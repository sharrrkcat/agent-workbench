# Agent Workbench run guide

Agent Workbench provides local chat, optional built-in tools and a single-key
OpenAI-compatible service. Model files are managed manually.

## Requirements and startup

Install the Python and uv requirements listed in the [README](README.md#start).
A portable package already contains `frontend/dist`; running it needs no Node.js.

On Windows, double-click `start.bat`. On Linux/macOS, run `bash start.sh`.
Both launchers open <http://127.0.0.1:8765>. To select a different port:

```shell
uv run python scripts/run_app.py --port 8766 --open
```

For a source checkout, install dependencies and build the frontend using the
[README](README.md) before starting. The official launcher binds loopback only.

## Model setup

Follow [model setup](README.md#configure-models) for external connections,
managed runtimes and manual model placement. The
[runtime catalog](docs/contracts/models.md#managed-catalog-and-installation)
owns the supported platform/variant matrix, including Windows CUDA.

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
