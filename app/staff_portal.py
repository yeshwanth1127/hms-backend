"""The staff UI ships in the API image and shares its origin and session."""
from pathlib import Path
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, RedirectResponse
from .services import DomainError
from .staff_auth import require_staff

router = APIRouter()
STATIC = Path(__file__).with_name("staff_static")


@router.get("/admin", include_in_schema=False)
@router.get("/admin/{path:path}", include_in_schema=False)
def legacy_admin(path: str = ""):
    return RedirectResponse("/staff/appointments", status_code=307)


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


@router.get("/talk", include_in_schema=False)
def talk_entry():
    return RedirectResponse("/talk/")


@router.get("/talk/", include_in_schema=False)
def talk_page():
    file = STATIC / "talk.html"
    if not file.is_file():
        raise DomainError("VOICE_UI_NOT_BUILT", "Build staff-web before opening the call screen.", 503)
    return FileResponse(file, media_type="text/html", headers={"Cache-Control": "no-store", "Permissions-Policy": "microphone=(self)", "Content-Security-Policy": "default-src 'self'; script-src 'self' blob:; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self' wss://*.sarvam.ai; worker-src 'self' blob:; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'"})


@router.get('/book', include_in_schema=False)
def book_entry(request: Request):
    return RedirectResponse('/book/' + ('?' + request.url.query if request.url.query else ''))


@router.get('/book/', include_in_schema=False)
def book_page():
    file = STATIC / 'book.html'
    if not file.is_file():
        raise DomainError('BOOKING_UI_NOT_BUILT', 'Build staff-web before opening booking.', 503)
    return FileResponse(file, media_type='text/html', headers={'Cache-Control': 'no-store',
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'", 'Referrer-Policy': 'no-referrer'})
