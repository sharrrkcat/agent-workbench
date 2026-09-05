# Runtime streaming contract

Streaming has one authoritative visible content path over WebSocket events.

## Events

- `message_updated` acknowledges persisted metadata or a user message.
- `message_started` announces an assistant draft and its ids.
- `message_delta` carries incremental text with `seq=1,2,...` and the same
  message_id/run_id as the started and completed events.
- `message_completed` carries the final persisted `Message` and is authoritative.
- `run_step_created`/`run_step_updated` expose generic step progress.

The frontend tracks the greatest sequence per message, ignores late deltas,
and replaces the draft with `message_completed.message.parts`. A completed
message is never overwritten by an older update. Gapped deltas are ignored
until an authoritative completed message/refresh repairs the text. A refresh
that began before incoming events must not overwrite newer streamed content.
Session switches reject stale responses belonging to the previous session.

`model_status` uses an empty session_id and reaches all connected sessions.
Its payload is `{model_profile_id, status}`. It has no run_id and is not
persisted as a business event. External inference SSE uses the same manager;
see [stateless-inference](stateless-inference.md).

## Persistence

Final messages persist `content_version: 2` and validated `parts`. Deltas are
transport-only unless `persist_streaming_message_deltas` is enabled for local
debugging. Run steps, errors, warnings, final messages, and events are always
persisted. On failure or cancellation, the terminal run status is authoritative
and any partial draft is treated as transient.

## Example

```json
{
  "type": "message_delta",
  "run_id": "run_1",
  "message_id": "msg_1",
  "payload": {"seq": 1, "delta": "hello"}
}
```
