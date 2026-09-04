# LLM resolution contract

Main chat calls use an enabled LLM profile selected by the session or global
default. Resolution is intentionally short:

1. `session.llm_profile_id`, when set;
2. `/api/settings/llm-defaults.default_model_profile_id`.

No manifest, extension, route, or text prefix participates in resolution. If
neither selection resolves to an enabled profile, the run fails with
`LLM_MODEL_NOT_SELECTED`.

Provider profiles hold connection details (provider, base URL, API key,
timeout, enabled state). LLM profiles hold model id, generation defaults,
capability flags, and provider reference. Secrets are masked in API responses
and excluded from run/event metadata.

The existing OpenAI-compatible adapter supports non-streaming and streaming
chat responses. Provider responses may include `choices[].message.content` or
plain text; ChatRunner stores the result as a text message part. Vision and
embedding inference skeletons remain available through their explicit APIs but
are not alternate chat routing paths.

Utility LLM uses the separate `utility_model_profile_id` setting and never
changes main chat resolution. See [utility-llm.md](utility-llm.md).
