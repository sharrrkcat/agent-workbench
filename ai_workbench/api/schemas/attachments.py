from typing import Annotated

from pydantic import Field

from ai_workbench.api.schemas.common import ApiModel, ApiTimestamp, JsonObject, public_model
from ai_workbench.core.attachments import Attachment


AttachmentInput = public_model("AttachmentInput", Attachment, fields={
    "metadata": (JsonObject | None, Field(default=None, description="Optional finite JSON attachment metadata.")),
})
AttachmentResponse = public_model("AttachmentResponse", Attachment, omit={"data_url"}, fields={
    "uri": (str, ...), "url": (str, ...), "created_at": (ApiTimestamp, ...),
    "metadata": (JsonObject | None, Field(default=None, description="Optional finite JSON attachment metadata.")),
})


class AttachmentUpload(ApiModel):
    file: Annotated[bytes, Field(description="Exactly one uploaded file.", json_schema_extra={"format": "binary"})]


class AttachmentDeleted(ApiModel):
    deleted: bool
    attachment_id: str
