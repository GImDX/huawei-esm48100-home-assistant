"""Tests for configuration helpers."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_helpers() -> ModuleType:
    """Load the pure helper module without importing Home Assistant."""
    path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "huawei_esm48100"
        / "helpers.py"
    )
    spec = importlib.util.spec_from_file_location("huawei_esm48100_helpers", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPERS = _load_helpers()
parse_slave_addresses = HELPERS.parse_slave_addresses
format_slave_addresses = HELPERS.format_slave_addresses


def test_parse_slave_addresses() -> None:
    assert parse_slave_addresses("0xD6, 215") == [214, 215]
    assert format_slave_addresses([214, 215]) == "0xD6, 0xD7"


@pytest.mark.parametrize("value", ["", "0", "248", "0xD6, 214", "hello"])
def test_reject_invalid_slave_addresses(value: str) -> None:
    with pytest.raises(ValueError):
        parse_slave_addresses(value)
