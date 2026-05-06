import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class TemplateError(ValueError):
    pass


def create_agent(
    agent_id: str,
    agent_type: str = "script",
    name: str | None = None,
    description: str | None = None,
    root: str | Path = ROOT,
    force: bool = False,
    dry_run: bool = False,
) -> list[Path]:
    _validate_id(agent_id, "agent id")
    if agent_type not in {"script", "prompt"}:
        raise TemplateError("--type must be one of: script, prompt")

    repo_root = Path(root)
    agent_dir = repo_root / "agents" / agent_id
    if agent_dir.exists() and not force:
        raise TemplateError(f"Agent directory already exists: {agent_dir}")

    display_name = name or _title_from_id(agent_id)
    display_description = description or f"{display_name}."
    files = _agent_files(agent_id, agent_type, display_name, display_description, agent_dir)

    if dry_run:
        return list(files)

    agent_dir.mkdir(parents=True, exist_ok=True)
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    return list(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a Prompt Agent or Script Agent template.")
    parser.add_argument("agent_id")
    parser.add_argument("--type", choices=["script", "prompt"], default="script")
    parser.add_argument("--name")
    parser.add_argument("--description")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        created = create_agent(
            args.agent_id,
            agent_type=args.type,
            name=args.name,
            description=args.description,
            root=args.root,
            force=args.force,
            dry_run=args.dry_run,
        )
    except TemplateError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    verb = "would create" if args.dry_run else "created"
    for path in created:
        print(f"[OK] {verb}: {path}")
    return 0


def _agent_files(
    agent_id: str,
    agent_type: str,
    name: str,
    description: str,
    agent_dir: Path,
) -> dict[Path, str]:
    if agent_type == "prompt":
        return {
            agent_dir / "agent.yaml": _prompt_manifest(agent_id, name, description),
        }
    return {
        agent_dir / "agent.yaml": _script_manifest(agent_id, name, description),
        agent_dir / "agent.py": _script_runtime(),
    }


def _script_manifest(agent_id: str, name: str, description: str) -> str:
    return f"""id: {agent_id}
name: {name}
type: script
description: {description}
entry: agent.py

actions:
  - id: default
    label: Run
    description: Run the script agent.

context_policy:
  mode: current_message
  max_messages: 1
  max_chars: 4000

model_lifecycle:
  load: on_demand
  unload: manual
  unload_failure: warn
"""


def _prompt_manifest(agent_id: str, name: str, description: str) -> str:
    return f"""id: {agent_id}
name: {name}
type: prompt
description: {description}
avatar: ""

actions:
  - id: default
    label: Chat
    description: Reply to the current user message.

prompt: |
  You are concise, practical, and helpful.

context_policy:
  mode: current_message
  max_messages: 1
  max_chars: 4000

model_lifecycle:
  load: on_demand
  unload: never
  unload_failure: warn
"""


def _script_runtime() -> str:
    return '''async def run(ctx):
    """Entry point for this Script Agent."""
    async with ctx.step("prepare"):
        text = ctx.input.text.strip()

    if not text:
        await ctx.reply_text("No input provided.")
        return

    await ctx.reply_markdown(f"**Input**\\n\\n{text}")
    await ctx.reply_json({"received": text, "length": len(text)})

    # Optional LLM helper when this Agent is configured for a model:
    # summary = await ctx.llm.text(system="Summarize briefly.", user=text)
    # await ctx.reply_text(summary)
'''


def _validate_id(value: str, label: str) -> None:
    if not ID_RE.fullmatch(value):
        raise TemplateError(f"{label} must be lowercase snake_case and match ^[a-z][a-z0-9_]*$")


def _title_from_id(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split("_"))


if __name__ == "__main__":
    raise SystemExit(main())
