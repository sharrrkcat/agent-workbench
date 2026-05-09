from pathlib import Path

import pytest

from ai_workbench.core.config_schema import (
    MASKED_SECRET,
    ConfigValidationError,
    clear_empty_enum_overrides,
    mask_config,
    merge_secret_patch,
    parse_config_schema,
    resolve_config,
    validate_user_config,
)
from ai_workbench.core.manifest_loader import load_capability_manifest


ROOT = Path(__file__).resolve().parents[1]


def test_config_schema_parses_supported_field_types() -> None:
    schema = parse_config_schema(
        [
            {"name": "name", "type": "string", "label": "Name"},
            {"name": "body", "type": "text", "label": "Body"},
            {"name": "count", "type": "integer", "label": "Count"},
            {"name": "ratio", "type": "float", "label": "Ratio"},
            {"name": "enabled", "type": "boolean", "label": "Enabled"},
            {"name": "mode", "type": "enum", "label": "Mode", "options": ["a", "b"]},
            {"name": "payload", "type": "json", "label": "Payload"},
            {"name": "token", "type": "string", "label": "Token", "secret": True},
        ]
    )

    assert [field.type for field in schema] == ["string", "text", "integer", "float", "boolean", "enum", "json", "string"]
    assert schema[-1].secret is True


def test_config_resolver_merges_defaults_and_user_config() -> None:
    schema = parse_config_schema(
        [
            {"name": "base_url", "type": "string", "label": "Base URL", "default": "http://localhost:1234/v1"},
            {"name": "timeout", "type": "float", "label": "Timeout", "default": 60},
        ]
    )

    assert resolve_config(schema, {"timeout": 10}) == {"base_url": "http://localhost:1234/v1", "timeout": 10.0}


def test_config_validation_rejects_unknown_field() -> None:
    schema = parse_config_schema([{"name": "known", "type": "string", "label": "Known"}])

    with pytest.raises(ConfigValidationError) as exc:
        validate_user_config(schema, {"unknown": "value"})

    assert exc.value.code == "UNKNOWN_CONFIG_FIELD"


def test_config_validation_rejects_missing_required_field() -> None:
    schema = parse_config_schema([{"name": "required", "type": "string", "label": "Required", "required": True}])

    with pytest.raises(ConfigValidationError) as exc:
        resolve_config(schema, {})

    assert exc.value.code == "MISSING_REQUIRED_CONFIG"


def test_config_validation_rejects_invalid_enum_option() -> None:
    schema = parse_config_schema([{"name": "mode", "type": "enum", "label": "Mode", "options": ["a"]}])

    with pytest.raises(ConfigValidationError) as exc:
        validate_user_config(schema, {"mode": "b"})

    assert exc.value.code == "INVALID_CONFIG_OPTION"


def test_config_validation_rejects_null_enum_option() -> None:
    schema = parse_config_schema([{"name": "mode", "type": "enum", "label": "Mode", "options": ["a"], "default": "a"}])

    with pytest.raises(ConfigValidationError) as exc:
        validate_user_config(schema, {"mode": None})

    assert exc.value.code == "INVALID_CONFIG_TYPE"


def test_config_resolver_treats_empty_enum_override_as_manifest_default() -> None:
    schema = parse_config_schema([{"name": "mode", "type": "enum", "label": "Mode", "options": ["a", "b"], "default": "a"}])

    assert clear_empty_enum_overrides(schema, {"mode": None}) == {}
    assert clear_empty_enum_overrides(schema, {"mode": ""}) == {}
    assert resolve_config(schema, {"mode": None}) == {"mode": "a"}
    assert resolve_config(schema, {"mode": ""}) == {"mode": "a"}


def test_config_validation_rejects_invalid_integer_and_boolean_types() -> None:
    schema = parse_config_schema(
        [
            {"name": "count", "type": "integer", "label": "Count"},
            {"name": "enabled", "type": "boolean", "label": "Enabled"},
        ]
    )

    with pytest.raises(ConfigValidationError) as integer_exc:
        validate_user_config(schema, {"count": "1"})
    with pytest.raises(ConfigValidationError) as boolean_exc:
        validate_user_config(schema, {"enabled": "true"})

    assert integer_exc.value.code == "INVALID_CONFIG_TYPE"
    assert boolean_exc.value.code == "INVALID_CONFIG_TYPE"


def test_config_validation_rejects_numeric_values_outside_bounds() -> None:
    schema = parse_config_schema(
        [
            {"name": "small", "type": "float", "label": "Small", "minimum": 0.1, "maximum": 1},
            {"name": "count", "type": "integer", "label": "Count", "minimum": 1, "maximum": 3},
        ]
    )

    with pytest.raises(ConfigValidationError) as low_exc:
        validate_user_config(schema, {"small": 0.01})
    with pytest.raises(ConfigValidationError) as high_exc:
        validate_user_config(schema, {"count": 4})

    assert low_exc.value.code == "INVALID_CONFIG_VALUE"
    assert high_exc.value.code == "INVALID_CONFIG_VALUE"


def test_json_config_validation_preserves_default_container_shape() -> None:
    schema = parse_config_schema(
        [
            {"name": "items", "type": "json", "label": "Items", "default": []},
            {"name": "options", "type": "json", "label": "Options", "default": {}},
        ]
    )

    with pytest.raises(ConfigValidationError) as array_exc:
        validate_user_config(schema, {"items": {"not": "an array"}})
    with pytest.raises(ConfigValidationError) as object_exc:
        validate_user_config(schema, {"options": ["not", "an", "object"]})

    assert array_exc.value.code == "INVALID_CONFIG_TYPE"
    assert object_exc.value.code == "INVALID_CONFIG_TYPE"


def test_secret_masking_and_patch_preserve_mask() -> None:
    schema = parse_config_schema([{"name": "api_key", "type": "string", "label": "API key", "secret": True}])

    assert mask_config(schema, {"api_key": "secret"}) == {"api_key": MASKED_SECRET}
    assert merge_secret_patch(schema, {"api_key": "secret"}, {"api_key": MASKED_SECRET}) == {"api_key": "secret"}
    assert merge_secret_patch(schema, {"api_key": "secret"}, {}) == {"api_key": "secret"}
    assert merge_secret_patch(schema, {"api_key": "secret"}, {"api_key": "new"}) == {"api_key": "new"}


def test_llm_capability_declares_config_schema() -> None:
    capability = load_capability_manifest(ROOT / "capabilities" / "llm" / "capability.yaml")

    names = {field.name for field in capability.config_schema}
    assert {"base_url", "api_key", "model", "timeout"}.issubset(names)
    assert next(field for field in capability.config_schema if field.name == "api_key").secret is True
