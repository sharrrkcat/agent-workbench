from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
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
def get_attachment(attachment_id: str) -> Response:
    try:
        path = resolve_attachment_uri(attachment_id)
        mime_type = attachment_mime_type(attachment_id)
    except ValueError:
        raise_error(404, "ATTACHMENT_NOT_FOUND", "Attachment not found.")

    if not path.is_file():
        raise_error(404, "ATTACHMENT_NOT_FOUND", "Attachment not found.")
    return Response(content=path.read_bytes(), media_type=mime_type)
