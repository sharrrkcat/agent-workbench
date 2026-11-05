# Letta persistent memory research

Research date: 2026-11-05. This follows the [AIRI investigation](AIRI_MEMORY.md)
and examines the requested [Memory & dreaming documentation][docs-memory].
It is a research reference, not an implementation plan, an accepted API design,
or a contract for implemented Cogita behavior.

## Scope and evidence

| Source | Inspected version | Evidence boundary |
| --- | --- | --- |
| Letta documentation | Live pages retrieved on 2026-11-05 | Current published behavior; pages can change and sometimes disagree |
| `letta-ai/letta-code` | [`ee6e2c588082cbd98d8db1e20b18096585afa5bf`][code] | Targeted static inspection of memory compilation, constraints, reflection, synchronization and tests |
| `letta-ai/context-constitution` | [`964f30137ace9eade1aef112992ed6539b61bbb0`][constitution-repo] | Design principles and prompting intent, not an operational guarantee |
| Cogita | `532d1d4e5d1cfa44b4553886d8cf321d6caf07c9` | Local contracts, history checkpoints, retrieval schemas and tests |

The supplied URL was read with its tracking parameter removed from citations.
Related official pages were read through their published `/index.md` versions.
Source links are pinned to the revisions above. Upstream applications, model
inference, cloud services and upstream tests were not run. Tests mentioned below
establish intended coverage from inspected assertions, not measured acceptance.
Letta Cloud's server implementation was not audited.

The main finding is a distinction between **durable storage**, **discoverable
knowledge**, and **knowledge actually included in a model request**. Letta uses
versioned Markdown, a small continuously visible layer, indexes into deeper
material, and optional background reflection. Git persistence alone does not
establish accurate learning, reliable recall, or safe sharing.

## Current architecture and terminology

[Stateful agents][docs-stateful] and [SDK sessions][docs-sessions] distinguish:

| Entity or layer | Lifetime and purpose | Important boundary |
| --- | --- | --- |
| Agent | Persistent identity, memory, model/tool configuration and conversations | Letta's agent is not equivalent to Cogita's configuration-only Persona |
| Conversation | Separate message thread belonging to an agent | A new conversation uses the same agent memory; it is not a memory-isolation boundary |
| SDK session | Active connection used to send messages and stream results | Closing it does not delete agent memory or conversation history |
| Active conversation context | Recent messages and compaction summary | A summary supports continuity but can lose wording and provenance |
| Recall/message history | Persisted original messages available for search | Separate from curated MemFS knowledge |
| Core memory | Small, continuously included identity, preferences and guidance | Every included character consumes request context |
| Deferred memory | Subject-oriented knowledge reached through indexes and reads | Stored content is useful only if the agent discovers and reads it |
| Agent-owned skills | Reusable procedures under `skills/` | Versioned with memory, but discovered separately from deferred knowledge |
| Shared repository | Explicitly attached organization-owned Cloud repository | Separate ownership and synchronization from an agent's private MemFS |

The [current MemFS page][docs-memfs] explicitly says that MemFS has **no semantic
or vector index by default**. The current design should not be described simply
as an automatically queried vector database or as the older MemGPT three-tier
memory API. The [shared-memory page][docs-shared] still acknowledges legacy
shared blocks, but recommends shared repositories for that use case.

### Documentation and version differences

Several published descriptions cannot be combined into one universal contract:

| Topic | Published descriptions | Evidence and interpretation |
| --- | --- | --- |
| Core-memory location | MemFS describes root Markdown for current agents and `system/` for older agents; SDK memory still says creation entries land under `system/` | Pinned local creation code and its test create root `MEMORY.md`, `persona.md` and `human.md`; the compiler supports both layouts |
| Deferred discovery | Older descriptions show a full external file tree; current v2 guidance describes a chain of `MEMORY.md` indexes | The pinned local v2 compiler includes root contents and top-level directory paths, not every deferred body |
| Memory doctor | MemFS groups doctor with worktree-based memory subagents | Pinned `/doctor` dispatch starts a primary-agent investigation in the current conversation; its audit instructions explicitly say there is no separate worktree integration |
| Explicit teaching | Configuration docs advertise `/remember` | This report treats it as a documented interface, without claiming live CLI acceptance |

Relevant evidence is [format selection][src-format], [initial local memory][src-initial],
[local prompt compilation][src-compiler], [fresh-layout tests][test-layout],
[doctor dispatch][src-doctor] and [doctor audit guidance][src-doctor-audit].
The [SDK memory page][docs-sdk-memory] and older [Affordances][affordances]
remain useful conceptual references, but their `system/` examples are not a
universal description of fresh local agents at the inspected revision.

## Memory lifecycle

| Stage | Letta mechanism | What it does not establish |
| --- | --- | --- |
| Observe | Conversations retain user input, model output and tool results | Every observed statement is not automatically a verified fact |
| Select | The active agent or reflection model decides which lessons are durable | No deterministic extraction quality follows from storing transcripts |
| Organize | Core guidance, indexed deferred knowledge or reusable skills | Directory placement alone does not prove future discoverability |
| Propose | File edits, or reflection commits in an isolated worktree | An uncommitted edit is not a completed memory update |
| Validate and save | Format/size checks and Git commits; reflection merges into parent memory | Structural validity and a clean merge do not resolve semantic contradictions |
| Synchronize | Cloud commits push; other checkouts pull; local agents retain local repositories | A local commit is not proof that another computer has received it |
| Include or retrieve | Compile core memory and indexes; read deeper files on demand | Persistent data need not be in the current request |
| Revise | Edit existing knowledge, reorganize indexes and retain Git history | Revision is not automatic truth maintenance after source changes |
| Remove | Delete current content or detach shared resources | Previous commits, transcripts, copies and already-derived lessons may remain |

### Capture and learning policy

The [configuration page][docs-memory] offers `/init` for initialization,
`/remember` for explicit teaching, `/memory` for inspection, `/doctor` for
investigation, and `/sleeptime` or app Dream settings for background reflection.
These are Letta interfaces, not proposed Cogita commands.

The [reflection v2 prompt][src-reflection-prompt] prioritizes mistakes and
corrections, durable preferences, new knowledge, contradictions and reusable
procedures. It asks the model to read existing memory before editing, avoid
duplicates and ephemeral task state, convert relative dates to absolute dates,
and make no change when nothing merits retention. Multiple transcript slices
can be reviewed together, including deliberate replay of previously reviewed
material for cross-conversation synthesis.

This is primarily model-guided curation, not a mandatory typed fact-extraction
pipeline. The inspected path does not establish a general fact table with
per-fact confidence, temporal validity, evidence relationships and automatic
invalidation. Prompts ask the model to resolve contradictions using newer
evidence; that is weaker than enforcing a domain rule about which source is
authoritative. A newer assertion can still be a quote, speculation or mistake.

[Core-memory guidance][src-core-guidance] favors refining an existing principle
over appending another narrow rule. [Deferred-memory guidance][src-deferred-guidance]
favors current understanding of a subject over chronological logs or copied
material that can already be recovered from history. Procedures belong in
skills rather than accumulating among personal facts.

These principles improve the shape of memory, but need quality evaluation.
Over-generalizing a single correction can be as damaging as retaining every
event. Separate observed facts, explicit user preferences, model conclusions
and instructions when adapting this idea to Cogita.

### Storage, indexing and context placement

The current root layout is conceptually:

```text
memory/
  MEMORY.md                 Always included: entry points and retrieval cues
  persona.md                Always included: identity/guidance
  human.md                  Always included: important user context
  projects/
    MEMORY.md               Read when this subject is needed
    example.md              Read through an index or file search
  skills/
    procedure/SKILL.md      Separately discovered procedure
```

Root and child `MEMORY.md` indexes have no frontmatter. Other v2 memory
Markdown uses `name` and `description`. Every directory along a deferred
memory path needs its own index to participate in the v2 projection; skills
are excluded from that projection and use their own discovery rules.

The [local compiler][src-compiler] reads tracked Markdown from Git `HEAD`,
not arbitrary uncommitted working files. It renders root memory blocks in
filename order, then the root index and top-level indexed directory paths.
Deferred bodies do not all enter the prompt. Changes require an updated
compiled prompt; no claim is made that an already-dispatched request changes
when a file is edited. Ordinary file tools may still see working-copy edits,
so file visibility and committed prompt state are distinct.

The crucial retrieval artifact is a **usable path of discovery**: the root
index says when to open a subject, its child index identifies the relevant
file, and that file supplies the detail. An index that omits a topic can make
correctly stored knowledge effectively unreachable through normal browsing.
The guidance therefore asks for parent-index updates when content moves or
expands, and for tracing a future request all the way to its target.

[Constraints and defaults][src-constraints] cap core memory at 65,536 characters,
individual memory files at 20,000 characters, and directory depth at two,
unless configured otherwise. Ordered file-glob overrides and protected paths
are supported. The [pre-commit validator][src-validator] checks staged content,
including indexes and frontmatter; routine changes distinguish changed-file
errors from pre-existing warnings. These are character and structural limits,
not proof that an arbitrary model's full request fits its token window.

Cogita should retain its actual request token counting and output reserve.
Neither Letta's size defaults nor a suggested fraction of context should
replace the existing budget enforcement.

### Retrieval and conversation continuity

Default MemFS recall uses ordinary file search and reads. The [MemFS page][docs-memfs]
describes an optional MemFS Search mod: keyword search needs no additional
dependencies, while semantic/hybrid modes require QMD and indexing. This is
an optional extension, not a prerequisite for persistent memory.

Conversation search is a different path. The same page describes full-text,
vector and hybrid message search on Cloud, versus full-text transcript search
on local backends. [Conversation compaction][docs-conversations] summarizes
older messages while preserving recent context; original history remains
available for subsequent search. Compaction summaries are not a replacement
for curated knowledge or exact historical evidence.

The useful separation is:

- Recall answers what was said or done, using original history.
- Deferred knowledge captures a maintained understanding that helps later work.
- Core memory keeps essential guidance and pointers continuously visible.
- Skills encode repeatable procedures with a discovery trigger.

Moving a critical constraint out of core memory changes when it reaches the
model. An accurate file and an existing link do not guarantee that the model
will choose to read it. Test retrieval on actual future queries, including
synonyms and indirect references, before treating a smaller prompt as better.

### Background dreaming and consolidation

The [SDK][docs-sdk-memory] exposes `off`, `step-count` and `compaction-event`
triggers, with `reminder` or `auto-launch` behavior chosen at agent creation.
Sessions can override the trigger and step interval, not that behavior.
The inspected [CLI settings resolver][src-reflection-settings] defaults to
compaction-triggered reflection, an interval value of 25 for step-count use,
and automatic merging. These are scoped source observations, not a guarantee
that every existing agent or client has those effective settings. Completed
agent steps must not be casually equated with user messages or idle time.

The [reflection coordinator][src-reflection-launcher], [worktree integration][src-worktree]
and [transcript accounting][src-reflection-transcript] implement more than
an unconstrained background prompt:

1. Select bounded transcript slices and remember their coverage boundary.
2. Give the reflection worker an isolated memory worktree and relevant context.
3. Have it inspect existing knowledge, edit selected files and commit useful changes.
4. Integrate successful committed changes into the parent memory repository.
5. Recompile after a merge and advance reviewed coverage only for a successful
   integration or a successful no-change result.

Failed workers, uncommitted output, a dirty parent checkout and merge conflicts
are not counted as consumed transcripts by the inspected finalizer. It cleans
the proposal worktree/branch so the transcript can be retried. An automatic
merge conflict is aborted rather than treated as a successful consolidation.
This is useful failure accounting; it is not an exactly-once guarantee.

The option **Agent reviews before applying** launches a second background
conversation that reviews and can revise the proposal before integration.
Both the [documentation][docs-memory] and [integration prompt][src-integration]
make clear that this is model review, not a human approval gate. It adds model
work and tokens and still requires evaluation of the resulting facts.

[Checkout-operation locking][src-operation] serializes harness-owned writers
such as reflection integration, workers and synchronization. The primary
agent's ordinary file edits do not all pass through that lock. Thus worktrees
and Git reduce interference but do not provide a universal transactional
boundary for every actor.

[Post-turn synchronization][src-git] distinguishes pushed, failed and other
states. The explicit integration path can report a successful local merge
while logging a later push problem, and [Cloud coverage synchronization][src-completion]
can fail without reversing local reflection success. Track local commit,
integration, remote publication and reviewed-source coverage separately;
do not infer one global atomic transaction from a successful reflection result.

### Updates, provenance and forgetting

Letta's curation guidance asks for one home per subject, revision in place,
replacement of stale conclusions and removal of redundant rules. Git preserves
prior versions. [Core][src-core-guidance] and [deferred][src-deferred-guidance]
guidance place detailed provenance in commit messages, including conversation
and message IDs, who provided the evidence, event dates and why the learning
generalizes. This keeps the prompt concise while retaining a review trail.

Those source references are an authoring convention, not necessarily enforced
foreign keys or per-fact provenance. A successful Git merge can retain two
contradictory facts in different files. Deleting a supporting message does not
by itself establish invalidation of all derived memory. The inspected scope
does not establish automatic confidence decay, TTL, FSRS scheduling, or
fact-level supersession semantics.

Distinguish these removal effects:

| Operation | Effect that can be inferred | What still needs separate treatment |
| --- | --- | --- |
| Edit/delete current memory content | Changes the latest curated state after saving and prompt refresh | Old Git commits, transcripts, backups and other checkouts |
| Detach a shared repository | Removes the persistent attachment; its provided skills stop loading | Knowledge already copied, summarized or used in a conversation |
| Delete a shared repository through the SDK | It disappears from SDK list/retrieval; the SDK has no restore method | Complete physical erasure and all derived/cached copies are not documented by that statement |
| Disable dreaming | Stops that background trigger | Existing memory and ordinary agent-driven writes are separate concerns |
| Run a `stateless` SDK session | Documented to avoid loading/changing agent memory and alter reflection/skill behavior | The agent and conversation remain persistent; this is not a promise that nothing is stored |

Deleting a current file is therefore not a complete forgetting policy.
Cogita needs explicit behavior for source deletion, derived facts, revisions,
search indexes and in-flight proposals before claiming that a memory is forgotten.

## Sharing and isolation

An agent's memory is shared across its conversations by design. Separate
conversations isolate message threads, not learned knowledge. Separate agents
are the documented way to obtain independent identities and memory. This is
a poor direct mapping to Cogita, where the same Agent Persona may serve
unrelated Workspace Projects or QQ conversations.

[Shared repositories][docs-shared] are organization-owned and explicitly
attached to Cloud agents. They are cloned beside private MemFS, and the prompt
lists their path and top-level files for on-demand reading. Agents commit and
push; other checkouts pull, with later synchronization using fast-forward
updates. This is versioned sharing, not immediate shared in-memory state.
The hosted shared-repository API is a Cloud feature. Self-managed Git remotes
are a different deployment arrangement, not equivalent hosted API support.

The [repository SDK][docs-repositories] distinguishes temporary session
`resources` links from persistent agent attachments. Session cleanup removes
the links it created; persistent attachments require explicit detachment.
File mutations return commit identities, and updates support a content-hash
precondition to reject stale writes. This is a useful concurrency primitive,
but it does not resolve contradictory edits in separate files or authorize
all facts for every participant.

The configuration page also documents finite per-repository Cloud storage
allowances. These constrain stored snapshots, independently of model context
capacity. Large datasets and artifacts belong outside concise memory with
useful references back to their owning storage.

## Comparison with AIRI and Cogita

| Concern | AIRI main-chat memory | Current Letta direction | Cogita implication |
| --- | --- | --- | --- |
| Unit of knowledge | Short description plus bounded fact body | Curated Markdown subjects, core guidance and skills | Start with explicit facts; permit richer organized notes only when needed |
| Discovery | Persona/general index, then read-by-ID | Small core plus hierarchical indexes, file search and reads | Budget both indexes and bodies; validate discoverability |
| Default vector dependency | None in the main-chat fact path | None for MemFS | A new vector database is not justified by these examples |
| Write policy | Model read/write/forget tools and user management | Active curation plus optional background reflection | Keep user controls and explicit write/commit semantics |
| Provenance and changes | Limited atomic-entry metadata | Git history and prompted source references in commits | Prefer structured source IDs and revisions for application-managed facts |
| Sharing | Persona/general ownership | Agent-wide memory and explicit shared repositories | Define Project/conversation/subject scope independently of Persona |
| Background work | Separate experimental consolidation paths | Reflection worktrees, integration and coverage accounting | Add asynchronous work only after foreground lifecycle correctness |
| Semantic lifecycle | Lightweight main path; richer related plast-mem experiment | Primarily model-authored revisions in this inspected path | Do not confuse Git history with temporal fact validity |

The [AIRI report](AIRI_MEMORY.md) separately examines plast-mem's typed
semantic actions, source episodes and FSRS-influenced episodic retrieval.
Those mechanisms should not be attributed to Letta or conflated with AIRI's
active main-chat store.

Cogita's current owners are [Chat/context](../contracts/chat-context.md),
[Harness/tools](../contracts/harness-tools.md#on-demand-history),
[Knowledge](../contracts/knowledge.md) and [QQBot](../contracts/qqbot.md).
Existing [history retrieval](../../ai_workbench/core/history_retrieval.py),
[checkpoint schemas](../../ai_workbench/core/schema/retrieval.py) and
[behavior tests](../../tests/test_history_retrieval.py) already separate
session memory from run progress, commit conversation checkpoints on success,
check `history_version`, and invalidate derived state on history mutation.
These session-scoped checkpoints are not an independent cross-session fact store.
Knowledge already provides hybrid retrieval and optional reranking.

### Recommendations for Cogita

These are research recommendations, not scheduled implementation work.

1. Keep four responsibilities distinct: original history, session/run working
   checkpoints, durable learned facts, and user-maintained instructions or
   external Knowledge. Do not turn every summary into persistent user memory.
2. Define access scope before choosing storage. Workspace facts belong to their
   Project unless explicitly promoted; QQ facts need conversation and subject
   attribution. Reusing a Persona must not silently share unrelated knowledge.
3. Start with user-inspectable remember, correct and forget behavior, concise
   entries, source IDs and revisions. Let model candidates commit against a
   valid source/version boundary. Explicit user deletion should not depend on
   a successful model reply, and stale writers must not resurrect deleted facts.
4. Adopt progressive disclosure within the existing ContextBuilder budget:
   a small relevant index or selected facts, then bounded reads. Count the
   complete request and retain Context detail provenance. Introduce deeper
   hierarchy only when a flat bounded index becomes inadequate.
5. Borrow versioned proposals and successful-coverage accounting from reflection,
   without requiring a Git repository per memory owner. SQLite transactions
   and explicit revisions fit the current application better. Git is useful
   for portable editable documents, but brings checkout, merge, sync and
   retention responsibilities that this research does not justify adding now.
6. Keep learned evidence below instruction authority. Letta deliberately learns
   by editing system-prompt memory and skills; Cogita should not automatically
   promote recalled web text, quoted messages or model conclusions into Persona
   instructions, executable procedures or tool permissions.
7. Consider background consolidation only after scope, corrections, deletion,
   concurrency and recall quality are accepted. It needs explicit model choice,
   inference budgets, cancellation, source coverage, retry semantics and visible
   outcomes. All inference must continue through `core/models`; external calls
   remain OpenAI-compatible. No new extension registry or YAML architecture is
   implied by Letta's files or mods.

The research leaves ordinary-chat memory ownership, read/write switches,
history-off behavior, operation without Harness, automatic extraction model
selection, and the scope of forgetting as product decisions. It does not
select new endpoints, defaults, background workers or migration schemas.

### Meaningful future acceptance

| Scenario | Observation needed |
| --- | --- |
| New session, same allowed scope | Correct durable facts survive without importing unrelated conversation state |
| Same Persona, different Project or QQ subject | No accidental cross-scope recall or attribution |
| Changed preference or fact | Current answer uses the correction and can identify its evidence |
| Quote, tool output or assistant hypothesis | No silent promotion into an asserted user fact or authoritative instruction |
| Deferred detail | Representative indirect queries actually reach the right entry within budget |
| Candidate failure or cancellation | Previously committed facts remain intact and source coverage does not advance incorrectly |
| Concurrent correction and deletion | Stale proposals neither overwrite newer facts nor recreate removed content |
| Evidence edit, deletion or retry | Derived-memory handling follows a documented policy atomically |
| Disabled memory or history | Reads, writes, extraction and existing retention have distinct tested behavior |
| Future background consolidation | Duplicate/replayed slices, conflicts and no-change results have explicit outcomes |
| Growing store | Index cost, retrieval cost and total request size remain bounded |
| Forgetting | Current facts, derived copies, indexes and retention boundaries match the product promise |

Measure supported-fact recall, stale answers, incorrect attribution, unwanted
writes, cross-scope exposure, extra inference calls and total token cost.
Upstream [layout tests][test-layout], [worktree tests][test-worktree],
[constraint tests][test-constraints] and [completion tests][test-completion]
exercise storage and integration behavior; they do not establish these model
quality outcomes. The strongest transferable ideas are discoverable concise
memory, visible versioned changes, evidence-aware corrections and explicit
failure boundaries, rather than a particular storage engine or dreaming label.

[docs-memory]: https://docs.letta.com/configuration/memory
[docs-memfs]: https://docs.letta.com/concepts/memfs
[docs-sdk-memory]: https://docs.letta.com/agent-sdk/memory
[docs-stateful]: https://docs.letta.com/concepts/stateful-agents
[docs-conversations]: https://docs.letta.com/concepts/conversations
[docs-sessions]: https://docs.letta.com/agent-sdk/sessions
[docs-shared]: https://docs.letta.com/concepts/shared-memory
[docs-repositories]: https://docs.letta.com/agent-sdk/repositories
[code]: https://github.com/letta-ai/letta-code/tree/ee6e2c588082cbd98d8db1e20b18096585afa5bf
[constitution-repo]: https://github.com/letta-ai/context-constitution/tree/964f30137ace9eade1aef112992ed6539b61bbb0
[affordances]: https://github.com/letta-ai/context-constitution/blob/964f30137ace9eade1aef112992ed6539b61bbb0/constitution/AFFORDANCES.md
[src-format]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/agent/memory-format.ts
[src-initial]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/backend/local/initial-memory.ts
[src-compiler]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/backend/local/system-prompt-compilation.ts
[src-doctor]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/cli/helpers/doctor-command.ts
[src-doctor-audit]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/skills/builtin/context-doctor/references/auditing-memory.md
[src-reflection-prompt]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/agent/subagents/builtin/reflection-v2.md
[src-core-guidance]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/skills/builtin/maintaining-core-memory/SKILL.md
[src-deferred-guidance]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/skills/builtin/maintaining-deferred-memory/SKILL.md
[src-constraints]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/memory-constraints.ts
[src-validator]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/agent/memory-constraints.ts
[src-reflection-settings]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/cli/helpers/memory-reminder.ts
[src-reflection-launcher]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/cli/helpers/reflection-launcher.ts
[src-worktree]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/agent/memory-worktree.ts
[src-reflection-transcript]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/cli/helpers/reflection-transcript.ts
[src-integration]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/cli/helpers/reflection-integration.ts
[src-operation]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/agent/memory-operation.ts
[src-git]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/agent/memory-git.ts
[src-completion]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/cli/helpers/reflection-completion.ts
[test-layout]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/backend/local-fresh-memory-layout.test.ts
[test-worktree]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/agent/memory-worktree.test.ts
[test-constraints]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/agent/memory-git-v2-precommit.test.ts
[test-completion]: https://github.com/letta-ai/letta-code/blob/ee6e2c588082cbd98d8db1e20b18096585afa5bf/src/cli/helpers/reflection-completion.test.ts
