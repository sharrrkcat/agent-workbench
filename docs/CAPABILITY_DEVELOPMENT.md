# Capability Development

For compact API contracts, runtime contracts, and generated registry, see:

- [EXTENSION_API.md](EXTENSION_API.md)
- [RUNTIME_PROTOCOLS.md](RUNTIME_PROTOCOLS.md)
- [generated/REGISTRY.md](generated/REGISTRY.md)

Capabilities live under `capabilities/<capability_id>/` with a `capability.yaml` manifest and a Python runtime in `__init__.py`. Capability ids are global, lowercase snake_case, and unique.

Use the template generator:

```powershell
uv run python scripts/create_capability.py demo_tool
uv run python scripts/create_capability.py text_tools --name "Text Tools Capability"
```

Add `--dry-run` to preview files and `--force` only when intentionally overwriting a local template directory.

## Minimal Capability

`capabilities/demo_tool/capability.yaml`:

```yaml
id: demo_tool
name: Demo Tool
description: Small developer test capability.

methods:
  - id: echo
    description: Echo input text.
    input_schema:
      text:
        type: string
        required: true
    output:
      part_type: text
      format: plain

commands:
  - name: /demo_tool
    method: echo
    description: Echo input text.
    safe: true
```

`capabilities/demo_tool/__init__.py`:

```python
class CapabilityRuntime:
    def echo(self, text: str) -> str:
        return text


def get_runtime():
    return CapabilityRuntime()
```

The runtime may export either `get_runtime()` or `CapabilityRuntime`. Strict checks verify that every manifest method has a matching callable runtime method.

## Commands

Commands are user-facing wrappers declared in Capability manifests. They are global and must start with `/`.

```text
/demo_tool hello
/base64 hello
/base64-decode aGVsbG8=
```

Agents do not declare slash commands. Keep the `@agent` and `/command` namespaces separate.

## Output Parts

Capability command result messages use Message Parts v2 as the visible content
authority. Manifest methods declare `output.part_type`:

- `part_type: text` with `format: plain` or `format: markdown`.
- `part_type: json`.
- `part_type: file` with `mode: inline_text`.
- `part_type: image`.
- `part_type: audio`.
- `part_type: video`.
- `part_type: media_group` with `layout: gallery`.
- `part_type: parts` for a validated list of message parts.

`output.type` is rejected by strict checks and manifest loading. If a command
returns a dict and the method has no declared output, the runner infers the
current parts contract, normally JSON unless the payload is shaped like an image
or media group. Use `file` parts for source files, config files, logs, and other
raw text that must not be interpreted as Markdown. Use `audio` parts only for
local attachment-backed audio payloads with `source: attachment`; remote audio
URLs, TTS, ASR, and transcription are not implemented. Use `video` parts only
for local attachment-backed video payloads with `source: attachment`; remote
video URLs, HLS/DASH/livestream sources, metadata parsing, thumbnails,
transcoding, and video input to LLMs are not implemented.

For external service Capabilities, prefer stable JSON contracts over user-facing prose. The `comfyui` Capability is the reference shape for a REST + polling integration: low-level methods cover connection, queue, history, submit, non-blocking prompt status, fetch, interrupt, upload, object info, and `free_memory` for ComfyUI `POST /free`; helper methods normalize outputs and collect images for a prompt. It also owns local workflow and preset library directories, scanning API-format workflow files, rejecting unsupported GUI-format files, hash de-duplication, preset loading, preset validation, per-workflow draft skip reasons, and draft preset creation. The preset YAML schema is documented in [COMFYUI_PRESET_SCHEMA.md](COMFYUI_PRESET_SCHEMA.md). It deliberately returns image references or base64 metadata rather than saving attachments, so a Script Agent can choose how to present or persist results. `free_memory` is a protocol method only: it requests unload/free behavior from the connected ComfyUI service and does not decide whether a user workflow should call it. ComfyUI is an external service and local asset capability, not a user-facing workflow Agent by itself.

The `knowledge` Capability is a thin wrapper over Workbench-owned Knowledge
storage and retrieval. It exposes `search`, `list_bases`, and `stats` for Script
Agents and `/kb-search` for explicit manual search of the current session active
KBs. Full Knowledge ownership lives in
[contracts/knowledge.md](contracts/knowledge.md).

## CLI Workflow

Create and test a Capability:

```powershell
uv run python scripts/create_capability.py demo_tool
uv run python scripts/check_agents.py --strict
uv run python scripts/run_command.py "/demo_tool hello"
```

Test built-in commands:

```powershell
uv run python scripts/run_command.py "/base64 hello"
uv run python scripts/run_command.py "/base64-decode aGVsbG8="
uv run python scripts/run_command.py "/base64-image data:image/svg+xml;base64,..."
uv run python scripts/run_command.py "/image-base64" --image path/to/cat.png
uv run python scripts/run_command.py "/read-file path/to/demo.wav"
uv run python scripts/run_command.py "/read-file path/to/demo.mp4"
uv run python scripts/run_command.py "/kb-search project notes"
```

The built-in `file` Capability exposes only `/read-file <path>` for user-facing
local reads. It auto-detects supported text, image, audio, and video files and
returns the matching Message Part: raw inline `file` for text, `image` for
images, attachment-backed `audio` for audio, and attachment-backed `video` for
video. It keeps separate text/image/audio/video size limits behind one
`enable_read_file_command` toggle; `max_local_video_read_size_mb` defaults to
5120. Video v1 supports `.mp4`, `.webm`, and `.ogv`. It does not support OCR,
ASR/transcription, TTS, PDF parsing, diff rendering, binary preview, network URL
reads, web page fetching, HLS/DASH/livestream sources, video metadata parsing,
thumbnail generation, transcoding, or video input to LLMs.

For image output, CLI summaries show MIME type, approximate decoded size, URL prefix, and URL length instead of printing the full data URL.

Use JSON output for automation:

```powershell
uv run python scripts/check_agents.py --strict --json
uv run python scripts/run_command.py "/base64 hello" --json
```

## Strict Checks

`uv run python scripts/check_agents.py --strict` checks:

- manifest loading for Agents and Capabilities
- Agent id and Capability id matching their directory names
- required manifest fields
- legal Agent types
- script entry file existence and importability
- `async def run(ctx)` for Script Agents
- duplicate and invalid action ids
- Agent capability references
- `llm.profile` format when present
- runtime importability
- `get_runtime()` or `CapabilityRuntime`
- manifest methods matching runtime callables
- command methods matching manifest methods
- command names starting with `/`
- duplicate global command names
- allowed output part declarations

## Common Errors

- Missing runtime method: add a method to `CapabilityRuntime` with the same name as the manifest method id.
- Duplicate command name: rename one command; command names are global across all Capabilities.
- Invalid command name: command names must start with `/`.
- Unsupported `output.type`: replace it with `output.part_type`.
- Image output displayed as JSON: declare `output.part_type: image` and return an image payload with `url`.
- Manifest field typo: `check_agents.py --strict` reports the manifest path and object id where possible.

## Safety

Capability runtime code is trusted local Python code. The current project has no sandbox, permission system, or plugin isolation. Do not install or run Capability code from untrusted sources.
