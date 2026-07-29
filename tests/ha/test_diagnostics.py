"""Test Home Assistant diagnostics output."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.huawei_esm48100.const import DOMAIN
from custom_components.huawei_esm48100.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_include_bus_and_battery_state(
    hass: Any,
    tcp_entry_data: dict[str, Any],
    mock_protocol: Any,
    protocol_factory: Any,
) -> None:
    """Diagnostics expose decoded data and serializable protocol counters."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="TCP 192.0.2.10:1145",
        data=tcp_entry_data,
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.huawei_esm48100.create_transport",
            protocol_factory.create_transport,
        ),
        patch(
            "custom_components.huawei_esm48100.create_clients",
            protocol_factory.create_clients,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["config"] == tcp_entry_data
    assert result["last_update_success"] is True
    assert result["unavailable_addresses"] == []
    assert result["battery_errors"] == {}
    assert result["transport"]["requests"] == 202
    assert result["transport"]["responses"] == 202
    assert result["transport"]["last_tx_frame"] == "d7 03 00 22 00 0f b6 32"
    assert result["clients"]["0xD6"]["successful_requests"] == 101
    assert result["batteries"]["0xD6"]["bus_voltage_v"] == 53.18
    assert result["batteries"]["0xD7"]["active_alarms"] == (
        "cell_undervoltage",
    )
