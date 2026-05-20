# Runtime Streaming Contract

Message streaming has one authoritative content path. This contract owns
`message_delta`, `message_completed`, `message_updated`, and compatible
streaming signals.

## Event Roles

- `message_updated` may acknowledge a newly persisted user message before an
  assistant draft exists. This lets clients clear local "sending" state for the
  user bubble as soon as the backend has accepted/saved it.
- `message_started` announces a new assistant draft before public deltas.
  Prompt Agent runs may emit it immediately after run creation and before
  expensive preparation steps, so run steps have a visible assistant row during
  preparation. The later LLM stream must reuse this draft message id.
- `message_delta` carries visible incremental output for a streaming assistant
  message.
- `message_completed` carries the final persisted assistant message and is the
  authoritative final content.
- `message_updated` updates non-content fields during streaming and may update
  rich content for non-streaming messages.
- `message_done` is a compatibility signal only. It is not a streaming source of
  truth.

During streaming, visible content is updated by `message_delta`. Final content
comes from `message_completed`. The frontend must not use `message_updated` or
`message_done` as the source of streamed text.

## Payloads And Persistence

`message_delta` carries:

- `message_id`
- `run_id`
- `seq`
- `delta`
- optional `reasoning_delta`

`message_completed` carries:

- `message_id`
- `run_id`
- `seq`
- final `message`

`seq` is monotonic per message. The frontend tracks the last accepted `seq` for
each message and ignores older events, including late deltas after completion.

`message_delta` is a realtime transport event. By default it is sent over
WebSocket and is not persisted to the SQLite event log. Settings -> Data ->
`Persist streaming message deltas` may persist deltas for debugging. This
setting does not affect run steps, errors, warnings, final messages, or other
diagnostic events.

`message_completed` persists the final assistant message content.

Final persisted assistant and command result messages include:

- `content_version: 2`
- `parts: [...]`

`message_delta` remains text-only for public visible streaming content. During
streaming, the frontend may display an accumulating transient draft in local
state. After `message_completed`, `message_completed.message.parts` is the
authoritative visible content.

## Producer Rules

- Emit `message_started` before public deltas for a new assistant draft.
- If `message_started` was already emitted during Prompt Agent preparation, do
  not emit a second draft for the LLM call. Reuse the same `message_id` for
  `message_delta` and the same `draft_message_id` on `message_completed`.
- Increment `seq` once for each public delta.
- Do not emit empty visible deltas unless carrying `reasoning_delta`.
- Emit `message_completed` once, with a greater `seq`.
- Keep final message content equal to accumulated visible deltas unless an
  explicit final replacement is intended.
- Include `draft_message_id` on completion when the frontend may need to replace
  a draft id.
- On failure or cancellation, keep already-emitted partial visible content only
  when it is useful and safe. Terminal error/cancel metadata must make the final
  state clear.

Internal `ctx.llm.stream` does not emit public `message_delta`. It is for hidden
planning, JSON extraction, or validation. Public output streaming requires
`ctx.output.write_delta` or `ctx.llm.stream_to_output`.

## Frontend Merge Rules

- Use `message_id` plus `draft_message_id` to resolve the active streaming row.
- Track the last accepted `seq` per message.
- Mark a message completed after `message_completed`.
- Treat renderable `message_completed.message.parts` as final authoritative
  content when `content_version=2`.
- Merge run metrics, steps, warnings, attachments, status, and `run_id` without
  resetting streamed content.
- During streaming, `message_updated` may conservatively merge metadata,
  `run_id`, attachments, status, `content_version`, and `parts`, but must not
  replace accumulated transient draft text.
- When `message_updated` carries a persisted user message matching a local
  optimistic user message by visible text and attachment ids, the frontend
  should replace the optimistic row and clear that row's sending state without
  waiting for `message_started`, `message_delta`, or `message_completed`.
- For non-streaming source messages, `message_updated` may persist backend
  generated part changes, such as replacing a `form` part after a silent save or
  setting form-level `ui.collapsed=true`.
- When `message_updated` changes a form, backend producers must update the
  authoritative `form` part.
- The frontend must not infer streaming state from content shape.

## Command Buttons

`command_buttons` Message Parts are the command button content model.
Clicking a command button sends its configured text through the normal
user-message flow. It creates an ordinary user message and does not mutate the
source assistant message, send hidden action payloads, or call a backend Agent
action API directly.

## Tiny Examples

```json
{
  "type": "message_delta",
  "run_id": "run_1",
  "message_id": "msg_1",
  "payload": {"seq": 1, "delta": "hel", "reasoning_delta": null}
}
```

```json
{
  "type": "message_completed",
  "run_id": "run_1",
  "message_id": "msg_1",
  "payload": {
    "seq": 2,
    "message": {
      "message_id": "msg_1",
      "content_version": 2,
      "parts": [{"type": "text", "format": "markdown", "text": "hello"}]
    }
  }
}
```
