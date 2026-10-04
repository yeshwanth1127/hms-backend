import hashlib
import io
import re
import uuid
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from sqlalchemy.orm import Session

from .config import settings
from .models import MediaAsset
from .services import DomainError

MAX_ASSET_BYTES = 16 * 1024 * 1024
MIME_LIMITS = {
    "guide": {"application/pdf": 10 * 1024 * 1024},
    "photo": {"image/png": 5 * 1024 * 1024, "image/jpeg": 5 * 1024 * 1024},
    "attachment": {
        "application/pdf": MAX_ASSET_BYTES,
        "image/png": MAX_ASSET_BYTES,
        "image/jpeg": MAX_ASSET_BYTES,
        "audio/ogg": MAX_ASSET_BYTES,
        "audio/mpeg": MAX_ASSET_BYTES,
        "video/mp4": MAX_ASSET_BYTES,
    },
}


def media_path(storage_name: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", storage_name):
        raise DomainError("INVALID_MEDIA_PATH", "Invalid media storage reference.", 500)
    return Path(settings.media_dir).resolve() / storage_name


def _matches(mime: str, data: bytes) -> bool:
    if mime == "application/pdf":
        if not data.startswith(b"%PDF-"):
            return False
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
            return not reader.is_encrypted and 0 < len(reader.pages) <= 100
        except Exception:
            return False
    if mime == "image/png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return False
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG" or image.width * image.height > 20_000_000:
                    return False
                image.verify()
            return True
        except (UnidentifiedImageError, OSError, ValueError):
            return False
    if mime == "image/jpeg":
        if not data.startswith(b"\xff\xd8\xff"):
            return False
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "JPEG" or image.width * image.height > 20_000_000:
                    return False
                image.verify()
            return True
        except (UnidentifiedImageError, OSError, ValueError):
            return False
    if mime == "audio/ogg":
        return data.startswith(b"OggS")
    if mime == "audio/mpeg":
        return data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xff and data[1] & 0xe0 == 0xe0)
    if mime == "video/mp4":
        return len(data) > 11 and data[4:8] == b"ftyp"
    return False


async def save_upload(db: Session, file: UploadFile, kind: str) -> MediaAsset:
    allowed = MIME_LIMITS[kind]
    mime = (file.content_type or "").lower().split(";", 1)[0]
    limit = allowed.get(mime)
    if not limit:
        raise DomainError("UNSUPPORTED_MEDIA", "That file type is not supported.", 415)
    data = await file.read(limit + 1)
    if not data or len(data) > limit:
        raise DomainError("INVALID_MEDIA_SIZE", "The file is empty or too large.", 413)
    if not _matches(mime, data):
        raise DomainError("INVALID_MEDIA_CONTENT", "The file content does not match its type.", 415)
    storage_name = uuid.uuid4().hex
    path = media_path(storage_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    asset = MediaAsset(kind=kind, original_name=Path(file.filename or "upload").name[:255],
                       mime_type=mime, storage_name=storage_name, size_bytes=len(data),
                       sha256=hashlib.sha256(data).hexdigest())
    db.add(asset)
    return asset


def asset_row(asset: MediaAsset) -> dict:
    return {"id": asset.id, "kind": asset.kind, "filename": asset.original_name,
            "mime_type": asset.mime_type, "size_bytes": asset.size_bytes,
            "sha256": asset.sha256, "created_at": asset.created_at}
