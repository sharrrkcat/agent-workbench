# Message Parts v2 Contract

Message Parts v2 is the current visible assistant content model. New Agent,
Script Agent, and Capability command replies persist:

```json
{
  "content_version": 2,
  "parts": []
}
```

`parts` is ordered and backend-validated. Runtime owns `content_version`.
`Message.parts[]` is the only new-message visible content authority.
`content` and `output_type` are deprecated compatibility fields and may be
empty/null on new assistant and command messages. Script Agent authors call
`ctx.reply_parts(parts, metadata=None)` or existing typed `reply_*` wrappers.
Capability methods still declare `output.type` in their manifest, but new
visible command result messages are stored through parts.

## Supported Parts

- `text`: `{ "type": "text", "format": "plain|markdown", "text": "..." }`.
  Prompt Agent final output uses markdown text. Knowledge citations remain
  inline `[K1]` tokens with compact metadata refs.
- `json`: `{ "type": "json", "data": {...} }` or array data. JSON is not stored
  as a markdown code block.
- `file`: small inline raw text with `mode="inline_text"`, `content`,
  `filename`, `language`, `mime_type`, and `truncated`. Raw file text must not
  be markdown-rendered. Long or binary files should use attachments in later
  rounds.
- `image`: one image with `url` or `attachment_id`, plus optional `alt`.
- `media_group`: gallery layout with image items; Round 1 uses this for legacy
  image galleries only.
- `form`: validated action form content. It keeps existing form safety rules:
  no HTML, frontend JavaScript, arbitrary URLs, file uploads, password/secret
  fields, remote options, or automatic execution.
- `command_buttons`: send-message shortcut buttons. Clicks send ordinary user
  messages only.
- `notice` and `error`: structured simple notices and errors.

Future part types may include audio, video, diff, chart, table, and artifact,
but Round 1 does not implement renderers or backend helpers for them.

## Capability Command Outputs

Round 2 makes Capability command output parts-first. Declared output types map
to parts before persistence:

- `text` -> plain `text` part.
- `markdown` -> markdown `text` part.
- `json` -> `json` part.
- `file_content` -> inline-text `file` part.
- `image` -> `image` part.
- `image_gallery` -> gallery `media_group` part.
- `rich_content.blocks` -> ordered parts.

If a command returns a dict without a declared output type, the runner may still
infer `json`, `image`, `image_gallery`, or `rich_content`; the inferred shape is
then converted to parts. `rich_content.blocks` remains only an input
compatibility format for legacy Capability payloads or old helper calls. It is
not a persistent message structure for new messages. Final messages use `form`
for `action_form` blocks and `command_buttons` for `command_buttons` blocks.

## Frontend Rendering

The frontend renderer uses parts as the normal path. When `message.parts`
contains at least one renderable part, chat renders ordered parts through
`MessagePartsRenderer`. Legacy `content`, `output_type`, and
`rich_content.blocks` are a deprecated no-parts fallback for old or invalid
messages only.

Markdown `text` parts still receive render-time Knowledge citation enhancement:
inline `[K1]` tokens are matched against compact `snippet_refs` metadata and the
modal fetches chunk details by `chunk_id`. Chunk body text is not stored in
message parts or metadata. Plain `text` and raw `file` parts are not markdown
rendered.

`form` and `command_buttons` parts are the primary path for action forms and
send-message shortcut buttons. Silent form updates modify the authoritative
`form` part first and use legacy block replacement only for no-parts fallback
messages.

## Legacy Compatibility

`content` and `output_type` remain in the DB/API for deprecated compatibility
and streaming draft text. New final assistant and command messages do not
require them for visible content, and they may be empty/null.
`parts_to_legacy_output` and `legacy_output_to_parts` are compatibility
utilities, not the runtime new-message output path. Do not copy full parts into
metadata.

Round 5 will tighten tests and docs further and reserve the second-batch part
types without implementing audio, video, diff, chart, table, or artifact.

## Attachments

Generated images and files should still be saved as local attachments and
referenced by `/api/attachments/<id>` URLs or attachment ids. Durable message
parts must not introduce a new large base64 storage path.
