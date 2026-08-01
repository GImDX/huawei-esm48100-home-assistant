"""Test user-facing translations for the Huawei ESM-48100 integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.helpers.translation import async_get_translations

from custom_components.huawei_esm48100.const import DOMAIN

ENGLISH_MESSAGE = (
    "The integration is still reloading. "
    "Wait for initialization to finish, then try again."
)
CHINESE_MESSAGE = "集成仍在重新加载。请等待初始化完成后重试。"


def test_translation_files_define_reconfigure_in_progress() -> None:
    """Every translation source defines both abort and form-error text."""
    component_dir = (
        Path(__file__).parents[2]
        / "custom_components"
        / "huawei_esm48100"
    )
    expected = {
        "strings.json": ENGLISH_MESSAGE,
        "translations/en.json": ENGLISH_MESSAGE,
        "translations/zh-Hans.json": CHINESE_MESSAGE,
    }

    for relative_path, message in expected.items():
        document = json.loads(
            (component_dir / relative_path).read_text(encoding="utf-8")
        )
        assert document["config"]["abort"]["reconfigure_in_progress"] == message
        assert document["config"]["error"]["reconfigure_in_progress"] == message


async def test_home_assistant_resolves_reconfigure_abort_translation(
    hass: Any,
) -> None:
    """Home Assistant resolves the abort reason instead of exposing its key."""
    translations = await async_get_translations(
        hass,
        "en",
        "config",
        integrations={DOMAIN},
    )

    assert translations[
        f"component.{DOMAIN}.config.abort.reconfigure_in_progress"
    ] == ENGLISH_MESSAGE
