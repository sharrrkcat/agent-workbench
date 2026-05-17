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


def test_create_agent_script_template_dry_run() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "create_agent.py"),
            "my_agent",
            "--type",
            "script",
            "--dry-run",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "agents" in result.stdout
    assert "agent.yaml" in result.stdout
    assert "agent.py" in result.stdout


def test_create_agent_script_template_real_create(tmp_path: Path) -> None:
    module = load_script_module("create_agent")

    created = module.create_agent("my_agent", agent_type="script", root=tmp_path)

    assert tmp_path / "agents" / "my_agent" / "agent.yaml" in created
    assert (tmp_path / "agents" / "my_agent" / "agent.py").is_file()
    check_module = load_script_module("check_agents")
    result = check_module.check_agents(
        agents_root=tmp_path / "agents",
        capabilities_root=ROOT / "capabilities",
        strict=True,
    )
    assert result.ok is True


def test_create_agent_prompt_template_real_create(tmp_path: Path) -> None:
    module = load_script_module("create_agent")

    module.create_agent("prompt_demo", agent_type="prompt", root=tmp_path)

    manifest = tmp_path / "agents" / "prompt_demo" / "agent.yaml"
    assert manifest.is_file()
    assert not (tmp_path / "agents" / "prompt_demo" / "agent.py").exists()
    check_module = load_script_module("check_agents")
    result = check_module.check_agents(
        agents_root=tmp_path / "agents",
        capabilities_root=ROOT / "capabilities",
        strict=True,
    )
    assert result.ok is True


def test_create_agent_rejects_illegal_id(tmp_path: Path) -> None:
    module = load_script_module("create_agent")

    try:
        module.create_agent("Bad-Agent", root=tmp_path)
    except module.TemplateError as exc:
        assert "lowercase snake_case" in str(exc)
    else:
        raise AssertionError("expected invalid id to fail")


def test_create_agent_existing_directory_fails(tmp_path: Path) -> None:
    module = load_script_module("create_agent")
    (tmp_path / "agents" / "my_agent").mkdir(parents=True)

    try:
        module.create_agent("my_agent", root=tmp_path)
    except module.TemplateError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("expected existing directory to fail")


def test_create_capability_template_real_create(tmp_path: Path) -> None:
    module = load_script_module("create_capability")

    module.create_capability("demo_tool", root=tmp_path)

    assert (tmp_path / "capabilities" / "demo_tool" / "capability.yaml").is_file()
    assert (tmp_path / "capabilities" / "demo_tool" / "__init__.py").is_file()


def test_create_capability_rejects_illegal_id(tmp_path: Path) -> None:
    module = load_script_module("create_capability")

    try:
        module.create_capability("123_demo", root=tmp_path)
    except module.TemplateError as exc:
        assert "lowercase snake_case" in str(exc)
    else:
        raise AssertionError("expected invalid id to fail")


def test_check_agents_strict_passes_current_repo() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_agents.py"), "--strict"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "[OK] Agent checks passed" in result.stdout


def test_check_agents_strict_recognizes_script_lifecycle_lab() -> None:
    module = load_script_module("check_agents")
    result = module.check_agents(
        agents_root=ROOT / "agents",
        capabilities_root=ROOT / "capabilities",
        strict=True,
    )

    assert result.ok is True
    assert "script_lifecycle_lab" in {agent["id"] for agent in result.agents}


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


def test_check_agents_strict_detects_missing_runtime_method(tmp_path: Path) -> None:
    module = load_script_module("check_agents")
    agents_root = tmp_path / "agents"
    write_valid_agent(agents_root, "demo_agent")
    capability_dir = tmp_path / "capabilities" / "bad_capability"
    capability_dir.mkdir(parents=True)
    (capability_dir / "capability.yaml").write_text(
        textwrap.dedent(
            """
            id: bad_capability
            name: Bad Capability
            methods:
              - id: missing
                output:
                  part_type: text
                  format: plain
            commands:
              - name: /bad-capability
                method: missing
            """
        ).strip(),
        encoding="utf-8",
    )
    (capability_dir / "__init__.py").write_text(
        "class CapabilityRuntime:\n    pass\n",
        encoding="utf-8",
    )

    result = module.check_workbench(
        agents_root=agents_root,
        capabilities_root=tmp_path / "capabilities",
        strict=True,
    )

    assert result.ok is False
    assert any("missing callable runtime method" in error for error in result.errors)


def test_check_agents_strict_detects_duplicate_command_name(tmp_path: Path) -> None:
    module = load_script_module("check_agents")
    agents_root = tmp_path / "agents"
    write_valid_agent(agents_root, "demo_agent")
    for capability_id in ["first_tool", "second_tool"]:
        capability_dir = tmp_path / "capabilities" / capability_id
        capability_dir.mkdir(parents=True)
        (capability_dir / "capability.yaml").write_text(
            textwrap.dedent(
                f"""
                id: {capability_id}
                name: {capability_id}
                methods:
                  - id: echo
                    output:
                      part_type: text
                      format: plain
                commands:
                  - name: /same-command
                    method: echo
                """
            ).strip(),
            encoding="utf-8",
        )
        (capability_dir / "__init__.py").write_text(
            "class CapabilityRuntime:\n    def echo(self, text: str) -> str:\n        return text\n",
            encoding="utf-8",
        )

    result = module.check_workbench(
        agents_root=agents_root,
        capabilities_root=tmp_path / "capabilities",
        strict=True,
    )

    assert result.ok is False
    assert any("duplicates command" in error for error in result.errors)


def test_run_agent_script_runs_script_lifecycle_lab() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_agent.py"), "script_lifecycle_lab:steps", "hello"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "run status: done" in result.stdout
    assert "assistant [parts]:" in result.stdout
    assert "Step Test Complete" in result.stdout


def test_run_agent_script_json_output_is_valid_json() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_agent.py"), "script_lifecycle_lab:steps", "hello", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    payload = __import__("json").loads(result.stdout)

    assert result.returncode == 0
    assert payload["run"]["status"] == "DONE"
    assert "Step Test Complete" in payload["messages"][-1]["parts"][0]["text"]
    assert payload["error"] is None


def test_run_agent_script_markdown_message_has_no_extra_json_quotes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_agent.py"), "script_lifecycle_lab:steps", "hello"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "assistant [parts]:" in result.stdout
    assert "# Step Test Complete" in result.stdout
    assert '"# Step Test Complete' not in result.stdout


def test_run_agent_supports_colon_action_argument() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_agent.py"), "script_lifecycle_lab:steps", "hello"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "assistant [parts]:" in result.stdout
    assert "Input: hello" in result.stdout


def test_run_agent_supports_action_argument() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_agent.py"), "script_lifecycle_lab", "hello", "--action", "steps"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "assistant [parts]:" in result.stdout
    assert "Input: hello" in result.stdout


def test_run_agent_summarizes_non_text_part_outputs() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_agent.py"), "script_lifecycle_lab:audio_demo", "hello"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "assistant [parts]:" in result.stdout
    assert "audio" in result.stdout


def test_run_agent_missing_llm_model_hint_mentions_env_var(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKBENCH_LLM_MODEL", raising=False)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_agent.py"), "chat", "hello"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={key: value for key, value in __import__("os").environ.items() if key != "AGENT_WORKBENCH_LLM_MODEL"},
    )

    assert result.returncode != 0
    assert "run status: failed" in result.stdout


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
        [sys.executable, str(ROOT / "scripts" / "run_agent.py"), "script_lifecycle_lab:missing_action", "hello"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Unknown action 'missing_action' for agent 'script_lifecycle_lab'." in result.stdout


def test_run_command_runs_base64() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_command.py"), "/encode base64 hello"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "run status: done" in result.stdout
    assert "declared output part: file" in result.stdout
    assert "aGVsbG8=" in result.stdout


def test_run_command_summarizes_image_output_without_full_data_url() -> None:
    svg_data_url = (
        "data:image/svg+xml;base64,"
        "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMjAiIGhlaWdodD0iNjAiPjx0ZXh0IHg9IjgiIHk9IjM1Ij5vazwvdGV4dD48L3N2Zz4="
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_command.py"), f"/decode base64 {svg_data_url}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "declared output part: image" in result.stdout
    assert "image:" in result.stdout
    assert "url_length=" in result.stdout
    assert "content:\nimage:" in result.stdout


def load_script_module(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_valid_agent(agents_root: Path, agent_id: str) -> None:
    agent_dir = agents_root / agent_id
    agent_dir.mkdir(parents=True)
    (agent_dir / "agent.yaml").write_text(
        textwrap.dedent(
            f"""
            id: {agent_id}
            name: Demo Agent
            type: prompt
            actions:
              - id: default
                label: Chat
            prompt: Hello.
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
