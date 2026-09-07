# Agent Workbench run guide

Agent Workbench provides local chat, optional built-in tools and a single-key
OpenAI-compatible service. Model files are managed manually.

## Requirements and startup

- Python 3.10+ and [uv](https://docs.astral.sh/uv/) are required.
- Node.js 20.19+ or 22.12+ is needed to build the frontend from source.
- A portable package already contains `frontend/dist`; running it needs no Node.js.

On Windows, double-click `start.bat`. On Linux/macOS, run `bash start.sh`.
Both launchers open <http://127.0.0.1:8765>. To select a different port:

```shell
uv run python scripts/run_app.py --port 8766 --open
```

For a source checkout, install dependencies and build the frontend using the
[README](README.md) before starting. The official launcher binds loopback only.

## Choose a model backend

- Configure an OpenAI-compatible connection in **Models → Connections**, then
  create a profile and select it as the default chat model.
- On Windows/Linux x64, install a supported CPU runtime in **Models → Runtimes**.
  Use llama-server for GGUF chat, or the Python worker for embeddings, reranking
  and supported vision tasks. GPU variants are currently unavailable.
- Place weights manually under `data/models`; runtime installation downloads
  the runtime and dependencies only. See [model setup](README.md#configure-models).

## Portable packages and data

Build from a source checkout with `uv run python scripts/build_portable.py --zip`.
The folder and optional ZIP are written under `build/`. They contain application
code, Alembic revisions, built frontend assets and the maintained documentation.
They exclude `.env`, databases, model weights, installed runtimes, attachments,
API keys and dependency/cache directories. Python dependencies are installed by
uv on first launch.

The default database is `data/agent_workbench.db`. Startup applies Alembic
revisions. Test database records may be reset by a revision; model, runtime,
attachment and other data files are outside migration ownership. See
[data layout](docs/DATA_LAYOUT.md) for environment paths and reset behavior.
