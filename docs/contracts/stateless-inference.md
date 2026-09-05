# Stateless inference contract

The optional localhost service is disabled by default. It uses the same
ModelManager and adapters as internal chat and creates no sessions, messages,
runs, attachments or Knowledge rows. Transient model-status events and access
logs remain observable.

## Settings and guard

`GET/PATCH /api/models/settings` owns `external_enabled`,
`external_api_key` and `max_request_mb` (default 10). Enabling requires one
nonempty key. Authenticate with `Authorization: Bearer <key>` or
`x-api-key`; conflicting credentials are rejected. Non-loopback clients are
rejected independently of headers. The official launcher binds loopback only.

Both Content-Length and actual received bytes are checked. Strict request
schemas reject unsupported fields without echoing input values. Responses and
logs do not expose credentials, prompts, image data or raw provider errors.
Each response has X-Request-Id. Access logs include elapsed time and final
stream error/cancellation after the entire response ends.

## Endpoints and identities

- GET `/v1/models`: enabled, externally visible llm/embedding aliases.
- POST `/v1/chat/completions`: non-streaming or SSE chat.
- POST `/v1/embeddings`: text embeddings.

External model names must match the public alias exactly. UUIDs and prefixed
aliases are rejected. A profile must match the endpoint kind and capability
requirements. Missing providers/models never trigger model substitution.

## Chat subset

The request supports system/developer/user/assistant/tool messages, plain text
and user image_url parts (HTTP(S) or image data URL), function tools,
tool_choice, parallel_tool_calls, response_format and generation parameters.
Only `n=1` is accepted. response_format supports text, json_object and
json_schema with the matching profile capability. Tool result ids must match
preceding assistant calls. Unknown fields, legacy function-call fields,
unsupported formats and incomplete tool histories are rejected.

Tool definitions, choice, arguments and tool results are forwarded as data.
The service never executes tools. Ordinary internal chat rejects tool-call
responses; harness execution is Phase 4.

Responses keep one public id, created timestamp and alias across all chunks.
SSE contains content/tool-call fragments, one finish reason, optional usage
when stream_options.include_usage is true, and one `data: [DONE]`.
Tool-only non-streaming messages include `content: null`. Backend/load checks
run before headers; later inference/queue failures produce an explicit SSE
error and DONE. Disconnects close the upstream stream and release occupancy.
Malformed upstream chunks, invalid choices and truncated streams are errors.

## Embeddings and deferred operations

Input accepts a string or nonempty string array. encoding_format is float or
base64 (little-endian float32), and dimensions is optional. The manager applies
the profile's document instruction, batching, dimension validation and
normalization, shared with Knowledge document indexing. Knowledge queries use
the same profile's query instruction.

The old multimodal/vision endpoints and inference management routes are
deleted. Reranker remains an internal operation; public /v1/rerank, image
services remain deferred. Managed llama chat and Python text embeddings share
these existing endpoints and the same ModelManager with internal callers.
