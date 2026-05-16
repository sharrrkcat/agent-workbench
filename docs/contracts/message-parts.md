# Message Parts v2 Contract

Message Parts v2 is the new visible assistant content model. New Agent, Script
Agent, and Capability command replies persist:

```json
{
  "content_version": 2,
  "parts": []
}
```

`parts` is ordered and backend-validated. Runtime owns `content_version`;
Script Agent authors call `ctx.reply_parts(parts, metadata=None)` or existing
`reply_*` wrappers. Capability methods still declare `output.type` in their
manifest, but new visible command result messages are stored through parts.

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
then converted to parts. `rich_content.blocks` remains an input compatibility
format during the transition. Final messages use `form` for `action_form` blocks
and `command_buttons` for `command_buttons` blocks.

## Frontend Rendering

Round 3 makes the frontend renderer parts-first. When `message.parts` contains
at least one renderable part, chat renders ordered parts through
`MessagePartsRenderer`. Legacy `content` and `output_type` are fallback
compatibility fields for historical messages, streaming drafts, and transition
paths only.

Markdown `text` parts still receive render-time Knowledge citation enhancement:
inline `[K1]` tokens are matched against compact `snippet_refs` metadata and the
modal fetches chunk details by `chunk_id`. Chunk body text is not stored in
message parts or metadata. Plain `text` and raw `file` parts are not markdown
rendered.

`form` and `command_buttons` parts are the new primary path for action forms and
send-message shortcut buttons. Legacy `rich_content.blocks` remains accepted as
an input/fallback shape during the transition. Round 4 will remove old primary
renderer paths after verification.

## Legacy Compatibility

Round 3 still writes `content` and `output_type` as transition fields for API
tests, streaming draft display, and historical fallback rendering. They are
derived from parts where possible and are planned for removal in a later Message
Parts round. Do not copy full parts into metadata.

## Attachments

Generated images and files should still be saved as local attachments and
referenced by `/api/attachments/<id>` URLs or attachment ids. Durable message
parts must not introduce a new large base64 storage path.
