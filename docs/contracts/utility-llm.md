# Utility LLM contract

UtilityLLMService is an internal client of ModelManager for short text/JSON
tasks and titles. It has no independent backend, unload path or public route.

## Configuration and calls

`/api/models/settings.utility_model_profile_id` is the sole selector and
must identify an enabled llm profile by UUID. Missing selection or model
failure raises `UTILITY_MODEL_UNAVAILABLE`. It never substitutes the default
chat model or accepts profile aliases.

`generate_text(prompt, max_tokens=None, temperature=None)` uses non-streaming
manager chat with only the supplied prompt. `generate_json(prompt, schema,
**parameters)` parses the entire returned text as JSON and validates the
Pydantic schema. Fenced/embedded JSON, tool calls and invalid output raise
`UTILITY_OUTPUT_INVALID`; output never becomes executable instructions.

Utility tasks create no messages or runs. Their occupancy/status uses the
same provider queue and release policy as any other manager caller.

## Title lifecycle

General settings retain auto_generate_session_titles (true),
session_title_prompt and session_title_max_input_chars (1200). ChatRunner
finishes the response, releases its model lease and publishes message/run
completion before attempting a title. The title request explicitly uses
max_tokens=64 and temperature=0.

An empty/default title may be generated from the bounded current user text.
No configured auxiliary model, failed/empty output or a concurrently edited
manual title leaves the current title unchanged. Title failure does not change
the successful chat result. No history, attachments, Memory, Worldbook or
Knowledge is injected into the auxiliary prompt.
