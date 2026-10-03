# Future QQ integration

This document records the QQ integration research and project decisions as of
2026-10-03. The integration is not implemented and has no active implementation
plan. Proposed behavior below is a design direction, not a supported API or a
commitment to implement it before the memory system.

## Intended product and scope

- One QQ Project represents one bot account; one persistent Session represents
  one group or private conversation. A Run represents one reply generation batch.
- Cogita supplies inference through `core/models` and an external OpenAI-compatible
  ProviderProfile. Linux Local Runtime support is outside this integration's scope.
- QQ messages provide conversation history; a selected Agent Persona supplies
  the bot's personality. Knowledge is excluded from the requested workflow.
- Worldbook use is desired but requires an injection design. Integration may wait
  for Cogita's memory system; memory ownership and retrieval remain undecided.
- The deployment is noncommercial, without Docker. The preference is to run QQ,
  its protocol adapter and Cogita together on the Linux VPS.
- The stated approximately 500 MiB budget means available host RAM before these
  services start, not total physical RAM.

## Protocol and deployment direction

Use an independent QQ protocol adapter exposing OneBot v11, with NapCat Shell as
the first candidate. Both NapCat and SnowLuma depend on an actual NTQQ client;
removing Docker does not remove QQ's process and memory costs. NapCat's Linux
Shell deployment can use Xvfb without a desktop session. SnowLuma remains an
alternative, with more involved native Linux setup.

[qq-agent-plus](https://github.com/sakurawwwxh/qq-agent-plus/tree/53ad4ac7fb92449779804d4e8e7b878069575595)
was reviewed at v0.7.7 as a reference for message ingestion, batching, history and
delivery. Its `chatKey` corresponds to the intended persistent Cogita Session;
its processing `sessionId` is closer to a Cogita Run. Its model uses a
`send_message` tool for public replies, whereas the proposed Cogita integration
would forward a completed answer. Its prompts and execution loop cannot simply
be copied into Cogita.

The intended flow is QQ → protocol adapter → Cogita ingestion → Session/Run →
`core/models` → delivery record → protocol adapter → QQ. A second Node.js agent
service is unnecessary for this direction. Merely pointing qq-agent-plus at
Cogita `/v1` would reuse inference without creating internal Sessions/Runs or
applying their Persona context.

The current [production launcher](../scripts/run_app.py) already supports
`--no-open`. Production frontend files are static assets served by the backend;
the browser runs on the accessing computer. A separate CLI product is not needed
just to remove server-side browser or Vite overhead. Build frontend assets away
from the small VPS. Keep service listeners on loopback and use SSH access for
management under the current [Models contract](contracts/models.md).

## Integration requirements to resolve

The initial candidate scope is one account, text from groups and friends, group
mention/reply triggers, direct replies in private chats, short message batching,
internal history display and final-answer delivery. The exact settings and wire
schemas are not fixed.

1. Separate recording from generation. Save allowed incoming messages even when
   no reply is triggered or another Run is active. Deduplicate external message
   IDs, serialize generation per conversation and freeze each batch's history
   cutoff. Reconcile the bot's own echoes without triggering another reply.
2. Preserve participant identities, time, mentions and quoted-message references
   in stored messages, model context and UI. Group participants are not separate
   Agent Personas. Define bot-specific resource inheritance so personal Cogita
   background and Knowledge are not implicitly included.
3. Track generation separately from delivery. Retry a known failed delivery of
   an existing answer without regenerating it; do not automatically resend when
   the send result is unknown. Context must distinguish generated answers from
   messages actually delivered to QQ. Keep reasoning and tool processing internal.
4. Define external-history editing, regeneration and explicit manual QQ sends.
   Internal history pruning does not retract QQ messages. External `/...` input
   should remain chat text rather than enter the internal direct-tool executor.
5. Start with realtime history accumulation. Group/friend batch-history APIs are
   adapter extensions; reconnect backfill must be tested against the chosen
   adapter and cannot imply full historical export.
6. Define Worldbook injection and any future memory isolation per bot and
   conversation, with bounded retrieval. Current Worldbook bindings do not
   provide ordinary-chat injection.

## Current code gaps

[Chat/context](contracts/chat-context.md), [Runs/streaming](contracts/runs-streaming.md)
and [Harness/tools](contracts/harness-tools.md) own existing behavior. QQ ingestion,
conversation bindings and outgoing delivery are absent. Implementation would
need to update those owners as behavior lands.

- [Message routes](../ai_workbench/api/routes/messages.py) couple accepted input
  to execution; they are not a passive external-message ingestion API.
- [ContextBuilder](../ai_workbench/core/context.py) projects ordinary chat rather
  than a QQ participant transcript. [MessageBubble](../frontend/src/components/MessageBubble.tsx)
  displays the singleton user identity for ordinary user messages.
- [Chat configuration](../ai_workbench/core/chat_service.py) inherits personal
  and Agent Knowledge for current chat. The requested bot resource boundary
  therefore needs explicit treatment.
- [SqlMessageStore](../ai_workbench/db/stores.py) loads the entire Session's
  messages before ContextBuilder applies limits. Long-lived group history needs
  bounded database queries, not only a bounded final model prompt.
- [EventBus](../ai_workbench/core/events.py) retains emitted events in `_events`
  without a normal capacity bound, and subscriber queues are unbounded. Durable
  streaming-delta persistence settings do not bound this in-memory retention.

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

The user limited this round to login and idle memory. No model call, first-use
tokenizer cost, OneBot message round trip, internal Session bridge, long history,
concurrent generation, media workload, reconnect, cached-login restart or
24–72 hour soak has been verified. QQ shutdown behavior also needs follow-up.
Address bounded history and event retention before long-lived bot acceptance.
An implementation task should settle Worldbook/memory timing and message/delivery
semantics before defining schemas; as features land, move their current behavior
to the owning contracts and remove superseded proposals from this note.
