"""The application-bundled DLSS component; no remote component registry."""
from pathlib import Path

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.schema import ComponentRelease, model_path
from ai_workbench.core.models.schema import ModelProfile


BUNDLED_ROOT = Path(__file__).parent / "bundled"


def bundled_release() -> ComponentRelease:
    return ComponentRelease.model_validate_json((BUNDLED_ROOT / "dlss5nr.json").read_bytes())


def bootstrap_processor(root, profiles, installation):
    directory = model_path(root, "processors/dlss5-nr")
    directory.mkdir(parents=True, exist_ok=True)
    if installation.default_profile_id:
        try:
            profiles.get(installation.default_profile_id)
            return
        except KeyError:
            pass  # Explicit install recreates a deleted default profile.
    alias, suffix = "dlss5-nr", 2
    while profiles.find_by_alias(alias):
        alias = f"dlss5-nr-{suffix}"
        suffix += 1
    profile = profiles.create(ModelProfile(name="DLSS 5 NR", alias=alias, kind="processor",
        model_ref="processors/dlss5-nr", source={"type": "local"}))
    installation.default_profile_id = profile.id


def require_component(value):
    if value.state == "installed":
        return
    code = {"not_installed": "RUNTIME_COMPONENT_NOT_INSTALLED", "installing": "RUNTIME_INSTALLING",
            "unsupported": "RUNTIME_COMPONENT_INCOMPATIBLE"}.get(value.state, "RUNTIME_COMPONENT_BROKEN")
    raise ModelError(code, "Install or repair the DLSS NR component in Local Runtime settings.", 503,
        {"component_id": value.component_id, "action": "install" if value.state == "not_installed" else "repair"})
