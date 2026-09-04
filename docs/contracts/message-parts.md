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

Unknown part types are rejected. There are no form, action, command-button,
diff, or registry-specific parts. Large binary data belongs in the attachment
store and is referenced by id/URL.

## Rendering and context

The frontend renders parts without interpreting their text as routing
instructions. Markdown is displayed as content; copy/retry/edit operations use
the original text. ChatRunner projects text parts into model messages while
preserving speaker labels for group transcripts. Metadata may hold compact
source refs, counts, and warnings, but never duplicates full part bodies or
secrets.
