"""Test config entry setup, polling, recovery, and unloading."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from huawei_esm48100 import ControlSetting, EsmConnectionError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.huawei_esm48100 import async_unload_entry
from custom_components.huawei_esm48100.const import DOMAIN


def _entries_for_config_entry(hass: Any, entry_id: str) -> list[Any]:
    registry = er.async_get(hass)
    return list(er.async_entries_for_config_entry(registry, entry_id))


async def _setup_entry(
    hass: Any,
    data: dict[str, Any],
    protocol_factory: Any,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="TCP 192.0.2.10:1145",
        data=data,
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
    return entry


async def test_setup_creates_two_devices_and_read_only_entities(
    hass: Any,
    tcp_entry_data: dict[str, Any],
    mock_protocol: Any,
    protocol_factory: Any,
) -> None:
    """Two 15-cell batteries create devices without control entities."""
    entry = await _setup_entry(hass, tcp_entry_data, protocol_factory)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.transport is mock_protocol.transport
    assert set(entry.runtime_data.coordinator.data.batteries) == {0xD6, 0xD7}
    entries = _entries_for_config_entry(hass, entry.entry_id)
    assert len(entries) == 96
    assert sum(item.entity_id.startswith("sensor.") for item in entries) == 94
    assert sum(
        item.entity_id.startswith("binary_sensor.") for item in entries
    ) == 2
    assert not any(item.entity_id.startswith("number.") for item in entries)
    assert not any(item.entity_id.startswith("switch.") for item in entries)

    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass),
        entry.entry_id,
    )
    assert len(devices) == 2
    assert {device.name for device in devices} == {
        "Huawei ESM-48100 @ 0xD6",
        "Huawei ESM-48100 @ 0xD7",
    }

    bus_voltage_entry = next(
        item for item in entries if item.unique_id.endswith("_d6_bus_voltage")
    )
    alarm_entry = next(
        item for item in entries if item.unique_id.endswith("_d7_active_alarm")
    )
    bar_code_entry = next(
        item for item in entries if item.unique_id.endswith("_d6_bar_code")
    )
    label_entry = next(
        item
        for item in entries
        if item.unique_id.endswith("_d6_electrical_label")
    )
    assert hass.states.get(bus_voltage_entry.entity_id).state == "53.18"
    assert hass.states.get(alarm_entry.entity_id).state == "on"
    assert hass.states.get(bar_code_entry.entity_id).state == "EX0000000001"
    label_state = hass.states.get(label_entry.entity_id)
    assert label_state.state == "loaded"
    assert "BarCode=EX0000000001" in label_state.attributes["text"]

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    mock_protocol.transport.close.assert_awaited_once()


async def test_poll_failure_only_marks_failed_battery_unavailable(
    hass: Any,
    tcp_entry_data: dict[str, Any],
    mock_protocol: Any,
    protocol_factory: Any,
) -> None:
    """One failed slave does not stop healthy batteries from updating."""
    entry = await _setup_entry(hass, tcp_entry_data, protocol_factory)
    entries = _entries_for_config_entry(hass, entry.entry_id)
    d6_bus_voltage = next(
        item for item in entries if item.unique_id.endswith("_d6_bus_voltage")
    )
    d7_bus_voltage = next(
        item for item in entries if item.unique_id.endswith("_d7_bus_voltage")
    )
    coordinator = entry.runtime_data.coordinator

    mock_protocol.clients[1].read_snapshot.side_effect = EsmConnectionError(
        "offline"
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is True
    assert coordinator.data.unavailable_addresses == frozenset({0xD7})
    assert coordinator.data.battery_errors == {
        0xD7: "EsmConnectionError: offline"
    }
    assert hass.states.get(d6_bus_voltage.entity_id).state == "53.18"
    assert hass.states.get(d7_bus_voltage.entity_id).state == "unavailable"

    mock_protocol.clients[1].read_snapshot.side_effect = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is True
    assert coordinator.data.unavailable_addresses == frozenset()
    assert coordinator.data.battery_errors == {}
    assert hass.states.get(d6_bus_voltage.entity_id).state == "53.18"
    assert hass.states.get(d7_bus_voltage.entity_id).state == "53.15"


async def test_failed_first_refresh_closes_transport(
    hass: Any,
    tcp_entry_data: dict[str, Any],
    mock_protocol: Any,
    protocol_factory: Any,
) -> None:
    """An unavailable slave prevents setup and releases the shared transport."""
    mock_protocol.clients[1].read_snapshot.side_effect = EsmConnectionError(
        "offline"
    )

    entry = await _setup_entry(hass, tcp_entry_data, protocol_factory)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    mock_protocol.transport.close.assert_awaited_once()


async def test_explicit_controls_create_entities_without_writing(
    hass: Any,
    tcp_entry_data: dict[str, Any],
    mock_protocol: Any,
    protocol_factory: Any,
) -> None:
    """Opt-in creates allowlisted controls but setup performs no writes."""
    data = {**tcp_entry_data, "enable_control_entities": True}

    entry = await _setup_entry(hass, data, protocol_factory)

    entries = _entries_for_config_entry(hass, entry.entry_id)
    assert len(entries) == 106
    assert sum(item.entity_id.startswith("number.") for item in entries) == 6
    assert sum(item.entity_id.startswith("switch.") for item in entries) == 4
    for client in mock_protocol.clients:
        client.read_configuration.assert_awaited_once()
        client.write_control_setting.assert_not_awaited()

    charge_number = next(
        item
        for item in entries
        if item.unique_id.endswith("_d6_charge_limit_coefficient")
    )
    do2_switch = next(
        item
        for item in entries
        if item.unique_id.endswith("_d6_do2_alarm_action")
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": charge_number.entity_id, "value": 0.75},
        blocking=True,
    )
    mock_protocol.clients[0].write_control_setting.assert_awaited_with(
        ControlSetting.CHARGE_LIMIT_COEFFICIENT,
        0.75,
    )

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": do2_switch.entity_id},
        blocking=True,
    )
    mock_protocol.clients[0].write_control_setting.assert_awaited_with(
        ControlSetting.DO2_ALARM_ACTION_OPEN,
        True,
    )
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": do2_switch.entity_id},
        blocking=True,
    )
    mock_protocol.clients[0].write_control_setting.assert_awaited_with(
        ControlSetting.DO2_ALARM_ACTION_OPEN,
        False,
    )


async def test_unload_failure_keeps_transport_open(
    hass: Any,
    tcp_entry_data: dict[str, Any],
    mock_protocol: Any,
    protocol_factory: Any,
) -> None:
    """A platform unload failure must not close a still-active transport."""
    entry = await _setup_entry(hass, tcp_entry_data, protocol_factory)
    unload_platforms = AsyncMock(return_value=False)

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        unload_platforms,
    ):
        assert await async_unload_entry(hass, entry) is False

    mock_protocol.transport.close.assert_not_awaited()
