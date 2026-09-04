# Utility LLM contract

Utility LLM is a core service for short internal tasks. It is not a public
target, route, plugin, command, or independently configurable backend.

## Configuration

`AppSettings.utility_model_profile_id` is the only selector. The id resolves
an enabled LLM profile (alias lookup is allowed by the profile store). If no
profile, provider, model, or runtime is available, calls raise
`UtilityLlmError(code="UTILITY_MODEL_UNAVAILABLE")`.

The remaining title settings are:

- `auto_generate_session_titles` (default `true`)
- `session_title_prompt`
- `session_title_max_input_chars` (default `1200`)

There are no utility-specific model paths, device settings, scans, or public
diagnostic endpoints.

## Interface

```python
class UtilityLlmService(Protocol):
    async def generate_text(self, prompt: str, *, max_tokens: int | None = None,
                            temperature: float | None = None) -> str: ...
    async def generate_json(self, prompt: str, schema: type[T], *,
                            max_tokens: int | None = None,
                            temperature: float | None = None) -> T: ...
    async def generate_title(self, user_text: str) -> str | None: ...
    def unload(self) -> dict: ...
```

`generate_text` sends a non-streaming user prompt through the normal LLM
runtime. `generate_json` parses plain text (including a fenced or embedded JSON
object) and validates it with the supplied Pydantic schema. Invalid output
raises `UTILITY_OUTPUT_INVALID`; it never executes instructions from the text.
`generate_title` truncates to the configured input limit and returns `None` on
any unavailable, invalid, or empty result so the chat run can continue.
`unload` is best effort and returns a small status dictionary.

## Isolation and metadata

Utility calls do not create messages, runs, events, or recursive title calls.
They receive only their explicit prompt and do not inject chat history,
attachments, Memory, Worldbook, or Knowledge. Logs and metadata may contain
public profile/model identifiers and compact error codes, never secrets or raw
prompts/model output.

## Title lifecycle

After the first user message in a default-titled session, ChatRunner may make
one best-effort title call. Failure leaves the existing title unchanged and
does not change the response model or run status.
