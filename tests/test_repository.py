"""Structural tests for the HACS repository."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "huawei_esm48100"


def test_hacs_repository_has_one_integration() -> None:
    """HACS manages exactly one integration directory per repository."""
    integrations = [
        path for path in (ROOT / "custom_components").iterdir() if path.is_dir()
    ]
    assert integrations == [INTEGRATION]


def test_manifest_has_required_custom_integration_keys() -> None:
    """The manifest includes fields required by HACS and Home Assistant."""
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    required = {
        "codeowners",
        "config_flow",
        "documentation",
        "domain",
        "integration_type",
        "iot_class",
        "issue_tracker",
        "name",
        "requirements",
        "version",
    }
    assert required <= manifest.keys()
    assert manifest["domain"] == INTEGRATION.name
    assert manifest["config_flow"] is True


def test_translation_files_have_same_shape_as_strings() -> None:
    """Translations must retain every key from the source strings file."""

    def shape(value: object) -> object:
        if isinstance(value, dict):
            return {key: shape(child) for key, child in value.items()}
        return None

    source = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    expected_shape = shape(source)
    for translation in (INTEGRATION / "translations").glob("*.json"):
        translated = json.loads(translation.read_text(encoding="utf-8"))
        assert shape(translated) == expected_shape


def test_advanced_controls_are_default_off() -> None:
    """Control platforms exist but require an explicit opt-in."""
    const_source = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    api_source = (INTEGRATION / "api.py").read_text(encoding="utf-8")
    assert "DEFAULT_ENABLE_CONTROLS = False" in const_source
    assert "allow_unsafe_requests=allow_controls" in api_source
    assert (INTEGRATION / "number.py").is_file()
    assert (INTEGRATION / "switch.py").is_file()
