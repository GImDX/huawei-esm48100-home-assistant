"""Create protocol clients from a Home Assistant config entry."""

from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_HOST, CONF_PORT

from huawei_esm48100 import EsmClient
from huawei_esm48100.transports import (
    RtuTransport,
    SerialRtuTransport,
    TcpRtuTransport,
)

from .const import (
    CONF_BAUDRATE,
    CONF_CONNECT_TIMEOUT,
    CONF_CONNECTION_TYPE,
    CONF_ENABLE_CONTROLS,
    CONF_KEEPALIVE_INTERVAL,
    CONF_PARITY,
    CONF_RESPONSE_TIMEOUT,
    CONF_SERIAL_PORT,
    CONF_SLAVE_ADDRESSES,
    CONF_STOPBITS,
    CONNECTION_SERIAL,
    DEFAULT_BAUDRATE,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_ENABLE_CONTROLS,
    DEFAULT_KEEPALIVE_INTERVAL,
    DEFAULT_PARITY,
    DEFAULT_RECOVERY_TIMEOUT,
    DEFAULT_RESPONSE_TIMEOUT,
    DEFAULT_STOPBITS,
)


def create_transport(data: Mapping[str, Any]) -> RtuTransport:
    """Create one transport representing one RS485 bus."""
    timeout = float(data.get(CONF_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT))
    connect_timeout = float(
        data.get(CONF_CONNECT_TIMEOUT, DEFAULT_CONNECT_TIMEOUT)
    )
    allow_controls = bool(
        data.get(CONF_ENABLE_CONTROLS, DEFAULT_ENABLE_CONTROLS)
    )
    if data[CONF_CONNECTION_TYPE] == CONNECTION_SERIAL:
        return SerialRtuTransport(
            str(data[CONF_SERIAL_PORT]),
            baudrate=int(data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)),
            parity=str(data.get(CONF_PARITY, DEFAULT_PARITY)),
            stopbits=float(data.get(CONF_STOPBITS, DEFAULT_STOPBITS)),
            timeout=timeout,
            connect_timeout=connect_timeout,
            allow_unsafe_requests=allow_controls,
        )
    return TcpRtuTransport(
        str(data[CONF_HOST]),
        int(data[CONF_PORT]),
        timeout=timeout,
        connect_timeout=connect_timeout,
        allow_unsafe_requests=allow_controls,
    )


def create_clients(
    transport: RtuTransport,
    data: Mapping[str, Any],
) -> list[EsmClient]:
    """Create one client per configured battery address."""
    return [
        EsmClient(
            transport,
            slave_address,
            recovery_timeout=DEFAULT_RECOVERY_TIMEOUT,
            keepalive_interval=float(
                data.get(
                    CONF_KEEPALIVE_INTERVAL,
                    DEFAULT_KEEPALIVE_INTERVAL,
                )
            ),
        )
        for slave_address in data[CONF_SLAVE_ADDRESSES]
    ]
