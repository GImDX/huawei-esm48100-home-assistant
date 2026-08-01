"""Home Assistant runtime test fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from huawei_esm48100 import (
    BatteryConfiguration,
    BatterySnapshot,
    BatteryState,
    ClientDiagnostics,
)
from huawei_esm48100.transports.base import TransportDiagnostics


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: Any,
) -> None:
    """Enable loading integrations from custom_components."""
    del enable_custom_integrations


def make_snapshot(
    slave_address: int,
    *,
    active_alarms: tuple[str, ...] = (),
) -> BatterySnapshot:
    """Build a stable 15-cell snapshot."""
    offset = 0.0 if slave_address == 0xD6 else 0.01
    voltages = tuple(
        round(3.39 + offset + (index % 4) * 0.002, 3)
        for index in range(15)
    )
    temperatures = tuple(
        30 + (index % 3) + (1 if slave_address == 0xD6 else 0)
        for index in range(15)
    )
    return BatterySnapshot(
        slave_address=slave_address,
        bus_voltage_v=53.18 if slave_address == 0xD6 else 53.15,
        pack_voltage_v=round(sum(voltages), 2),
        current_a=0.0,
        state_of_charge=100,
        state_of_health=100,
        highest_cell_temperature_c=max(temperatures),
        lowest_cell_temperature_c=min(temperatures),
        state=BatteryState.CHARGE,
        discharge_ah=1542 if slave_address == 0xD6 else 995,
        discharge_times=109 if slave_address == 0xD6 else 117,
        software_version="V112",
        subsoftware_id=146,
        cell_count=15,
        cell_temperatures_c=temperatures,
        cell_voltages_v=voltages,
        alarm_words=(0, 0, 0, 0, 0),
        active_alarms=active_alarms,
        bar_code=(
            "EX0000000001" if slave_address == 0xD6 else "EX0000000002"
        ),
        electrical_label_text=(
            "[Board Properties]\r\n"
            "BoardType=ESM-48100B1\r\n"
            f"BarCode={'EX0000000001' if slave_address == 0xD6 else 'EX0000000002'}\r\n"
            "Model=ESM-48100B1\r\n"
        ),
    )


def make_configuration() -> BatteryConfiguration:
    """Build verified control values without performing writes."""
    return BatteryConfiguration(
        discharge_limit_coefficient=0.8,
        charge_limit_coefficient=0.7,
        default_charge_limit_coefficient=0.6,
        do1_alarm_action_open=False,
        do2_alarm_action_open=True,
        gyroscope_enabled=None,
        gyroscope_sensitivity=None,
    )


@dataclass(slots=True)
class MockProtocol:
    """One mocked transport and its battery clients."""

    transport: MagicMock
    clients: list[MagicMock]


@pytest.fixture
def mock_protocol() -> MockProtocol:
    """Return a protocol surface that cannot perform real I/O."""
    transport = MagicMock()
    transport.connect = AsyncMock()
    transport.close = AsyncMock()
    transport.timeout = 3.0
    transport.diagnostics = TransportDiagnostics(
        requests=202,
        responses=202,
        reconnects=1,
        last_tx_frame=bytes.fromhex("D7 03 00 22 00 0F B6 32"),
        last_rx_frame=bytes.fromhex("D7 03 02 14 C4 FF 05"),
        last_success_at=datetime(2026, 7, 29, tzinfo=UTC),
    )

    clients: list[MagicMock] = []
    for address in (0xD6, 0xD7):
        client = MagicMock()
        client.slave_address = address
        client.diagnostics = ClientDiagnostics(
            requests=101,
            successful_requests=101,
            wake_attempts=1,
            wake_successes=1,
            last_success_at=datetime(2026, 7, 29, tzinfo=UTC),
        )
        client.ensure_awake = AsyncMock(return_value=True)
        client.read_snapshot = AsyncMock(
            return_value=make_snapshot(
                address,
                active_alarms=(
                    ("cell_undervoltage",) if address == 0xD7 else ()
                ),
            )
        )
        client.read_configuration = AsyncMock(
            return_value=make_configuration()
        )
        client.write_control_setting = AsyncMock()
        clients.append(client)

    return MockProtocol(transport=transport, clients=clients)


@pytest.fixture
def tcp_entry_data() -> dict[str, Any]:
    """Return the tested transparent-TCP configuration."""
    return {
        "connection_type": "tcp",
        "host": "192.0.2.10",
        "port": 1145,
        "connect_timeout": 5.0,
        "slave_addresses": [0xD6, 0xD7],
        "response_timeout": 3.0,
        "enable_control_entities": False,
    }


@pytest.fixture
def serial_entry_data() -> dict[str, Any]:
    """Return a local serial configuration."""
    return {
        "connection_type": "serial",
        "serial_port": "COM4",
        "baudrate": 9600,
        "parity": "N",
        "stopbits": 1,
        "slave_addresses": [0xD6, 0xD7],
        "response_timeout": 3.0,
        "enable_control_entities": False,
    }


@pytest.fixture
def protocol_factory(mock_protocol: MockProtocol) -> SimpleNamespace:
    """Return patched factory callables shared by tests."""
    return SimpleNamespace(
        create_transport=MagicMock(return_value=mock_protocol.transport),
        create_clients=MagicMock(return_value=mock_protocol.clients),
    )
