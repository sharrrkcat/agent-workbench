from fastapi import APIRouter
from fastapi.responses import Response

from ai_workbench.api.errors import raise_error
from ai_workbench.core.attachments import attachment_mime_type, resolve_attachment_uri


router = APIRouter(prefix="/api/attachments", tags=["attachments"])


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
