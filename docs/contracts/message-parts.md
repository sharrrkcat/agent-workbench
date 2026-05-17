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
- `audio`: one audio file. It supports local attachment-backed audio with
  `source: attachment`, `attachment_id`, `/api/attachments/<id>.<ext>` URL, and
  `audio/*` MIME type. It also supports direct remote audio with `source: url`,
  an `http://` or `https://` URL, and `audio/*` MIME type.
- `video`: one video file. It supports local attachment-backed video with
  `source: attachment`, `attachment_id`, `/api/attachments/<id>.<ext>` URL, and
  `video/*` MIME type. It also supports direct remote video with `source: url`,
  an `http://` or `https://` URL, and `video/*` MIME type.
- `media_group`: `layout: gallery` with image items.
- `form`: validated action form. It does not allow HTML, JavaScript, arbitrary
  URLs, file uploads, password/secret fields, or automatic execution.
- `command_buttons`: send-message shortcuts. Clicks submit ordinary user text.
- `notice` and `error`: simple structured status and error content.

Unknown part types fail validation. `diff`, `chart`, `table`, and `artifact`
are future work and are not accepted.

AudioPart `source: url` is only for safe HTTP/HTTPS direct audio links. It does
not allow `file:`, `data:`, `javascript:`, or `blob:` URLs and must not include
`attachment_id`. AudioPart does not support network downloads, remote
attachment caching, HTTP media proxying, HLS/DASH manifests, `.m3u8`, `.mpd`,
`.pls`, livestreams, radio, podcast RSS, TTS, ASR, transcription, audio input
to LLMs, or audio content understanding. The built-in file Capability creates
attachment-backed AudioParts through `/read-file <path>` when the local file is
detected as supported audio.
VideoPart `source: url` is only for safe HTTP/HTTPS direct video links. It does
not allow `file:`, `data:`, `javascript:`, or `blob:` URLs and must not include
`attachment_id`. VideoPart requires `video/*` MIME type. Remote poster URLs are
not supported; `poster_url`, when present, must remain a local attachment URL.
VideoPart does not support network downloads, remote attachment caching, HTTP
media proxying, HLS/DASH manifests, `.m3u8`, `.mpd`, livestreams, video page
extraction, metadata parsing, thumbnail or poster generation, transcoding, OCR,
ASR, transcription, video input to LLMs, or video content understanding. The
built-in file Capability creates attachment-backed VideoParts through
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

The built-in `http` Capability declares `/fetch-url` as `part_type: parts`
because it auto-detects supported remote text, HTML, JSON, image, direct audio,
and direct video responses. Plain text returns a plain `text` part, HTML returns
lightweight extracted page text, JSON returns a `json` part, images return an
`image` part, direct audio returns an AudioPart with `source: url`, and direct
video returns a VideoPart with `source: url`. HTTP audio and video are not
downloaded, cached, saved as local attachments, or proxied. HLS/DASH, `.m3u8`,
`.mpd`, `.pls`, livestream/radio/podcast extraction, video page extraction,
OCR, ASR, TTS, transcription, audio/video understanding, and PDF parsing are
not implemented.

`output.type` is invalid. If a method omits `output`, the runtime infers the
current parts contract from the returned value: lists are validated as parts,
dicts become JSON unless they look like image/media payloads, and scalars become
plain text.

## Rendering

The frontend renders normal messages only through `MessagePartsRenderer`.
Missing or invalid parts produce a safe empty/error state, not a legacy fallback.
Copyable content and renderability checks are derived from parts and status.
Audio parts render with the project custom audio player, backed by a hidden
`<audio>` element without native browser controls. Remote `source: url` playback
depends on browser support and the remote server's Content-Type, Range, CORS,
and hotlink behavior; the workbench does not proxy or repair remote media.
Video parts render with a native `<video controls preload="metadata">` element.
They accept local attachment URLs for `source: attachment` and HTTP/HTTPS direct
video URLs for `source: url`. Remote playback depends on browser support and
the remote server's Content-Type, Range, CORS, and hotlink behavior; the
workbench does not proxy or repair remote media.

Forms and command buttons are first-class parts. Silent form updates replace the
matching `form` part in `Message.parts[]`.

## Attachments

Generated images, audio, video, and files should be saved as local attachments
and referenced by `/api/attachments/<id>` URLs or attachment ids. Message parts
must not create a new durable large-base64 storage path.
