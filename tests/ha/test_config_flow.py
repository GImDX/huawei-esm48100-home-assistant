"""Test the Huawei ESM-48100 config and options flows."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from huawei_esm48100 import DEFAULT_SCAN_ADDRESSES, EsmConnectionError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.huawei_esm48100.config_flow import _async_scan_bus
from custom_components.huawei_esm48100.const import DOMAIN


def _connection_input(connection_type: str) -> dict[str, Any]:
    """Return connection-only input for one transport."""
    if connection_type == "tcp":
        return {
            "host": "192.0.2.10",
            "port": 1145,
            "connect_timeout": 5.0,
            "response_timeout": 3.0,
        }
    return {
        "serial_port": "COM4",
        "baudrate": 9600,
        "parity": "N",
        "stopbits": 1,
        "response_timeout": 3.0,
    }


async def _open_transport_form(
    hass: Any,
    connection_type: str,
) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"connection_type": connection_type},
    )


async def _open_address_method(
    hass: Any,
    connection_type: str,
) -> dict[str, Any]:
    """Submit transport details and return the address method menu."""
    form = await _open_transport_form(hass, connection_type)
    return await hass.config_entries.flow.async_configure(
        form["flow_id"],
        _connection_input(connection_type),
    )


async def _open_manual_form(
    hass: Any,
    connection_type: str,
) -> dict[str, Any]:
    """Open manual address entry after configuring a transport."""
    menu = await _open_address_method(hass, connection_type)
    assert menu["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        menu["flow_id"],
        {"next_step_id": "manual"},
    )


@pytest.mark.parametrize(
    ("connection_type", "step_id"),
    [("serial", "serial"), ("tcp", "tcp")],
)
async def test_select_transport_form(
    hass: Any,
    connection_type: str,
    step_id: str,
) -> None:
    """The first step routes to the selected transport form."""
    result = await _open_transport_form(hass, connection_type)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == step_id
    assert result["errors"] == {}


@pytest.mark.parametrize("connection_type", ["serial", "tcp"])
async def test_connection_details_open_address_method_menu(
    hass: Any,
    connection_type: str,
) -> None:
    """Configured transports offer scan and manual address entry."""
    result = await _open_address_method(hass, connection_type)

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["scan", "manual"]


@pytest.mark.parametrize("connection_type", ["serial", "tcp"])
async def test_manual_form_is_frontend_serializable(
    hass: Any,
    connection_type: str,
) -> None:
    """Manual entry exposes a text selector instead of a custom validator."""
    form = await _open_manual_form(hass, connection_type)

    assert form["type"] is FlowResultType.FORM
    field = next(iter(form["data_schema"].schema.values()))
    assert field.__class__.__name__ == "TextSelector"


@pytest.mark.parametrize("connection_type", ["serial", "tcp"])
async def test_create_entry_validates_every_slave(
    hass: Any,
    mock_protocol: Any,
    protocol_factory: Any,
    connection_type: str,
) -> None:
    """Successful configuration wakes every configured slave before saving."""
    with (
        patch(
            "custom_components.huawei_esm48100.config_flow.create_transport",
            protocol_factory.create_transport,
        ),
        patch(
            "custom_components.huawei_esm48100.config_flow.create_clients",
            protocol_factory.create_clients,
        ),
        patch(
            "custom_components.huawei_esm48100.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
    ):
        form = await _open_manual_form(hass, connection_type)
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"],
            {"slave_addresses": "0xD6, 0xD7"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["slave_addresses"] == [0xD6, 0xD7]
    for key, value in _connection_input(connection_type).items():
        assert result["data"][key] == value
    for client in mock_protocol.clients:
        client.ensure_awake.assert_awaited_once_with(force=True)
    mock_protocol.transport.close.assert_awaited_once()


async def test_manual_form_reports_invalid_addresses(hass: Any) -> None:
    """Invalid manual address text remains on the form."""
    form = await _open_manual_form(hass, "tcp")
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        {"slave_addresses": "0xD6, 0xD6"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"slave_addresses": "invalid_addresses"}


async def test_scan_bus_runs_every_address_for_every_round(
    mock_protocol: Any,
    protocol_factory: Any,
) -> None:
    """Responding addresses remain in all fixed scan rounds."""
    progress = MagicMock()
    mock_protocol.clients[0].read_holding_registers = AsyncMock(
        side_effect=[
            EsmConnectionError("sleeping"),
            (0x14C6,),
            (0x14C6,),
        ]
    )
    mock_protocol.clients[1].read_holding_registers = AsyncMock(
        return_value=(0x14C4,)
    )

    with (
        patch(
            "custom_components.huawei_esm48100.config_flow.create_transport",
            protocol_factory.create_transport,
        ),
        patch(
            "custom_components.huawei_esm48100.config_flow.create_clients",
            protocol_factory.create_clients,
        ),
    ):
        found = await _async_scan_bus(
            _connection_input("tcp"),
            [0xD6, 0xD7],
            3,
            progress,
        )

    assert found == [0xD6, 0xD7]
    for client in mock_protocol.clients:
        assert client.read_holding_registers.await_count == 3
        client.read_holding_registers.assert_awaited_with(
            0x0000,
            1,
            retries=0,
        )
    scan_data = protocol_factory.create_transport.call_args.args[0]
    assert scan_data["response_timeout"] == 0.3
    assert scan_data["enable_control_entities"] is False
    progress.assert_called_with(1.0)
    mock_protocol.transport.close.assert_awaited_once()


async def test_scan_defaults_match_huawei_capture(hass: Any) -> None:
    """The form defaults to Huawei's two 8-address blocks and 14 rounds."""
    menu = await _open_address_method(hass, "tcp")
    form = await hass.config_entries.flow.async_configure(
        menu["flow_id"],
        {"next_step_id": "scan"},
    )
    defaults = form["data_schema"]({})

    assert defaults["scan_rounds"] == 14
    assert defaults["scan_addresses"] == ", ".join(
        f"0x{address:02X}" for address in DEFAULT_SCAN_ADDRESSES
    )


async def test_scan_discovers_and_selects_multiple_batteries(
    hass: Any,
) -> None:
    """The progress flow lists responders and saves selected addresses."""
    scan_bus = AsyncMock(return_value=[0xD6, 0xD7])
    addresses = "0xD6, 0xD7, 0xE0"

    with (
        patch(
            "custom_components.huawei_esm48100.config_flow._async_scan_bus",
            scan_bus,
        ),
        patch(
            "custom_components.huawei_esm48100.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
    ):
        menu = await _open_address_method(hass, "tcp")
        scan_form = await hass.config_entries.flow.async_configure(
            menu["flow_id"],
            {"next_step_id": "scan"},
        )
        progress = await hass.config_entries.flow.async_configure(
            scan_form["flow_id"],
            {"scan_addresses": addresses, "scan_rounds": 14},
        )
        await hass.async_block_till_done()
        result_form = await hass.config_entries.flow.async_configure(
            progress["flow_id"]
        )
        result = await hass.config_entries.flow.async_configure(
            result_form["flow_id"],
            {"slave_addresses": [str(0xD6), str(0xD7)]},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["slave_addresses"] == [0xD6, 0xD7]
    assert scan_bus.call_args.args[1] == [0xD6, 0xD7, 0xE0]
    assert scan_bus.call_args.args[2] == 14


async def test_scan_reports_when_no_batteries_respond(hass: Any) -> None:
    """An empty discovery result returns to scan options with an error."""
    with patch(
        "custom_components.huawei_esm48100.config_flow._async_scan_bus",
        new=AsyncMock(return_value=[]),
    ):
        menu = await _open_address_method(hass, "tcp")
        scan_form = await hass.config_entries.flow.async_configure(
            menu["flow_id"],
            {"next_step_id": "scan"},
        )
        progress = await hass.config_entries.flow.async_configure(
            scan_form["flow_id"],
            {"scan_addresses": "0xD6, 0xD7", "scan_rounds": 2},
        )
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(
            progress["flow_id"]
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_devices_found"}


@pytest.mark.parametrize("connection_type", ["serial", "tcp"])
@pytest.mark.parametrize(
    ("error", "expected_error"),
    [
        (EsmConnectionError("offline"), "cannot_connect"),
        (RuntimeError("unexpected"), "unknown"),
    ],
)
async def test_connection_errors_are_reported(
    hass: Any,
    mock_protocol: Any,
    protocol_factory: Any,
    connection_type: str,
    error: Exception,
    expected_error: str,
) -> None:
    """Connection failures remain on the manual address form."""
    mock_protocol.clients[0].ensure_awake.side_effect = error
    with (
        patch(
            "custom_components.huawei_esm48100.config_flow.create_transport",
            protocol_factory.create_transport,
        ),
        patch(
            "custom_components.huawei_esm48100.config_flow.create_clients",
            protocol_factory.create_clients,
        ),
    ):
        form = await _open_manual_form(hass, connection_type)
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"],
            {"slave_addresses": "0xD6, 0xD7"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}
    mock_protocol.transport.close.assert_awaited_once()


@pytest.mark.parametrize("connection_type", ["serial", "tcp"])
async def test_duplicate_bus_is_rejected(
    hass: Any,
    tcp_entry_data: dict[str, Any],
    serial_entry_data: dict[str, Any],
    connection_type: str,
) -> None:
    """The same physical bus cannot be configured twice."""
    data = tcp_entry_data if connection_type == "tcp" else serial_entry_data
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="Existing bus",
        data=data,
    )
    existing.add_to_hass(hass)

    form = await _open_transport_form(hass, connection_type)
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        _connection_input(connection_type),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_updates_existing_entry(
    hass: Any,
    tcp_entry_data: dict[str, Any],
    protocol_factory: Any,
) -> None:
    """Reconfiguration updates and reloads the existing entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Existing bus",
        data=tcp_entry_data,
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.huawei_esm48100.config_flow.create_transport",
            protocol_factory.create_transport,
        ),
        patch(
            "custom_components.huawei_esm48100.config_flow.create_clients",
            protocol_factory.create_clients,
        ),
        patch.object(
            hass.config_entries,
            "async_reload",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        transport_form = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"connection_type": "tcp"},
        )
        menu = await hass.config_entries.flow.async_configure(
            transport_form["flow_id"],
            {
                "host": "192.0.2.11",
                "port": 1146,
                "connect_timeout": 4.0,
                "response_timeout": 1.0,
            },
        )
        manual = await hass.config_entries.flow.async_configure(
            menu["flow_id"],
            {"next_step_id": "manual"},
        )
        result = await hass.config_entries.flow.async_configure(
            manual["flow_id"],
            {"slave_addresses": "0xD6"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["host"] == "192.0.2.11"
    assert entry.data["port"] == 1146
    assert entry.data["slave_addresses"] == [0xD6]
    assert entry.title == "TCP 192.0.2.11:1146"


async def test_reconfigure_pauses_loaded_entry_during_validation(
    hass: Any,
    tcp_entry_data: dict[str, Any],
    protocol_factory: Any,
) -> None:
    """Manual validation must not compete with the active bus transport."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Existing bus",
        data=tcp_entry_data,
    )
    entry.add_to_hass(hass)
    validation_states: list[ConfigEntryState] = []

    async def validate_while_stopped(data: dict[str, Any]) -> None:
        del data
        validation_states.append(entry.state)

    with (
        patch(
            "custom_components.huawei_esm48100.create_transport",
            protocol_factory.create_transport,
        ),
        patch(
            "custom_components.huawei_esm48100.create_clients",
            protocol_factory.create_clients,
        ),
        patch(
            "custom_components.huawei_esm48100.config_flow._async_validate_connection",
            side_effect=validate_while_stopped,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        transport_form = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"connection_type": "tcp"},
        )
        menu = await hass.config_entries.flow.async_configure(
            transport_form["flow_id"],
            _connection_input("tcp"),
        )
        manual = await hass.config_entries.flow.async_configure(
            menu["flow_id"],
            {"next_step_id": "manual"},
        )
        result = await hass.config_entries.flow.async_configure(
            manual["flow_id"],
            {"slave_addresses": "0xD6, 0xD7"},
        )
        await hass.async_block_till_done()

    assert validation_states == [ConfigEntryState.NOT_LOADED]
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.state is ConfigEntryState.LOADED


async def test_reconfigure_pauses_loaded_entry_during_scan(
    hass: Any,
    tcp_entry_data: dict[str, Any],
    protocol_factory: Any,
) -> None:
    """A reconfiguration scan must have exclusive access to the bus."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Existing bus",
        data=tcp_entry_data,
    )
    entry.add_to_hass(hass)
    scan_states: list[ConfigEntryState] = []

    async def scan_while_stopped(
        data: dict[str, Any],
        addresses: list[int],
        rounds: int,
        progress_callback: Any,
    ) -> list[int]:
        del data, rounds, progress_callback
        scan_states.append(entry.state)
        return addresses

    with (
        patch(
            "custom_components.huawei_esm48100.create_transport",
            protocol_factory.create_transport,
        ),
        patch(
            "custom_components.huawei_esm48100.create_clients",
            protocol_factory.create_clients,
        ),
        patch(
            "custom_components.huawei_esm48100.config_flow._async_scan_bus",
            side_effect=scan_while_stopped,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        transport_form = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"connection_type": "tcp"},
        )
        menu = await hass.config_entries.flow.async_configure(
            transport_form["flow_id"],
            _connection_input("tcp"),
        )
        scan = await hass.config_entries.flow.async_configure(
            menu["flow_id"],
            {"next_step_id": "scan"},
        )
        progress = await hass.config_entries.flow.async_configure(
            scan["flow_id"],
            {"scan_addresses": "0xD6, 0xD7", "scan_rounds": 2},
        )
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(progress["flow_id"])

    assert scan_states == [ConfigEntryState.NOT_LOADED]
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scan_result"
    assert entry.state is ConfigEntryState.LOADED


async def test_options_update_runtime_intervals(
    hass: Any,
    tcp_entry_data: dict[str, Any],
) -> None:
    """Options expose collection, keepalive, and controls."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Existing bus",
        data=tcp_entry_data,
    )
    entry.add_to_hass(hass)
    with patch.object(
        hass.config_entries,
        "async_reload",
        new=AsyncMock(return_value=True),
    ):
        form = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            form["flow_id"],
            {
                "update_interval": 60,
                "keepalive_interval": 10.0,
                "enable_control_entities": True,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "update_interval": 60,
        "keepalive_interval": 10.0,
        "enable_control_entities": True,
    }
