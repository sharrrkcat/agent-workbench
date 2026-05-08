# Capability Development

For compact API contracts and generated registry, see:

- [EXTENSION_API.md](EXTENSION_API.md)
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
      type: text

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

## Output Types

Allowed method output types:

- `text`
- `markdown`
- `json`
- `image`
- `image_gallery`
- `rich_content`
- `file_content`

Use `file_content` for source files, config files, logs, and other raw text that must not be interpreted as Markdown. Its payload includes `content` plus optional `filename`, `language`, `mime_type`, `size`, and `truncated` fields. The command runner validates image, image gallery, rich content, and file content payload shapes. If a command returns a dict and the method has no declared output type, it falls back to `json`.

For external service Capabilities, prefer stable JSON contracts over user-facing prose. The `comfyui` Capability is the reference shape for a REST + polling integration: low-level methods cover connection, queue, history, submit, non-blocking prompt status, fetch, interrupt, upload, and object info; helper methods normalize outputs and collect images for a prompt. It also owns local workflow and preset library directories, scanning API-format workflow files, rejecting unsupported GUI-format files, hash de-duplication, preset loading, preset validation, per-workflow draft skip reasons, and draft preset creation. It deliberately returns image references or base64 metadata rather than saving attachments, so a Script Agent can choose how to present or persist results. ComfyUI is an external service and local asset capability, not a user-facing workflow Agent by itself.

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
```

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
- allowed output types

## Common Errors

- Missing runtime method: add a method to `CapabilityRuntime` with the same name as the manifest method id.
- Duplicate command name: rename one command; command names are global across all Capabilities.
- Invalid command name: command names must start with `/`.
- Unsupported `output.type`: use one of the allowed output types above.
- Image output displayed as JSON: declare `output.type: image` and return an image payload with `url`.
- Manifest field typo: `check_agents.py --strict` reports the manifest path and object id where possible.

## Safety

Capability runtime code is trusted local Python code. The current project has no sandbox, permission system, or plugin isolation. Do not install or run Capability code from untrusted sources.
