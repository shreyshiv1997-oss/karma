"""Authenticated image upload and immutable object delivery.

Uploads terminate at the API so mobile/web clients never receive object-store credentials and never
need to reach an internal container hostname. The database records ownership and purpose; social
and gig routes accept only ready objects owned by the caller, not arbitrary remote URLs.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import CurrentUser, SessionDep
from app.core.ports import build_cache
from app.models.media import MediaObject
from app.schemas.media import MediaObjectOut
from app.services.storage import StorageUnavailable, object_storage

router = APIRouter(prefix="/media", tags=["Media"])
_cache = build_cache()
_ALLOWED_PURPOSES = {"post", "gig", "proof_before", "proof_after"}
_READ_CHUNK = 1024 * 1024


def _sniff_image(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def media_path(object_id: str) -> str:
    return f"{settings.API_PREFIX}/media/objects/{object_id}"


def _object_id(reference: str) -> str | None:
    try:
        parsed = urlsplit(reference)
    except ValueError:
        return None
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        return None
    prefix = f"{settings.API_PREFIX}/media/objects/"
    if not parsed.path.startswith(prefix):
        return None
    raw = parsed.path.removeprefix(prefix)
    if "/" in raw or not raw:
        return None
    try:
        return str(UUID(raw))
    except ValueError:
        return None


async def validate_media_references(
    session,
    *,
    owner_id: int,
    references: list[str],
    purposes: set[str] | None = None,
    purpose_sequence: list[str] | None = None,
) -> list[str]:
    """Resolve client references to canonical API paths after ownership/purpose checks."""
    if not references:
        return []
    ids = [_object_id(reference) for reference in references]
    if any(value is None for value in ids) or len(set(ids)) != len(ids):
        raise HTTPException(
            status_code=422,
            detail="Media must be unique objects returned by the KARMA upload endpoint",
        )
    if purpose_sequence is not None and len(purpose_sequence) != len(ids):
        raise HTTPException(status_code=422, detail="Media purposes do not match this request")

    rows = (
        await session.execute(select(MediaObject).where(MediaObject.id.in_(ids)))
    ).scalars().all()
    by_id = {row.id: row for row in rows}
    canonical: list[str] = []
    for index, object_id in enumerate(ids):
        row = by_id.get(object_id)
        required = purpose_sequence[index] if purpose_sequence is not None else None
        if (
            row is None
            or row.owner_id != owner_id
            or row.status != "ready"
            or (purposes is not None and row.purpose not in purposes)
            or (required is not None and row.purpose != required)
        ):
            # Do not reveal whether a guessed id exists or who owns it.
            raise HTTPException(status_code=422, detail="Media object is not valid for this request")
        canonical.append(media_path(row.id))
    return canonical


@router.post("/uploads", response_model=MediaObjectOut, status_code=status.HTTP_201_CREATED)
async def upload_media(
    user: CurrentUser,
    session: SessionDep,
    purpose: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> MediaObjectOut:
    try:
        uploads = await _cache.incr_window(
            f"karma:media:upload:{user.id}", settings.MEDIA_UPLOAD_WINDOW
        )
    except Exception as exc:
        # The budget is a correctness boundary in multi-worker production. Uploading while it
        # is unavailable would turn an object endpoint into unbounded storage consumption.
        raise HTTPException(status_code=503, detail="Upload protections are unavailable") from exc
    if uploads > settings.MEDIA_UPLOAD_LIMIT:
        raise HTTPException(status_code=429, detail="Upload limit reached; try again later")
    if purpose not in _ALLOWED_PURPOSES:
        raise HTTPException(status_code=422, detail="Unsupported media purpose")

    maximum = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    try:
        while chunk := await file.read(_READ_CHUNK):
            total += len(chunk)
            if total > maximum:
                raise HTTPException(
                    status_code=413,
                    detail=f"Image exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB upload limit",
                )
            chunks.append(chunk)
    finally:
        await file.close()
    data = b"".join(chunks)
    image = _sniff_image(data)
    if image is None:
        raise HTTPException(
            status_code=415,
            detail="Only JPEG, PNG, and WebP image bytes are accepted",
        )
    content_type, extension = image
    claimed = (file.content_type or "").lower()
    aliases = {"image/jpg": "image/jpeg"}
    claimed = aliases.get(claimed, claimed)
    if claimed not in {"", "application/octet-stream", content_type}:
        raise HTTPException(status_code=415, detail="Declared and detected image types differ")

    object_id = str(uuid4())
    now = datetime.now(UTC)
    key = f"users/{user.id}/{now:%Y/%m}/{object_id}.{extension}"
    digest = hashlib.sha256(data).hexdigest()
    row = MediaObject(
        id=object_id,
        owner_id=user.id,
        purpose=purpose,
        storage_key=key,
        content_type=content_type,
        byte_size=len(data),
        sha256=digest,
        status="uploading",
    )
    session.add(row)
    await session.flush()
    try:
        await object_storage.put(
            key,
            data,
            content_type=content_type,
            sha256=digest,
        )
    except StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    row.status = "ready"
    await session.flush()
    return MediaObjectOut(
        id=row.id,
        purpose=row.purpose,
        url=media_path(row.id),
        content_type=row.content_type,
        byte_size=row.byte_size,
        sha256=row.sha256,
    )


@router.get("/objects/{object_id}", name="get_media_object")
async def get_media_object(object_id: UUID, session: SessionDep) -> Response:
    row = await session.get(MediaObject, str(object_id))
    if row is None or row.status != "ready":
        raise HTTPException(status_code=404, detail="Media object not found")
    try:
        stored = await object_storage.get(row.storage_key)
    except StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if stored is None:
        raise HTTPException(status_code=404, detail="Media object not found")
    digest = hashlib.sha256(stored.data).hexdigest()
    if len(stored.data) != row.byte_size or not hmac.compare_digest(digest, row.sha256):
        raise HTTPException(status_code=503, detail="Media object failed its integrity check")
    return Response(
        content=stored.data,
        media_type=row.content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{row.sha256}"',
            "Content-Disposition": f'inline; filename="{row.id}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
