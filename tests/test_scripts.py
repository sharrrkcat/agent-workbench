import subprocess
import sys
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
