"""Test transport and client construction."""

from __future__ import annotations

from huawei_esm48100.transports import SerialRtuTransport, TcpRtuTransport

from custom_components.huawei_esm48100.api import (
    create_clients,
    create_transport,
)


def test_create_tcp_transport_and_clients(
    tcp_entry_data: dict[str, object],
) -> None:
    """One TCP transport is shared by every configured slave."""
    transport = create_transport(tcp_entry_data)
    clients = create_clients(transport, tcp_entry_data)

    assert isinstance(transport, TcpRtuTransport)
    assert transport.host == "192.0.2.10"
    assert transport.port == 1145
    assert transport.timeout == 3.0
    assert transport.connect_timeout == 5.0
    assert transport.allow_unsafe_requests is False
    assert [client.slave_address for client in clients] == [0xD6, 0xD7]
    assert all(client.transport is transport for client in clients)
    assert all(client.recovery_timeout == 60.0 for client in clients)
    assert all(client.keepalive_interval == 10.0 for client in clients)


def test_create_serial_transport(
    serial_entry_data: dict[str, object],
) -> None:
    """Serial settings and safe defaults are passed to the protocol layer."""
    transport = create_transport(serial_entry_data)

    assert isinstance(transport, SerialRtuTransport)
    assert transport.port == "COM4"
    assert transport.baudrate == 9600
    assert transport.parity == "N"
    assert transport.stopbits == 1
    assert transport.timeout == 3.0
    assert transport.allow_unsafe_requests is False


def test_controls_must_be_explicitly_enabled(
    tcp_entry_data: dict[str, object],
) -> None:
    """Only explicit opt-in allows the protocol transport to write."""
    data = {**tcp_entry_data, "enable_control_entities": True}

    transport = create_transport(data)

    assert transport.allow_unsafe_requests is True
