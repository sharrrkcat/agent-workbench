# Attachments and vision contract

Attachments are local files referenced by message parts. Upload limits are
owned by `AppSettings`; durable message metadata stores ids, MIME type, name,
size, and compact status, never large base64 payloads.

Supported parts are `file`, `image`, `audio`, `video`, and `media_group`.
Attachment serving resolves only inside the configured attachment directory;
orphan cleanup is limited to unreferenced files there.

When the selected LLM profile advertises `supports_vision`, image attachments
from the current user message may be encoded as provider image content.
Otherwise they remain display-only and the model receives no image bytes.
Text attachment context is controlled by the General setting and per-file and
per-message byte limits. Historical attachments are not implicitly resent.

The existing explicit `/v1/vision` and `/api/inference/vision` skeletons use
vision model profiles and remain stateless. They do not create sessions,
messages, runs, or Knowledge rows.
