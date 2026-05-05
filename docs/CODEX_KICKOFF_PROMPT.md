# Codex Kickoff Prompt

You are implementing a new lightweight personal AI workbench.

Start by reading `AGENTS.md`, then implement `docs/CODEX_ROUND_1.md`.

Important constraints:

- Keep the first round small.
- Implement only schema, manifest loading, and registries.
- Use Pydantic v2.
- Use tests.
- Agents are invoked with `@agent_id`.
- Agent actions are invoked with `@agent_id:action`.
- Commands are invoked with `/command`.
- Slash Commands belong only to Capability manifests.
- Agents must not declare slash command aliases.
- Commands must be globally unique.
- Agent ids must be globally unique.
- The first example Agents are `chat` and `translate`.
- The first example Capability is `base64`, exposing `/base64` and `/base64-decode`.
- Do not add external app integrations during the first core round.

When the round is complete, summarize changed files, tests run, results, limitations, and next suggested round.
