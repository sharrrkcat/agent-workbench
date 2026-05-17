from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response
from starlette.datastructures import UploadFile

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.attachments import attachment_mime_type, resolve_attachment_uri, save_attachment_from_upload


router = APIRouter(prefix="/api/attachments", tags=["attachments"])


@router.post("")
async def upload_attachment(request: Request, state: RuntimeState = Depends(get_state)) -> dict:
    form = await request.form()
    items = form.getlist("file")
    if len(items) != 1 or not isinstance(items[0], UploadFile):
        raise_error(422, "INVALID_ATTACHMENT_UPLOAD", "Upload exactly one file field.")
    file = items[0]
    data = await file.read()
    try:
        return save_attachment_from_upload(
            name=file.filename or "attachment.txt",
            mime_type=file.content_type or "application/octet-stream",
            data=data,
            settings=state.app_settings.get(),
        )
    except ValueError as exc:
        raise_error(400, "INVALID_ATTACHMENT", str(exc) or "Invalid attachment.")


@router.get("/{attachment_id:path}")
def get_attachment(attachment_id: str, request: Request) -> Response:
    try:
        path = resolve_attachment_uri(attachment_id)
        mime_type = attachment_mime_type(attachment_id)
    except ValueError:
        raise_error(404, "ATTACHMENT_NOT_FOUND", "Attachment not found.")

    if not path.is_file():
        raise_error(404, "ATTACHMENT_NOT_FOUND", "Attachment not found.")

    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(
            path,
            media_type=mime_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )

    byte_range = parse_byte_range(range_header, file_size)
    if byte_range is None:
        return Response(
            status_code=416,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes */{file_size}",
                "Content-Length": "0",
            },
        )

    start, end = byte_range
    content = read_file_range(path, start, end)
    return Response(
        status_code=206,
        content=content,
        media_type=mime_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(len(content)),
        },
    )


def parse_byte_range(range_header: str, file_size: int) -> tuple[int, int] | None:
    value = range_header.strip()
    if not value.startswith("bytes=") or "," in value:
        return None
    if file_size <= 0:
        return None

    spec = value.removeprefix("bytes=").strip()
    if "-" not in spec:
        return None
    start_text, end_text = spec.split("-", 1)
    if not start_text and not end_text:
        return None

    try:
        if not start_text:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                return None
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
            return start, end

        start = int(start_text)
        if start < 0 or start >= file_size:
            return None
        if not end_text:
            return start, file_size - 1

        end = int(end_text)
        if end < start:
            return None
        return start, min(end, file_size - 1)
    except ValueError:
        return None


def read_file_range(path: Path, start: int, end: int) -> bytes:
    with path.open("rb") as file:
        file.seek(start)
        return file.read(end - start + 1)
