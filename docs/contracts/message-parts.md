# Message Parts v2 Contract

Message Parts v2 is the only visible message content model.

```json
{
  "content_version": 2,
  "parts": []
}
```

`content_version` is required and currently fixed at `2`. `parts` is required
and defaults to an empty array. Messages do not expose `content` or
`output_type`, and `rich_content.blocks` is not a persistent message structure.
Metadata may store compact refs, counts, warnings, and runtime details, but it
must not duplicate full parts.

## Supported Parts

- `text`: `format` is `plain` or `markdown`. Prompt Agent final output is a
  markdown text part. Knowledge citations stay as inline `[K1]` tokens with
  compact `metadata.snippet_refs`; chunk text is fetched at render time.
- `json`: structured object or array data.
- `file`: inline raw text (`mode: inline_text`) or an attachment reference.
- `image`: one image by `url` or `attachment_id`.
- `audio`: one local attachment-backed audio file. v1 supports only
  `source: attachment` with `attachment_id`, `/api/attachments/<id>.<ext>` URL,
  and `audio/*` MIME type.
- `video`: one local attachment-backed video file. v1 supports only
  `source: attachment` with `attachment_id`, `/api/attachments/<id>.<ext>` URL,
  and `video/*` MIME type. Supported v1 extensions are `.mp4`, `.webm`, and
  `.ogv`.
- `media_group`: `layout: gallery` with image items.
- `form`: validated action form. It does not allow HTML, JavaScript, arbitrary
  URLs, file uploads, password/secret fields, or automatic execution.
- `command_buttons`: send-message shortcuts. Clicks submit ordinary user text.
- `notice` and `error`: simple structured status and error content.

Unknown part types fail validation. `diff`, `chart`, `table`, and `artifact`
are future work and are not accepted.

AudioPart v1 does not support remote URL sources, network downloads, TTS, ASR,
transcription, livestreams, playlists, or audio content understanding.
The built-in file Capability creates AudioParts through `/read-file <path>` when
the local file is detected as supported audio.
VideoPart v1 does not support remote URL sources, HTTP/HTTPS playback URLs,
`file:` URLs, data URLs, HLS/DASH manifests, livestreams, video metadata
parsing, thumbnails/posters, transcoding, OCR, ASR, transcription, or video
content understanding. The built-in file Capability creates VideoParts through
`/read-file <path>` when the local file is detected as supported video.

## Capability Outputs

Capability method declarations use Message Parts terms:

```yaml
output:
  part_type: text
  format: markdown
```

Supported declarations are:

- `part_type: text`, with `format: plain|markdown`.
- `part_type: json`.
- `part_type: file`, with `mode: inline_text`.
- `part_type: image`.
- `part_type: audio`.
- `part_type: video`.
- `part_type: media_group`, with `layout: gallery`.
- `part_type: parts`, for a validated list of message parts.

The built-in `file` Capability declares `/read-file` as `part_type: parts`
because it auto-detects supported local text, image, and audio files. Text files
return a raw `file` part with `mode: inline_text`; image files return an
`image` part; audio files return an attachment-backed `audio` part; video files
return an attachment-backed `video` part.

`output.type` is invalid. If a method omits `output`, the runtime infers the
current parts contract from the returned value: lists are validated as parts,
dicts become JSON unless they look like image/media payloads, and scalars become
plain text.

## Rendering

The frontend renders normal messages only through `MessagePartsRenderer`.
Missing or invalid parts produce a safe empty/error state, not a legacy fallback.
Copyable content and renderability checks are derived from parts and status.
Audio parts render with the project custom audio player, backed by a hidden
`<audio>` element without native browser controls.
Video parts render with a native `<video controls preload="metadata">` element
and only use local attachment URLs.

Forms and command buttons are first-class parts. Silent form updates replace the
matching `form` part in `Message.parts[]`.

## Attachments

Generated images, audio, video, and files should be saved as local attachments
and referenced by `/api/attachments/<id>` URLs or attachment ids. Message parts
must not create a new durable large-base64 storage path.
