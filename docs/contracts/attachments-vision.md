# Attachments And Vision Contract

This contract owns chat attachments, Script Agent attachment helpers, Prompt
Agent file context, vision input, generated local attachments, and attachment
storage safety.

## Storage And Metadata

User attachments are stored as local refs in message metadata. Metadata keeps
attachment ids, type, MIME type, name, size, URI/URL, timestamps, dimensions, and
compact source details where relevant. It must not store full base64 payloads
for normal local attachments.

Generated files, audio, video, and images should be saved as local attachments
and returned by local URLs such as `/api/attachments/<id>.png`. Do not put large
base64 data URLs in durable message content.

Generated attachment metadata may record compact integration details such as
ComfyUI prompt id, preset id, workflow file name, and image type. ComfyUI final
galleries should use formal output images, such as SaveImage outputs; temporary,
preview, and input image refs are filtered before final rendering.

Legacy image attachments with `data_url` may remain supported for display and
vision compatibility, but new generated outputs should use attachment storage.

Message Parts v2 keeps the same storage rule. `image` parts should point at a
local attachment URL such as `/api/attachments/<id>.png` or carry an
`attachment_id` ref. `audio` and `video` parts are implemented as local
attachment refs only: `source` must be `attachment`, `url` must be a local
`/api/attachments/...` route, and `mime_type` must be `audio/*` or `video/*`.
`media_group` parts use image items with the same URL/ref shape. `file` parts
may carry small inline raw text with `mode="inline_text"`; long files and binary
files should be saved as attachments in later rounds.
Durable message parts must not introduce a new large base64 storage path.

## Prompt Agent File Context

Prompt Agents may include ordinary text file attachment content in LLM context
only when General settings enable file context. Per-file and per-message byte
limits apply before provider calls. Truncated files are marked in generated
context and compact metadata.

When disabled, Prompt Agents add lightweight placeholders and do not read or
send text file contents. File context metadata records included attachment refs,
limits, truncation, and warnings without storing full file text.

`file` parts display raw text and should not be markdown-rendered.

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
- `await ctx.reply_audio(audio_attachment_or_part, title=None, duration_ms=None, metadata=None)`
- `await ctx.save_attachment_file(source_path, filename=None, mime_type=None, kind="file", metadata=None)`
- `await ctx.reply_video(video_attachment_or_part, title=None, metadata=None)`

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

The file Capability exposes one local read command, `/read-file <path>`. It
auto-detects supported text, image, audio, and video files by extension/MIME policy.
Text returns a raw inline `file` part, image returns a local attachment-backed
`image` part, audio returns a local attachment-backed `audio` part, and video
returns a local attachment-backed `video` part. The single
`enable_read_file_command` toggle gates all four kinds, while
`max_local_text_read_size_mb`, `max_local_image_read_size_mb`,
`max_local_audio_read_size_mb`, and `max_local_video_read_size_mb` remain
independent size limits. The default video read limit is 5120 MB.

Generated audio attachments use `type: "audio"` and are stored under the local
attachment root's `audios` subdirectory, for example
`data/attachments/audios/<id>.wav`. Supported v1 formats include WAV, MP3, and
OGG, with M4A, FLAC, and WebM accepted by MIME/extension policy.

Generated video attachments use `type: "video"` and are stored under the local
attachment root's `videos` subdirectory, for example
`data/attachments/videos/<id>.mp4`. Supported v1 formats are MP4, WebM, and
OGV. Video saving from `/read-file` uses file copy and does not read the whole
video into Python memory.

The file Capability does not perform OCR, ASR/transcription, TTS, PDF parsing,
diff rendering, binary preview, network URL reads, web page fetching, video
metadata parsing, thumbnail generation, transcoding, streaming protocol
handling, or video input to LLMs.

The HTTP Capability exposes only `/fetch-url <url>` for user-facing network
reads. It returns Message Parts for supported text, HTML, JSON, and image
responses without creating a generalized remote attachment download/cache/proxy
path. It does not support HTTP audio/video, HLS/DASH, livestreams, radio,
podcasts, video-page media extraction, OCR, ASR/transcription, TTS, or PDF
parsing.

## Route And Store Safety

Local attachment serving resolves only files inside the configured attachment
directory. Attachment cleanup deletes only unreferenced local files inside that
directory and does not reset data, browse arbitrary folders, generate
thumbnails, export/import data, or sync to cloud storage.

Composer upload, drag-and-drop, paste, serving, Prompt Agent file context,
vision input, file parts, and attachment echo/test agents obey General
upload and file context limits. Active File and HTTP Capabilities have their own
CapabilityConfig limits and are not passive upload handling.

## Output Rendering Boundaries

Message Parts v2 selects the frontend renderer for new messages:

- markdown `text` parts render as markdown.
- `file` parts render raw inline text or attachment refs.
- `image` and `media_group` parts require renderable local attachment URLs or
  attachment ids.
- `audio` parts render local attachment audio with the project custom player,
  not native browser controls.
- `video` parts render local attachment video with native browser controls and
  `preload="metadata"`.
- `form` and `command_buttons` parts are the interactive block path.

Renderer changes that alter payload shapes update
[../EXTENSION_API.md](../EXTENSION_API.md#output-payloads).

Agent/Script outputs persist `content_version=2` and `parts`, with
image/file/media parts following the attachment rules above.

ComfyUI preset schema is documented in
[../COMFYUI_PRESET_SCHEMA.md](../COMFYUI_PRESET_SCHEMA.md). ComfyUI output
attachments are summarized here; workflow/preset behavior belongs to ComfyUI
docs and existing Agent/Capability development docs.
