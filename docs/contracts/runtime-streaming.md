# Runtime streaming contract

Streaming has one authoritative visible content path over WebSocket events.

## Events

- `message_updated` acknowledges persisted metadata or a user message.
- `message_started` announces an assistant draft and its ids.
- `message_delta` carries incremental text with a monotonic `seq`.
- `message_completed` carries the final persisted `Message` and is authoritative.
- `run_step_created`/`run_step_updated` expose generic step progress.

The frontend tracks the greatest sequence per message, ignores late deltas,
and replaces the draft with `message_completed.message.parts`. A completed
message is never overwritten by an older update.

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
