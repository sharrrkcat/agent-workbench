# Cogita run guide

Cogita provides local chat, optional built-in tools and a single-key
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
[README](README.md) before starting. The launcher defaults to `0.0.0.0:8765`,
serving the built UI, `/api` and WebSockets on all IPv4 interfaces. Other LAN
devices can open `http://<computer-LAN-IP>:8765`; `ipconfig` shows that address
on Windows. Allow the selected TCP port through the host firewall if needed.
The local browser still opens `127.0.0.1`, not the wildcard bind address.

Use `--host 127.0.0.1` for local-only web access. The web interface shares the
host's conversations and settings without login; use it on a trusted LAN.
The separate `/v1` model API still rejects non-loopback clients, even with a valid key.
See [web access](docs/contracts/runs-streaming.md#web-access) for browser limitations.

## Model setup

Follow [model setup](README.md#configure-models) for providers and local runtime settings,
the shared local installation and manual model placement. The
[runtime catalog](docs/contracts/models.md#managed-catalog-and-installation)
owns Windows x64 engines and CPU/CUDA/D3D12 support. Local installation requires neither
model files nor a GPU; model execution checks its selected device and resources.

## QQBot deployment

[QQBot](docs/contracts/qqbot.md) connects directly to an external NapCat-compatible
OneBot v11 server; no separate Node.js agent service is needed. NapCat Shell and
SnowLuma still require an actual NTQQ client and its memory, even without Docker.
Linux NapCat Shell can use Xvfb without a desktop. Linux Local Runtime is unsupported;
QQBot inference uses configured external OpenAI-compatible providers.

For a small VPS, build frontend assets elsewhere. Cogita serves the built UI;
the browser runs on the accessing computer. Start without opening a local browser:

```shell
uv run python scripts/run_app.py --host 127.0.0.1 --no-open
```

Use SSH forwarding for management access. Host setup, credentials, QQ installation
and login records belong to external operational documentation.
A short Ubuntu 24.04 amd64 trial reached QQ online and Cogita migrations/health,
with no inference or media workload. This establishes basic same-host feasibility,
not a minimum-memory requirement, swap-free operation or long-running stability.
The [QQBot acceptance limits](docs/contracts/qqbot.md#limits-and-acceptance) retain
outstanding live delivery, workload, restart and shutdown checks; detailed experiment
records remain in Git and the separate operational workspace.

## Portable packages and data

Build from a source checkout with `uv run python scripts/build_portable.py --zip`.
The folder `build/cogita-portable/` and optional `build/cogita-portable.zip` contain
application code, Alembic revisions, built frontend assets, the bundled DLSS NR component archive and maintained documentation.
They exclude `.env`, databases, model weights, installed runtimes, attachments,
API keys and dependency/cache directories. Python dependencies are installed by
uv on first launch.

The default database is `data/cogita.db`. Startup applies Alembic
revisions. Test database records may be reset by a revision; model, runtime,
attachment and other data files are outside migration ownership. See
[data layout](docs/DATA_LAYOUT.md) for environment paths and reset behavior.
