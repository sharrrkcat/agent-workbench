# Agent Workbench Run Guide

## Windows

Double-click `start.bat`, or run:

```bat
start.bat
```

## Linux/macOS

```bash
chmod +x start.sh
./start.sh
```

## Requirements

- Python and uv are required.
- Node.js is required only when `frontend/dist` needs to be built.
- If a portable package already contains `frontend/dist`, normal startup does not need `npm run dev`.
- LM Studio, Ollama, or llama.cpp are not bundled. Start your chosen local LLM service separately.

Default address:

```text
http://127.0.0.1:8765
```

If the port is in use:

```bash
uv run python scripts/run_app.py --port 8766 --open
```

The portable package does not include `.env`, databases, attachments, API keys, `node_modules`, or cache folders.
Current data is still stored in the project `data` directory. A future release may move data to an OS user data directory.
