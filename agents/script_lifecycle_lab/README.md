# Script Lifecycle Lab

Script Lifecycle Lab is a development and test agent for validating Script Agent runtime behavior. It is not a business agent and does not read or write external files.

## Actions

- `steps`: tests realtime run steps without LLM.
- `hidden_json`: tests internal LLM streaming without public output.
- `public_stream`: tests public output streaming from a script agent.

## Expected behavior

- Steps appear while the script is still running.
- `hidden_json` does not show raw JSON to chat.
- `public_stream` streams text to the assistant message.
- Completed runs collapse by default.

## Example calls

```text
@script_lifecycle_lab:steps Build a local-first workbench
@script_lifecycle_lab:hidden_json Build a local-first workbench
@script_lifecycle_lab:public_stream Script agent lifecycle events
```
