import sys
from pathlib import Path

from sqlalchemy import inspect

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_workbench.core.agent_registry import AgentRegistry
from ai_workbench.core.capability_registry import CapabilityRegistry
from ai_workbench.core.command_registry import CommandRegistry
from ai_workbench.db.database import SCHEMA_VERSION, get_engine, init_db
from ai_workbench.db.models import AppMetadataRecord


def main() -> int:
    checks = []
    try:
        checks.append(("Python version", check_python_version()))
        agents = check_agents()
        checks.append(("Agent manifests", f"{len(agents.list())} loaded"))
        capabilities = check_capabilities()
        checks.append(("Capability manifests", f"{len(capabilities.list())} loaded"))
        commands = CommandRegistry.from_capability_registry(capabilities)
        checks.append(("Command registry", f"{len(commands.list())} commands registered"))
        checks.append(("Database initialization", check_database()))
        checks.append(("Schema version", check_schema_version()))
        checks.append(("FastAPI app", check_app_health()))
    except Exception as exc:
        print(f"[FAIL] {exc}")
        return 1

    for name, message in checks:
        print(f"[OK] {name}: {message}")
    return 0


def check_python_version() -> str:
    version = sys.version_info
    if version < (3, 10):
        raise RuntimeError(f"Python 3.10+ is required, found {version.major}.{version.minor}.{version.micro}")
    return f"{version.major}.{version.minor}.{version.micro}"


def check_agents() -> AgentRegistry:
    registry = AgentRegistry()
    registry.load_from_directory(ROOT / "agents")
    registry.get("chat")
    registry.get("translate")
    return registry


def check_capabilities() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.load_from_directory(ROOT / "capabilities")
    registry.get("llm")
    registry.get("base64")
    return registry


def check_database() -> str:
    engine = get_engine()
    init_db(engine)
    tables = set(inspect(engine).get_table_names())
    if AppMetadataRecord.__tablename__ not in tables:
        raise RuntimeError("metadata table was not created")
    return "initialized"


def check_schema_version() -> str:
    engine = get_engine()
    init_db(engine)
    from sqlmodel import Session

    with Session(engine) as session:
        record = session.get(AppMetadataRecord, "schema_version")
    if record is None:
        raise RuntimeError("schema_version metadata is missing")
    if record.value != SCHEMA_VERSION:
        raise RuntimeError(f"schema_version mismatch: expected {SCHEMA_VERSION}, found {record.value}")
    return record.value


def check_app_health() -> str:
    from fastapi.testclient import TestClient

    from ai_workbench.api.main import create_app

    client = TestClient(create_app(use_memory=True))
    health = client.get("/api/health")
    if health.status_code != 200 or health.json().get("status") != "ok":
        raise RuntimeError(f"/api/health failed: {health.text}")
    details = client.get("/api/health/details")
    if details.status_code != 200:
        raise RuntimeError(f"/api/health/details failed: {details.text}")
    payload = details.json()
    registries = payload.get("registries", {})
    if registries.get("agents", 0) < 1 or registries.get("capabilities", 0) < 1 or registries.get("commands", 0) < 1:
        raise RuntimeError(f"registry counts are not healthy: {registries}")
    if "api_key" in str(payload).lower() and "api_key_set" not in str(payload):
        raise RuntimeError("/api/health/details leaked api key material")
    return "health endpoints ok"


if __name__ == "__main__":
    raise SystemExit(main())
