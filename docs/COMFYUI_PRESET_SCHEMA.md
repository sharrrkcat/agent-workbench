# ComfyUI Preset Schema

This document defines the ComfyUI preset YAML format used by the ComfyUI Capability and ComfyUI Agent. It is written for AI agents, developers, and users who hand-edit preset files.

## Concepts

- Workflow file: a ComfyUI API-format workflow JSON file.
- Preset file: YAML that references one workflow file and declares parameter schema, mappings, defaults, and output policy.
- Session recipe: a per-session runtime copy of one preset plus user-edited values. Editing a recipe does not rewrite the preset file.
- Generation request: one execution built from workflow file -> preset -> session recipe -> filled workflow request.

## Locations

- `workflows_dir` comes from the ComfyUI `CapabilityConfig`.
- `presets_dir` comes from the ComfyUI `CapabilityConfig`.
- `preset.workflow.file_name` must be a file name only, such as `base_workflow.json`.
- Do not use `../`, path separators, or absolute paths in `workflow.file_name`.

## Workflow Requirements

Workflow JSON must be ComfyUI API format, not GUI format. GUI-format exports with top-level keys such as `nodes`, `links`, or `widgets_values` are currently unsupported.

The workflow must be a non-empty top-level object:

```json
{
  "6": {
    "class_type": "CLIPTextEncode",
    "inputs": {
      "text": ""
    }
  }
}
```

The canonical hash is `sha256:` plus the SHA-256 of JSON serialized with sorted keys and compact separators. A hash mismatch is reported as a warning so users can intentionally update workflows and then refresh the recorded hash.

## Canonical Preset

```yaml
id: base_workflow
name: Base Workflow
description: Basic txt2img workflow.
status: ready

workflow:
  file_name: base_workflow.json
  hash: sha256:...

parameters:
  - name: positive_prompt
    type: textarea
    label: Positive prompt
    required: true
    default: ""
    ui:
      section: prompts
      span: 12
    mapping:
      node_id: "6"
      input_path: ["inputs", "text"]

  - name: sampler_name
    type: enum
    label: Sampler
    default: euler
    ui:
      section: sampling
      span: 4
    options:
      - value: euler
        label: Euler
      - value: dpmpp_2m
        label: DPM++ 2M
    mapping:
      node_id: "3"
      input_path: ["inputs", "sampler_name"]

output:
  images: all
```

Optional top-level form layout sections:

```yaml
ui:
  sections:
    - key: prompts
      title: Prompts
    - key: sampling
      title: Sampling
    - key: image
      title: Image
    - key: output
      title: Output
```

## Field Rules

- Top-level `id` is the preset id and must be lowercase slug-like text.
- Parameter declarations use `name`, not `id`.
- Mappings use `mapping.node_id` and `mapping.input_path`, not `target` or `input`.
- Supported parameter `type` values are `text`, `textarea`, `integer`, `float`, `boolean`, `enum`, and `json`.
- `default` must match the declared `type`.
- Numeric parameters may define `minimum`, `maximum`, and `step`.
- `required: true` means the session recipe must provide a non-empty value before generation. In LLM mode, `positive_prompt` may be filled by the prompt enhancer before generation.
- Custom parameter fields are allowed and preserved as long as required schema and `mapping` fields are present.
- Enum parameters must have non-empty `options`.
- Enum `options` items must be objects shaped as `{value, label}`.
- Optional `parameter.ui` may shape the ComfyUI Agent recipe form. `ui.section` is an optional non-empty string. `ui.span` is an optional integer from 1 to 12 for a 12-column frontend grid.
- Optional top-level `ui.sections` is an array of `{key, title?}` section labels.
- `ui.order` is not supported. To change form order, reorder the `parameters` array. Section order is based on the first parameter that uses each section, and field order within a section remains the `parameters` array order.
- `ui` does not affect workflow generation, parameter mapping, or recipe values. Missing `ui` uses Agent/frontend default layout rules.
- Collapsible sections, `default_open`, nested layout, row layout DSL, dynamic onchange refresh, and automatic field mapping are not part of this schema.

## Status

Supported `status` values:

- `ready`: valid and available for forms and generation.
- `needs_mapping`: may have empty `parameters`; valid for draft/library display but cannot generate.
- `disabled`: ignored by the Agent.

`needs_mapping` presets do not appear as selectable ready recipe options.

## Output

The first version supports:

```yaml
output:
  images: all
```

Unknown output fields are warnings. Do not invent complex output shapes for runtime behavior yet.

## Minimal Legal Preset

```yaml
id: minimal_txt2img
name: Minimal Txt2Img
status: ready
workflow:
  file_name: minimal_txt2img.json
parameters:
  - name: positive_prompt
    type: textarea
    required: true
    default: ""
    mapping:
      node_id: "6"
      input_path: ["inputs", "text"]
output:
  images: all
```

## Typical Mappings

KSampler:

```yaml
- name: steps
  type: integer
  default: 30
  minimum: 1
  maximum: 150
  mapping:
    node_id: "3"
    input_path: ["inputs", "steps"]
```

CLIPTextEncode:

```yaml
- name: positive_prompt
  type: textarea
  required: true
  default: ""
  mapping:
    node_id: "6"
    input_path: ["inputs", "text"]
```

SaveImage filename prefix:

```yaml
- name: filename_prefix
  type: text
  default: workbench
  mapping:
    node_id: "9"
    input_path: ["inputs", "filename_prefix"]
```

## Common Errors

Wrong:

```yaml
parameters:
  - id: positive_prompt
    type: textarea
```

Correct:

```yaml
parameters:
  - name: positive_prompt
    type: textarea
```

Wrong:

```yaml
target:
  node_id: "6"
input: ["inputs", "text"]
```

Correct:

```yaml
mapping:
  node_id: "6"
  input_path: ["inputs", "text"]
```

Other common failures:

- `enum` options are empty.
- `workflow.file_name` contains a path.
- The workflow file is GUI format instead of API format.
- `mapping.node_id` does not exist in the workflow.
- `mapping.input_path` cannot be found.
- `workflow.hash` does not match the canonical workflow hash.
- `parameter.ui.span` is outside 1..12 or is not an integer.
- `parameter.ui.order` is present; reorder `parameters` instead.

## AI Checklist

Before writing or editing a preset:

- Confirm the workflow JSON is API format.
- Use only the workflow file basename in `workflow.file_name`.
- Use `parameter.name`, not `parameter.id`.
- Use `mapping.node_id` and `mapping.input_path`.
- Confirm every mapped `node_id` exists.
- Confirm every `input_path` exists in that node.
- Give every `enum` a non-empty list of `{value, label}` options.
- Use `ui.section` and `ui.span` for compact recipe forms.
- Do not use `ui.order`.
- Keep field order in `parameters`.
- Keep `needs_mapping` for drafts that are not generation-ready.
- Use `output.images: all`.
