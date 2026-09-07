# Message parts contract

Messages use `content_version: 2` and a validated `parts` array. The generic
message schema is strict (`extra="forbid"`) and stores role, speaker identity,
run/parent references, and compact metadata.

## Supported parts

- `text` with `plain` or `markdown` format;
- `json` data;
- `file` inline text or an attachment reference;
- `image`, `audio`, and `video` attachment/direct URL references;
- `media_group` image galleries;
- `notice` and `error` status parts.
- `tool_call` assistant data parts and `tool_result` tool data parts.

Unknown part types are rejected. There are no form, action, command-button or
diff parts. Large binary data belongs in the attachment store and is referenced
by id/URL. Tool parts are strict data records and do not route or execute text.

Tool calls require role=assistant, a unique call id within the run, a tool name
and finite JSON object arguments. Results require role=tool, a matching call id,
success/error/rejected/cancelled status, optional JSON data/error fields and a
truncation flag. Calls in one assistant message have distinct part ids.

## Rendering and context

The frontend renders parts without interpreting their text as routing
instructions. Markdown is displayed as content; copy/retry/edit operations use
the original text. ChatRunner projects text parts into model messages while
preserving speaker labels for group transcripts. Metadata may hold compact
source refs, counts, and warnings, but never duplicates full part bodies or
secrets.
Live harness transcripts use native assistant/tool protocol pairs. Historical
tool parts are quoted as data in ordinary and group context, allowing selected
or truncated history without orphan protocol calls. They never become
system/developer instructions. Tool call messages are not retryable replies.

Assistant messages from a Persona include a compact speaker id/name and may
include an avatar attachment reference snapshot. These are presentation data,
not routing instructions.
