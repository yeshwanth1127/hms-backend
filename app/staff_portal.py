"""The staff UI ships in the API image and shares its origin and session."""
from pathlib import Path
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, RedirectResponse
from .services import DomainError
from .staff_auth import require_staff

router = APIRouter()
STATIC = Path(__file__).with_name("staff_static")


@router.get("/staff", include_in_schema=False)
def entry():
    return RedirectResponse("/staff/whatsapp")


@router.get("/staff/{path:path}", include_in_schema=False)
def staff_page(path: str):
    if path.startswith("assets/"):
        file = (STATIC / path).resolve()
        if STATIC.resolve() not in file.parents or not file.is_file():
            raise DomainError("ASSET_NOT_FOUND", "Workspace asset was not found.", 404)
        return FileResponse(file)
    index = STATIC / "index.html"
    if not index.is_file():
        raise DomainError("STAFF_UI_NOT_BUILT", "Build staff-web before starting the staff workspace.", 503)
    return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-store"})


@router.get("/api/v1/staff/design-guide")
def design_guide(user=Depends(require_staff)):
    return {"title": "The clinic workspace", "markdown": Path(__file__).resolve().parents[1].joinpath("STAFF_WORKSPACE_UX_DECISION_BOOK.md").read_text()}
