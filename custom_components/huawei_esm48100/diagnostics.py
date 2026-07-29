"""Diagnostics support for Huawei ESM-48100."""

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import HuaweiEsm48100ConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: HuaweiEsm48100ConfigEntry,
) -> dict[str, Any]:
    """Return config and decoded poll data."""
    del hass
    snapshot = entry.runtime_data.coordinator.data
    transport_diagnostics = entry.runtime_data.transport.diagnostics
    return {
        "config": dict(entry.data),
        "last_update_success": entry.runtime_data.coordinator.last_update_success,
        "last_success_at": snapshot.last_success_at.isoformat(),
        "response_time_ms": round(snapshot.response_time_ms, 2),
        "unavailable_addresses": [
            f"0x{address:02X}"
            for address in sorted(snapshot.unavailable_addresses)
        ],
        "battery_errors": {
            f"0x{address:02X}": error
            for address, error in snapshot.battery_errors.items()
        },
        "transport": {
            **asdict(transport_diagnostics),
            "last_tx_frame": (
                None
                if transport_diagnostics.last_tx_frame is None
                else transport_diagnostics.last_tx_frame.hex(" ")
            ),
            "last_rx_frame": (
                None
                if transport_diagnostics.last_rx_frame is None
                else transport_diagnostics.last_rx_frame.hex(" ")
            ),
            "last_success_at": (
                None
                if transport_diagnostics.last_success_at is None
                else transport_diagnostics.last_success_at.isoformat()
            ),
        },
        "clients": {
            f"0x{client.slave_address:02X}": {
                **asdict(client.diagnostics),
                "last_success_at": (
                    None
                    if client.diagnostics.last_success_at is None
                    else client.diagnostics.last_success_at.isoformat()
                ),
            }
            for client in entry.runtime_data.coordinator.clients
        },
        "batteries": {
            f"0x{slave_address:02X}": {
                "bus_voltage_v": battery.bus_voltage_v,
                "pack_voltage_v": battery.pack_voltage_v,
                "current_a": battery.current_a,
                "state_of_charge": battery.state_of_charge,
                "state_of_health": battery.state_of_health,
                "state": battery.state,
                "cell_count": battery.cell_count,
                "cell_temperatures_c": battery.cell_temperatures_c,
                "cell_voltages_v": battery.cell_voltages_v,
                "alarm_words": [
                    f"0x{value:04X}" for value in battery.alarm_words
                ],
                "active_alarms": battery.active_alarms,
            }
            for slave_address, battery in snapshot.batteries.items()
        },
    }
