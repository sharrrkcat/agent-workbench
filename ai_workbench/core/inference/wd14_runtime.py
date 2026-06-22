from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Any

from ai_workbench.core.knowledge_models import models_root_path
from ai_workbench.core.provider_inventory import internal_provider_backend_status
from ai_workbench.core.provider_runtime import provider_runtime_settings
from ai_workbench.core.vision_profiles import normalize_vision_model_ref, vision_provider_compatibility_error


def preflight_wd14_runtime(
    profile: Any,
    *,
    repo_root: Path | None = None,
    provider_profile_store: Any = None,
    load_model: bool = False,
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    profile_id = str(getattr(profile, "id", ""))
    architecture = str(getattr(profile, "architecture", ""))
    backend = str(getattr(profile, "backend", ""))
    provider = _provider_for_profile(profile, provider_profile_store)
    backend_status = internal_provider_backend_status("internal_onnxruntime")

    def add_check(check_id: str, status: str, message: str) -> None:
        checks.append({"id": check_id, "status": status, "message": message})

    if architecture == "wd14":
        add_check("architecture", "pass", "Vision profile uses the WD14 architecture.")
    else:
        add_check("architecture", "fail", "Vision profile architecture is not supported by WD14 preflight.")

    if backend == "onnxruntime":
        add_check("backend", "pass", "Vision profile uses the ONNX Runtime backend.")
    else:
        add_check("backend", "fail", "WD14 requires the ONNX Runtime backend.")

    provider_error = vision_provider_compatibility_error(profile, provider_profile_store)
    if provider_error is None:
        add_check("provider", "pass", "Vision profile uses an internal ONNX Runtime provider profile.")
    else:
        add_check("provider", "fail", provider_error)

    if backend_status.get("onnxruntime_available"):
        add_check("dependencies", "pass", "ONNX Runtime dependencies are available.")
    else:
        add_check("dependencies", "fail", "Missing ONNX Runtime dependencies.")

    _preflight_execution_provider(provider, backend_status, add_check)
    _preflight_model_file(profile, repo_root, add_check)

    if load_model:
        add_check("model_load", "fail", "WD14 ONNX model loading is not implemented yet.")

    return {
        "ok": all(check["status"] == "pass" for check in checks),
        "profile_id": profile_id,
        "architecture": architecture,
        "load_model": bool(load_model),
        "checks": checks,
        "runtime": {
            "onnxruntime_version": _package_version("onnxruntime"),
            **backend_status,
        },
    }


def _preflight_execution_provider(provider: Any, backend_status: dict[str, Any], add_check: Any) -> None:
    settings = provider_runtime_settings(provider)
    selected = settings.get("onnx_execution_provider", "auto")
    available_providers = backend_status.get("available_providers") or []
    if selected == "cuda" and "CUDAExecutionProvider" not in available_providers:
        add_check("execution_provider", "fail", "CUDAExecutionProvider is not available.")
        return
    if selected == "cpu" and backend_status.get("onnxruntime_available") and "CPUExecutionProvider" not in available_providers:
        add_check("execution_provider", "fail", "CPUExecutionProvider is not available.")
        return
    add_check("execution_provider", "pass", f"ONNX execution provider setting is valid: {selected}.")


def _preflight_model_file(profile: Any, repo_root: Path | None, add_check: Any) -> None:
    try:
        normalized = normalize_vision_model_ref(getattr(profile, "provider_model_id", ""))
        relative = normalized.removeprefix("vision/")
        root = (models_root_path(repo_root).resolve() / "vision").resolve()
        model_dir = (root / relative).resolve()
        model_dir.relative_to(root)
        model_file = (model_dir / "model.onnx").resolve()
        model_file.relative_to(model_dir)
    except Exception:
        add_check("model_file", "fail", "WD14 model reference is invalid.")
        return
    if model_dir.is_symlink() or model_file.is_symlink() or not model_file.is_file():
        add_check("model_file", "fail", "WD14 requires data/models/vision/<folder>/model.onnx.")
        return
    add_check("model_file", "pass", "WD14 model.onnx is available.")


def _provider_for_profile(profile: Any, provider_profile_store: Any) -> Any:
    provider_id = getattr(profile, "provider_profile_id", None)
    if not provider_id or provider_profile_store is None:
        return None
    try:
        return provider_profile_store.get(str(provider_id))
    except Exception:
        return None


def _package_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "not_installed"
    except Exception:
        return "unknown"
