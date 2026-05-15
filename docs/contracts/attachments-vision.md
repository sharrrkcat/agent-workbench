# Attachments And Vision Contract

This contract owns chat attachments, Script Agent attachment helpers, Prompt
Agent file context, vision input, generated local attachments, and attachment
storage safety.

## Storage And Metadata

User attachments are stored as local refs in message metadata. Metadata keeps
attachment ids, type, MIME type, name, size, URI/URL, timestamps, dimensions, and
compact source details where relevant. It must not store full base64 payloads
for normal local attachments.

Generated files and images should be saved as local attachments and returned by
local URLs such as `/api/attachments/<id>.png`. Do not put large base64 data URLs
in durable message content.

Generated attachment metadata may record compact integration details such as
ComfyUI prompt id, preset id, workflow file name, and image type. ComfyUI final
galleries should use formal output images, such as SaveImage outputs; temporary,
preview, and input image refs are filtered before final rendering.

Legacy image attachments with `data_url` may remain supported for display and
vision compatibility, but new generated outputs should use attachment storage.

## Prompt Agent File Context

Prompt Agents may include ordinary text file attachment content in LLM context
only when General settings enable file context. Per-file and per-message byte
limits apply before provider calls. Truncated files are marked in generated
context and compact metadata.

When disabled, Prompt Agents add lightweight placeholders and do not read or
send text file contents. File context metadata records included attachment refs,
limits, truncation, and warnings without storing full file text.

`file_content` displays raw text and should not be markdown-rendered.

## Vision Input

Prompt Agents send image attachments to the LLM only when the resolved Model
Profile has `supports_vision=true`. Supported images are read from local storage
and converted to provider content parts for the current user message.

When vision is unsupported, image files are not read and image data is not sent
to the LLM. The model may receive a lightweight placeholder or warning such as
that images were attached but the selected model does not support vision.

Historical image attachments are not resent in LLM context unless a future
contract explicitly adds resend support. They remain stored in message metadata
and render in the UI.

## Script Agent Helpers

Script Agents are trusted local Python and may inspect current input
attachments through:

- `ctx.input.attachments`
- `ctx.read_attachment_text(attachment_or_id)`
- `ctx.read_attachment_bytes(attachment_or_id)`
- `ctx.attachment_as_data_url(attachment_or_id)`
- `await ctx.save_attachment_bytes(data, filename, mime_type, kind="file", metadata=None)`
- `await ctx.save_attachment_base64(data_base64, filename, mime_type, kind="file", metadata=None)`

Image attachments can be read by scripts regardless of Prompt Agent vision
support. Text/code/config files can be read by scripts through helpers; Prompt
Agent file context remains controlled separately by General settings.

Generated attachment helpers return local attachment metadata shaped like:

```json
{
  "id": "uuid",
  "type": "image",
  "mime_type": "image/png",
  "name": "result.png",
  "size": 12345,
  "uri": "local://attachments/<id>.png",
  "url": "/api/attachments/<id>.png",
  "created_at": "2026-05-08T12:00:00Z",
  "metadata": {"source": "optional"}
}
```

## Route And Store Safety

Local attachment serving resolves only files inside the configured attachment
directory. Attachment cleanup deletes only unreferenced local files inside that
directory and does not reset data, browse arbitrary folders, generate
thumbnails, export/import data, or sync to cloud storage.

Composer upload, drag-and-drop, paste, serving, Prompt Agent file context,
vision input, `file_content`, and attachment echo/test agents obey General
upload and file context limits. Active File and HTTP Capabilities have their own
CapabilityConfig limits and are not passive upload handling.

## Output Rendering Boundaries

Backend output type selects the frontend renderer:

- `markdown` renders as markdown.
- `file_content` renders as raw text.
- `image` and `image_gallery` require renderable URLs.
- `rich_content` preserves ordered blocks.

Renderer changes that alter payload shapes update
[../EXTENSION_API.md](../EXTENSION_API.md#output-payloads).

ComfyUI preset schema is documented in
[../COMFYUI_PRESET_SCHEMA.md](../COMFYUI_PRESET_SCHEMA.md). ComfyUI output
attachments are summarized here; workflow/preset behavior belongs to ComfyUI
docs and existing Agent/Capability development docs.
