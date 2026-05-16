import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class TemplateError(ValueError):
    pass


def create_capability(
    capability_id: str,
    name: str | None = None,
    description: str | None = None,
    root: str | Path = ROOT,
    force: bool = False,
    dry_run: bool = False,
) -> list[Path]:
    _validate_id(capability_id, "capability id")

    repo_root = Path(root)
    capability_dir = repo_root / "capabilities" / capability_id
    if capability_dir.exists() and not force:
        raise TemplateError(f"Capability directory already exists: {capability_dir}")

    display_name = name or _title_from_id(capability_id)
    display_description = description or f"{display_name}."
    files = {
        capability_dir / "capability.yaml": _manifest(capability_id, display_name, display_description),
        capability_dir / "__init__.py": _runtime(),
    }

    if dry_run:
        return list(files)

    capability_dir.mkdir(parents=True, exist_ok=True)
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    return list(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a Capability template.")
    parser.add_argument("capability_id")
    parser.add_argument("--name")
    parser.add_argument("--description")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        created = create_capability(
            args.capability_id,
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


def _manifest(capability_id: str, name: str, description: str) -> str:
    command_name = f"/{capability_id}"
    return f"""id: {capability_id}
name: {name}
description: {description}

methods:
  - id: echo
    description: Echo input text.
    input_schema:
      text:
        type: string
        required: true
    output:
      part_type: text
      format: plain

commands:
  - name: {command_name}
    method: echo
    description: Echo input text.
    safe: true
"""


def _runtime() -> str:
    return '''class CapabilityRuntime:
    def echo(self, text: str) -> str:
        return text


def get_runtime():
    return CapabilityRuntime()
'''


def _validate_id(value: str, label: str) -> None:
    if not ID_RE.fullmatch(value):
        raise TemplateError(f"{label} must be lowercase snake_case and match ^[a-z][a-z0-9_]*$")


def _title_from_id(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split("_"))


if __name__ == "__main__":
    raise SystemExit(main())
