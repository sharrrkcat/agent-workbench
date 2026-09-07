# Runtime protocols

This is an entry map; protocol rules have one owner in the six contracts.

| Boundary | Contract |
| --- | --- |
| Profiles, connections, status, managed workers, `/v1` | [Models](contracts/models.md) |
| Persona/session resolution, context, messages, attachments, titles | [Chat/context](contracts/chat-context.md) |
| Tool registry, direct invocation, loops and explicit approval | [Harness/tools](contracts/harness-tools.md) |
| Knowledge sources, indexes, bindings and retrieval | [Knowledge](contracts/knowledge.md) |
| Run lifecycle, WS/SSE, event merging and cancellation | [Runs/streaming](contracts/runs-streaming.md) |
| Settings schemas, navigation, keys and Pet packages | [Settings](contracts/settings.md) |

Internal chat and external inference call the same ModelManager directly.
Only registered `/tool_name` input triggers a direct tool; ordinary messages
use ChatRunner and an optional harness. External `/v1` forwards tool data and
never executes it. Pending approval resumes only through the approval API.

Alembic is the only schema authority; head is `0010_runtime_maintenance`.
The disposable application-settings reset and protected file boundaries are
documented in [data layout](DATA_LAYOUT.md). Earlier revisions remain executable
history, not alternative current schemas or compatibility implementations.
