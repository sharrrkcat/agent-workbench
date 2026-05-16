# Message Parts v2 Contract

Message Parts v2 is the new visible assistant content model. New Agent and
Script Agent replies persist:

```json
{
  "content_version": 2,
  "parts": []
}
```

`parts` is ordered and backend-validated. Runtime owns `content_version`; Script
Agent authors call `ctx.reply_parts(parts, metadata=None)` or existing
`reply_*` wrappers.

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

## Legacy Compatibility

Round 1 still writes `content` and `output_type` as transition fields for the
current frontend renderer and API tests. They are derived from parts where
possible and are planned for removal in a later Message Parts round. Do not
copy full parts into metadata.

## Attachments

Generated images and files should still be saved as local attachments and
referenced by `/api/attachments/<id>` URLs or attachment ids. Durable message
parts must not introduce a new large base64 storage path.
