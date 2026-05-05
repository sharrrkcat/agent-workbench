# Release Checklist

Technical Alpha verification:

- [ ] `uv run pytest`
- [ ] `cd frontend && npm run build`
- [ ] `uv run python scripts/check.py`
- [ ] Start backend: `uv run uvicorn ai_workbench.api.main:app --reload`
- [ ] Start frontend: `cd frontend && npm run dev`
- [ ] Create a session
- [ ] Send a plain message: `hello`
- [ ] Invoke translate: `@translate 你好`
- [ ] Invoke Base64 command: `/base64 hello`
- [ ] Disable `translate` in Settings and confirm `@translate 你好` returns a structured disabled error
- [ ] Save `llm` capability config in Settings
- [ ] Run `llm` Test connection
- [ ] Select a returned LLM model and save it
- [ ] Confirm resolved LLM status does not show API key plaintext
- [ ] Restart backend and confirm session history is still present
