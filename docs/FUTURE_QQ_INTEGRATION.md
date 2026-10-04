# QQ integration boundaries

QQBot Projects and bound group/friend Sessions are implemented through an external
NapCat-compatible OneBot v11 WebSocket server. [Chat/context](contracts/chat-context.md#qqbot-conversations)
owns configuration, ingestion and context; [Harness/tools](contracts/harness-tools.md#qq-delivery-and-queues)
owns sending, durable queues, failure handling and recovery. [Runs/streaming](contracts/runs-streaming.md)
owns model execution and inspection. This note retains deployment evidence and unverified boundaries.

## Supported boundary and deployment

Cogita manages connections, bound-message recording, keyword/follow-up/private batches with explicit follow-up skip,
external OpenAI-compatible inference through core/models, and text delivery through
qq_send_message. A separate Node.js agent service is unnecessary. Agent Persona identity
and prompts are optional; Knowledge, Worldbook and Cogita Persona inheritance are excluded.

QQ/NapCat installation, login management, reconnect history backfill, media understanding,
manual sends and memory integration remain unimplemented. Linux Local Runtime support is
outside this integration. Future Worldbook/memory work requires explicit bot/conversation
isolation and a separate injection design; it is not a prerequisite for current QQBot execution.

NapCat Shell and SnowLuma both depend on an actual NTQQ client. Avoiding Docker does not
remove that process or its memory costs. Linux NapCat Shell can use Xvfb without a desktop.
The production launcher supports --no-open; the backend serves static frontend assets and
the browser runs on the accessing computer. Build frontend assets away from a small VPS.
Keep management listeners on loopback with SSH access under the [Models contract](contracts/models.md).

The earlier source review identified unbounded history/event retention at its tested revision.
Current SQLite context/history reads are paginated and EventBus subscriber queues are bounded;
see [Chat/context](contracts/chat-context.md#configuration-snapshots-and-context) and
[Runs/streaming](contracts/runs-streaming.md#websocket-events). Both context limits explicitly
set to null still permit growth. These code changes do not establish long-running QQ memory acceptance.

## Linux feasibility evidence

On 2026-10-03, Cogita commit `356a112f2843faa3ddf9a40ced1d4736b389c874`,
NapCat Shell v4.18.28 and QQ `3.2.32-52194` were tested on Ubuntu 24.04 amd64.
The host had 954 MiB physical RAM, approximately 546 MiB available before this
round, and 2 GiB swap with approximately 57 MiB already used. The shared experiment
slice was capped at 400 MiB RAM and 128 MiB swap.

QQ login reached the ready/online state. Cogita started with its locked production
dependencies, an isolated fresh database and no frontend assets, model profiles
or inference. Database migration and `/api/health` succeeded. The saved trace
covers approximately five minutes of combined running:

| Measurement | Observed result |
| --- | --- |
| Shared slice RAM in the final two minutes | 362.7–377.2 MiB |
| Shared slice swap peak during combined running | 80.8 MiB |
| Minimum host available RAM during combined running | 342.8 MiB |
| Final Cogita PSS / proportional swap | 111.4 / 1.4 MiB |
| Final QQ and NapCat PSS / proportional swap | 174.8 / 65.6 MiB |
| Experiment OOM / OOM kill / application restarts before stopping | 0 / 0 / 0 |

PSS apportions shared resident pages. Cgroup accounting also includes file cache
and kernel allocations. The shared limit caused reclaim and swapping while host
RAM was still available, so these observations do not establish a minimum RAM
requirement or swap-free operation. They support proceeding with same-host
testing, not a long-running memory guarantee.

During explicit shutdown, QQ reported Electron `Failed to shutdown` and exited
with SIGTRAP; this was a stop-time failure, not an OOM or a spontaneous idle crash.
Cogita stopped successfully. The experiment services were stopped after acceptance.

The separate Oracle workspace owns the full evidence and operational records in
`work/qq-memory-test-20261003/README.md` and its `results` directory. Host addresses,
credentials, installation scripts, package inventories and login data belong
there rather than in this repository. The measurements here retain only the
project-relevant feasibility evidence requested for future work.

## Outstanding acceptance

Local fake-OneBot/fake-model verification covers bound ingestion, batching, Harness delivery,
transport failures, pause/stop/resume and restart; browser fixtures cover English/Chinese desktop/touch workflows.
A real NapCat round trip with explicitly designated test targets remains unverified. Login
and idle-memory evidence below cannot establish message delivery, external model behavior or a RAM guarantee.

The Linux experiment did not exercise inference, first-use tokenizer cost, long histories,
concurrent generation, media workloads, reconnect, cached-login restart or a 24–72 hour soak.
Those scenarios and QQ shutdown behavior require separate operational acceptance. The approximately
500 MiB deployment budget refers to available host RAM before services start, not total physical RAM.
