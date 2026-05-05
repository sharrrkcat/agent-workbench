import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_check_script_runs_successfully(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'check.db'}"

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check.py")],
        cwd=ROOT,
        env={**__import__("os").environ, "AGENT_WORKBENCH_DATABASE_URL": db_url},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "[OK] Schema version" in result.stdout


def test_reset_data_script_deletes_temp_database_with_yes(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_workbench_test.db"
    db_path.write_text("placeholder", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "reset_data.py"),
            "--database-url",
            f"sqlite:///{db_path}",
            "--yes",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert not db_path.exists()


def test_check_agents_script_runs_successfully() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_agents.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "[OK] Agent checks passed" in result.stdout


def test_check_agents_detects_script_agent_without_run(tmp_path: Path) -> None:
    module = load_script_module("check_agents")
    agents_root = tmp_path / "agents"
    agent_dir = agents_root / "bad_script"
    agent_dir.mkdir(parents=True)
    (agent_dir / "agent.yaml").write_text(
        textwrap.dedent(
            """
            id: bad_script
            name: Bad Script
            type: script
            entry: agent.py
            actions:
              - id: default
            context_policy:
              mode: current_message
            model_lifecycle:
              load: on_demand
              unload: manual
              unload_failure: warn
            """
        ).strip(),
        encoding="utf-8",
    )
    (agent_dir / "agent.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = module.check_agents(agents_root=agents_root, capabilities_root=ROOT / "capabilities")

    assert result.ok is False
    assert any("must export run(ctx)" in error for error in result.errors)


def test_check_agents_detects_entry_escape(tmp_path: Path) -> None:
    module = load_script_module("check_agents")
    agents_root = tmp_path / "agents"
    agent_dir = agents_root / "escape_script"
    agent_dir.mkdir(parents=True)
    (tmp_path / "outside.py").write_text("async def run(ctx):\n    pass\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        textwrap.dedent(
            """
            id: escape_script
            name: Escape Script
            type: script
            entry: ../../outside.py
            actions:
              - id: default
            context_policy:
              mode: current_message
            model_lifecycle:
              load: on_demand
              unload: manual
              unload_failure: warn
            """
        ).strip(),
        encoding="utf-8",
    )

    result = module.check_agents(agents_root=agents_root, capabilities_root=ROOT / "capabilities")

    assert result.ok is False
    assert any("script entry must stay inside the agent directory" in error for error in result.errors)


def test_run_agent_script_runs_echo_script() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_agent.py"), "echo_script", "hello"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "run status: done" in result.stdout
    assert "agent [text]: aGVsbG8=" in result.stdout


def test_run_agent_script_unknown_agent_fails_clearly() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_agent.py"), "unknown_agent", "hello"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Unknown agent: unknown_agent" in result.stdout


def test_run_agent_script_unknown_action_fails_clearly() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_agent.py"), "echo_script:missing_action", "hello"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Unknown action 'missing_action' for agent 'echo_script'." in result.stdout


def load_script_module(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
