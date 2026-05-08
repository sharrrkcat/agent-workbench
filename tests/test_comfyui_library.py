import json
from pathlib import Path

import yaml

from capabilities.comfyui import CapabilityRuntime


def api_workflow() -> dict:
    return {
        "3": {"class_type": "KSampler", "inputs": {"steps": 30, "cfg": 7.0}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
    }


def context(tmp_path: Path, allow_preset_write: bool = True) -> dict:
    return {
        "capability_config": {
            "workflows_dir": str(tmp_path / "workflows"),
            "presets_dir": str(tmp_path / "presets"),
            "allow_preset_file_write": allow_preset_write,
            "allow_workflow_file_write": True,
            "auto_create_missing_presets": True,
        }
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_preset(path: Path, **overrides) -> dict:
    preset = {
        "id": "txt2img_basic",
        "name": "Text to Image Basic",
        "status": "ready",
        "workflow": {"file_name": "txt2img.workflow.json"},
        "parameters": [
            {
                "name": "positive_prompt",
                "type": "textarea",
                "required": True,
                "default": "",
                "mapping": {"node_id": "6", "input_path": ["inputs", "text"]},
                "custom_note": "preserved",
            },
            {
                "name": "steps",
                "type": "integer",
                "default": 30,
                "minimum": 1,
                "maximum": 150,
                "mapping": {"node_id": "3", "input_path": ["inputs", "steps"]},
            },
        ],
        "output": {"images": "all"},
    }
    for key, value in overrides.items():
        preset[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(preset, sort_keys=False), encoding="utf-8")
    return preset


def test_scan_workflow_library_identifies_api_workflow_and_hash(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "txt2img.workflow.json", api_workflow())
    runtime = CapabilityRuntime()

    first = runtime.scan_workflow_library(context=context(tmp_path))
    second = runtime.scan_workflow_library(context=context(tmp_path))

    workflow = first["workflows"][0]
    assert workflow["valid"] is True
    assert workflow["format"] == "api"
    assert workflow["node_count"] == 3
    assert "KSampler" in workflow["class_types"]
    assert workflow["hash"] == second["workflows"][0]["hash"]


def test_scan_marks_gui_format_unsupported_without_crashing(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "gui.json", {"nodes": [], "links": [], "widgets_values": []})

    workflow = CapabilityRuntime().scan_workflow_library(context=context(tmp_path))["workflows"][0]

    assert workflow["valid"] is False
    assert workflow["format"] == "unsupported_gui_format"
    assert "API-format" in workflow["errors"][0]


def test_duplicate_workflow_hash_is_reported(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "a.json", api_workflow())
    write_json(tmp_path / "workflows" / "b.json", api_workflow())

    scan = CapabilityRuntime().scan_workflow_library(context=context(tmp_path))

    assert len(scan["duplicates"]) == 1
    assert scan["duplicates"][0]["file_names"] == ["a.json", "b.json"]
    assert scan["workflows"][1]["duplicate_of"] == "a.json"


def test_list_workflows_returns_file_hash_and_node_count(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "txt2img.workflow.json", api_workflow())

    result = CapabilityRuntime().list_workflows(context=context(tmp_path))

    assert result["workflows"][0]["file_name"] == "txt2img.workflow.json"
    assert result["workflows"][0]["hash"].startswith("sha256:")
    assert result["workflows"][0]["node_count"] == 3


def test_validate_preset_rejects_path_traversal_workflow_file(tmp_path: Path) -> None:
    preset = {"id": "bad", "name": "Bad", "workflow": {"file_name": "../bad.json"}, "parameters": [], "output": {"images": "all"}}

    result = CapabilityRuntime().validate_preset(preset=preset, context=context(tmp_path))

    assert result["valid"] is False
    assert any("basename" in error for error in result["errors"])


def test_validate_preset_ready_success_and_custom_parameter_fields_preserved(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "txt2img.workflow.json", api_workflow())
    write_preset(tmp_path / "presets" / "txt2img.yaml")

    result = CapabilityRuntime().validate_preset(preset_id="txt2img_basic", context=context(tmp_path))

    assert result["valid"] is True
    assert result["status"] == "ready"
    assert result["parameters"][0]["custom_note"] == "preserved"


def test_validate_preset_missing_workflow_errors(tmp_path: Path) -> None:
    write_preset(tmp_path / "presets" / "txt2img.yaml")

    result = CapabilityRuntime().validate_preset(preset_id="txt2img_basic", context=context(tmp_path))

    assert result["valid"] is False
    assert any("Workflow file does not exist" in error for error in result["errors"])


def test_validate_preset_hash_mismatch_warns(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "txt2img.workflow.json", api_workflow())
    write_preset(tmp_path / "presets" / "txt2img.yaml", workflow={"file_name": "txt2img.workflow.json", "hash": "sha256:bad"})

    result = CapabilityRuntime().validate_preset(preset_id="txt2img_basic", context=context(tmp_path))

    assert result["valid"] is True
    assert result["workflow"]["hash_matches"] is False
    assert any("hash" in warning for warning in result["warnings"])


def test_validate_preset_mapping_node_and_input_path_errors(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "txt2img.workflow.json", api_workflow())
    bad_node = write_preset(
        tmp_path / "presets" / "bad_node.yaml",
        id="bad_node",
        parameters=[{"name": "positive_prompt", "type": "textarea", "required": True, "mapping": {"node_id": "999", "input_path": ["inputs", "text"]}}],
    )
    bad_path = dict(bad_node)
    bad_path["id"] = "bad_path"
    bad_path["parameters"] = [{"name": "positive_prompt", "type": "textarea", "required": True, "mapping": {"node_id": "6", "input_path": ["inputs", "missing"]}}]
    (tmp_path / "presets" / "bad_path.yaml").write_text(yaml.safe_dump(bad_path), encoding="utf-8")

    node_result = CapabilityRuntime().validate_preset(preset_id="bad_node", context=context(tmp_path))
    path_result = CapabilityRuntime().validate_preset(preset_id="bad_path", context=context(tmp_path))

    assert any("node_id" in error for error in node_result["errors"])
    assert any("input_path" in error for error in path_result["errors"])


def test_same_workflow_can_have_multiple_presets(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "txt2img.workflow.json", api_workflow())
    write_preset(tmp_path / "presets" / "a.yaml", id="preset_a")
    write_preset(tmp_path / "presets" / "b.yaml", id="preset_b")

    scan = CapabilityRuntime().scan_workflow_library(context=context(tmp_path))

    assert {preset["preset_id"] for preset in scan["presets"]} == {"preset_a", "preset_b"}
    assert scan["missing_preset_workflows"] == []
    assert scan["created_draft_presets"] == []


def test_missing_preset_workflow_auto_creates_stable_draft_once(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "txt2img.workflow.json", api_workflow())
    runtime = CapabilityRuntime()

    first = runtime.scan_workflow_library(context=context(tmp_path))
    second = runtime.scan_workflow_library(context=context(tmp_path))

    assert first["created_draft_presets"][0]["id"] == "auto_txt2img"
    assert second["created_draft_presets"] == []
    draft = yaml.safe_load((tmp_path / "presets" / "auto_txt2img.yaml").read_text(encoding="utf-8"))
    assert draft["status"] == "needs_mapping"
    assert draft["parameters"] == []


def test_allow_preset_file_write_false_reports_missing_without_draft(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "txt2img.workflow.json", api_workflow())

    scan = CapabilityRuntime().scan_workflow_library(context=context(tmp_path, allow_preset_write=False))

    assert scan["missing_preset_workflows"] == ["txt2img.workflow.json"]
    assert scan["created_draft_presets"] == []
    assert not (tmp_path / "presets" / "auto_txt2img.yaml").exists()


def test_workflow_and_preset_dirs_come_from_capability_config(tmp_path: Path) -> None:
    custom = tmp_path / "custom"
    write_json(custom / "wf" / "txt2img.workflow.json", api_workflow())
    ctx = {"capability_config": {"workflows_dir": str(custom / "wf"), "presets_dir": str(custom / "ps")}}

    scan = CapabilityRuntime().scan_workflow_library(context=ctx)

    assert scan["workflows_dir"] == str((custom / "wf").resolve())
    assert scan["presets_dir"] == str((custom / "ps").resolve())
