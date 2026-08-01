"""Config and options flows for Huawei ESM-48100."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector

from huawei_esm48100 import (
    DEFAULT_SCAN_ADDRESSES,
    EsmConnectionError,
    EsmError,
)
from huawei_esm48100.transports import RtuTransport

from .api import create_clients, create_transport
from .const import (
    CONF_BAUDRATE,
    CONF_CONNECT_TIMEOUT,
    CONF_CONNECTION_TYPE,
    CONF_ENABLE_CONTROLS,
    CONF_KEEPALIVE_INTERVAL,
    CONF_PARITY,
    CONF_RESPONSE_TIMEOUT,
    CONF_SCAN_ADDRESSES,
    CONF_SCAN_ROUNDS,
    CONF_SERIAL_PORT,
    CONF_SLAVE_ADDRESSES,
    CONF_STOPBITS,
    CONF_UPDATE_INTERVAL,
    CONNECTION_SERIAL,
    CONNECTION_TCP,
    DEFAULT_BAUDRATE,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_ENABLE_CONTROLS,
    DEFAULT_KEEPALIVE_INTERVAL,
    DEFAULT_PARITY,
    DEFAULT_RESPONSE_TIMEOUT,
    DEFAULT_SCAN_RESPONSE_TIMEOUT,
    DEFAULT_SCAN_ROUNDS,
    DEFAULT_SLAVE_ADDRESSES,
    DEFAULT_STOPBITS,
    DEFAULT_TCP_PORT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .helpers import format_slave_addresses, parse_slave_addresses

_LOGGER = logging.getLogger(__name__)


class SerialPortUnavailableError(EsmError):
    """Raised when a configured local serial port cannot be opened."""


class ReconfigureInProgressError(EsmError):
    """Raised when the active entry is not stable enough to lend its bus."""


def _text_selector() -> selector.TextSelector:
    """Return a serializable text selector."""
    return selector.TextSelector(selector.TextSelectorConfig())


CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CONNECTION_TYPE): vol.In(
            {
                CONNECTION_SERIAL: "Serial RTU",
                CONNECTION_TCP: "TCP RTU (transparent gateway)",
            }
        )
    }
)

SERIAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SERIAL_PORT): cv.string,
        vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.All(
            vol.Coerce(int), vol.Range(min=300, max=3_000_000)
        ),
        vol.Required(CONF_PARITY, default=DEFAULT_PARITY): vol.In(("N", "E", "O")),
        vol.Required(
            CONF_STOPBITS,
            default=str(DEFAULT_STOPBITS),
        ): vol.In(("1", "2")),
        vol.Required(
            CONF_RESPONSE_TIMEOUT,
            default=DEFAULT_RESPONSE_TIMEOUT,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=30)),
    }
)

TCP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT, default=DEFAULT_TCP_PORT): cv.port,
        vol.Required(
            CONF_CONNECT_TIMEOUT,
            default=DEFAULT_CONNECT_TIMEOUT,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=60)),
        vol.Required(
            CONF_RESPONSE_TIMEOUT,
            default=DEFAULT_RESPONSE_TIMEOUT,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=30)),
    }
)


def _manual_schema(default: str = DEFAULT_SLAVE_ADDRESSES) -> vol.Schema:
    """Build the manual-address schema with a frontend-safe selector."""
    return vol.Schema(
        {
            vol.Required(
                CONF_SLAVE_ADDRESSES,
                default=default,
            ): _text_selector(),
        }
    )


def _scan_schema(
    default_addresses: str | None = None,
    default_rounds: int = DEFAULT_SCAN_ROUNDS,
) -> vol.Schema:
    """Build the fixed-round scan schema."""
    return vol.Schema(
        {
            vol.Required(
                CONF_SCAN_ADDRESSES,
                default=(
                    default_addresses
                    or format_slave_addresses(list(DEFAULT_SCAN_ADDRESSES))
                ),
            ): _text_selector(),
            vol.Required(
                CONF_SCAN_ROUNDS,
                default=default_rounds,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        }
    )


def _options_schema(values: Mapping[str, Any]) -> vol.Schema:
    """Build runtime options with current values as defaults."""
    return vol.Schema(
        {
            vol.Required(
                CONF_UPDATE_INTERVAL,
                default=int(
                    values.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
            vol.Required(
                CONF_KEEPALIVE_INTERVAL,
                default=float(
                    values.get(
                        CONF_KEEPALIVE_INTERVAL,
                        DEFAULT_KEEPALIVE_INTERVAL,
                    )
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=5, max=60)),
            vol.Required(
                CONF_ENABLE_CONTROLS,
                default=bool(
                    values.get(
                        CONF_ENABLE_CONTROLS,
                        DEFAULT_ENABLE_CONTROLS,
                    )
                ),
            ): cv.boolean,
        }
    )


def _connection_identity(data: Mapping[str, Any]) -> tuple[object, ...]:
    """Return the physical endpoint and serial framing for one bus."""
    connection_type = data[CONF_CONNECTION_TYPE]
    if connection_type == CONNECTION_SERIAL:
        return (
            connection_type,
            str(data[CONF_SERIAL_PORT]),
            int(data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)),
            str(data.get(CONF_PARITY, DEFAULT_PARITY)),
            float(data.get(CONF_STOPBITS, DEFAULT_STOPBITS)),
        )
    return (
        connection_type,
        str(data[CONF_HOST]),
        int(data[CONF_PORT]),
    )


@asynccontextmanager
async def _async_operation_transport(
    data: dict[str, Any],
    borrowed_transport: RtuTransport | None = None,
) -> AsyncIterator[RtuTransport]:
    """Provide a transport, preserving a borrowed transport's timeout."""
    owns_transport = borrowed_transport is None
    transport = (
        create_transport(data) if borrowed_transport is None else borrowed_transport
    )
    original_timeout = getattr(transport, "timeout", None)
    if not owns_transport and original_timeout is not None:
        transport.timeout = float(
            data.get(CONF_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT)
        )
    try:
        if owns_transport:
            await _async_prepare_serial_transport(data, transport)
        yield transport
    finally:
        if not owns_transport and original_timeout is not None:
            transport.timeout = original_timeout
        if owns_transport:
            await transport.close()


async def _async_validate_connection(
    data: dict[str, Any],
    borrowed_transport: RtuTransport | None = None,
) -> None:
    """Open the bus and conservatively validate every configured battery."""
    async with _async_operation_transport(data, borrowed_transport) as transport:
        for client in create_clients(transport, data):
            await client.ensure_awake(force=True)


async def _async_prepare_serial_transport(
    data: Mapping[str, Any],
    transport: Any,
) -> None:
    """Open a local serial port before probing battery addresses."""
    if data[CONF_CONNECTION_TYPE] != CONNECTION_SERIAL:
        return
    try:
        await transport.connect()
    except EsmConnectionError as err:
        _LOGGER.warning(
            "Configured serial port %s is unavailable: %s",
            data[CONF_SERIAL_PORT],
            err,
        )
        raise SerialPortUnavailableError from err


async def _async_scan_bus(
    data: dict[str, Any],
    addresses: list[int],
    rounds: int,
    progress_callback: Callable[[float], None],
    borrowed_transport: RtuTransport | None = None,
) -> list[int]:
    """Probe every selected address for a fixed number of complete rounds."""
    scan_data = {
        **data,
        CONF_ENABLE_CONTROLS: False,
        CONF_SLAVE_ADDRESSES: addresses,
        CONF_RESPONSE_TIMEOUT: min(
            float(data.get(CONF_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT)),
            DEFAULT_SCAN_RESPONSE_TIMEOUT,
        ),
    }
    found: set[int] = set()
    total_probes = rounds * len(addresses)
    completed = 0

    async with _async_operation_transport(
        scan_data,
        borrowed_transport,
    ) as transport:
        clients = {
            client.slave_address: client
            for client in create_clients(transport, scan_data)
        }
        for _round in range(rounds):
            for address in addresses:
                try:
                    await clients[address].read_holding_registers(
                        0x0000,
                        1,
                        retries=0,
                    )
                except EsmError:
                    pass
                else:
                    found.add(address)
                completed += 1
                progress_callback(completed / total_probes)

    return [address for address in addresses if address in found]


class HuaweiEsm48100ConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle Huawei ESM-48100 configuration."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        super().__init__()
        self._connection_data: dict[str, Any] | None = None
        self._entry_title: str | None = None
        self._scan_task: asyncio.Task[list[int]] | None = None
        self._scan_results: list[int] = []
        self._scan_error: str | None = None
        self._scan_addresses_text: str | None = None
        self._scan_rounds = DEFAULT_SCAN_ROUNDS

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HuaweiEsm48100OptionsFlow:
        """Return the runtime options flow."""
        del config_entry
        return HuaweiEsm48100OptionsFlow()

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Choose the transport type."""
        if user_input is not None:
            return await self._route_connection_type(
                user_input[CONF_CONNECTION_TYPE]
            )
        return self.async_show_form(
            step_id="user",
            data_schema=CONNECTION_SCHEMA,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Reconfigure connection details and battery addresses."""
        entry = self._get_reconfigure_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="reconfigure_in_progress")
        if user_input is not None:
            return await self._route_connection_type(
                user_input[CONF_CONNECTION_TYPE]
            )
        schema = self.add_suggested_values_to_schema(
            CONNECTION_SCHEMA,
            {
                CONF_CONNECTION_TYPE: entry.data[CONF_CONNECTION_TYPE],
            },
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
        )

    async def _route_connection_type(
        self,
        connection_type: str,
    ) -> ConfigFlowResult:
        if connection_type == CONNECTION_SERIAL:
            return await self.async_step_serial()
        return await self.async_step_tcp()

    def _is_reconfigure(self) -> bool:
        return self.source == config_entries.SOURCE_RECONFIGURE

    @asynccontextmanager
    async def _async_exclusive_bus_access(
        self,
    ) -> AsyncIterator[RtuTransport | None]:
        """Borrow an unchanged bus, or hand off a changed bus explicitly."""
        if not self._is_reconfigure():
            yield None
            return

        entry = self._get_reconfigure_entry()
        if entry.state is not ConfigEntryState.LOADED:
            raise ReconfigureInProgressError(
                f"Config entry is not ready for reconfiguration: {entry.state}"
            )

        assert self._connection_data is not None
        if _connection_identity(self._connection_data) == _connection_identity(
            entry.data
        ):
            async with (
                entry.runtime_data.coordinator.async_exclusive_bus_access()
            ) as transport:
                yield transport
            return

        if not await self.hass.config_entries.async_unload(entry.entry_id):
            raise ReconfigureInProgressError(
                "Unable to temporarily unload the active RS485 bus"
            )

        try:
            yield
        finally:
            if not await asyncio.shield(
                self.hass.config_entries.async_setup(entry.entry_id)
            ):
                _LOGGER.error(
                    "Unable to restore ESM-48100 config entry %s after "
                    "exclusive reconfiguration access",
                    entry.entry_id,
                )

    def _duplicate_exists(self, match: Mapping[str, Any]) -> bool:
        current_entry_id = (
            self._get_reconfigure_entry().entry_id
            if self._is_reconfigure()
            else None
        )
        return any(
            entry.entry_id != current_entry_id
            and all(entry.data.get(key) == value for key, value in match.items())
            for entry in self._async_current_entries()
        )

    async def async_step_serial(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Configure a local serial bus."""
        if user_input is not None:
            data = {
                CONF_CONNECTION_TYPE: CONNECTION_SERIAL,
                **user_input,
                CONF_STOPBITS: int(user_input[CONF_STOPBITS]),
            }
            match = {
                CONF_CONNECTION_TYPE: CONNECTION_SERIAL,
                CONF_SERIAL_PORT: data[CONF_SERIAL_PORT],
            }
            if self._duplicate_exists(match):
                return self.async_abort(reason="already_configured")
            self._connection_data = data
            self._entry_title = f"Serial {data[CONF_SERIAL_PORT]}"
            return await self.async_step_address_method()

        schema = SERIAL_SCHEMA
        if self._is_reconfigure():
            entry = self._get_reconfigure_entry()
            suggested_values = {
                **entry.data,
                CONF_STOPBITS: str(
                    entry.data.get(CONF_STOPBITS, DEFAULT_STOPBITS)
                ),
            }
            schema = self.add_suggested_values_to_schema(
                SERIAL_SCHEMA,
                suggested_values,
            )
        return self.async_show_form(
            step_id="serial",
            data_schema=schema,
            errors={},
        )

    async def async_step_tcp(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Configure a transparent TCP serial gateway."""
        if user_input is not None:
            data = {CONF_CONNECTION_TYPE: CONNECTION_TCP, **user_input}
            match = {
                CONF_CONNECTION_TYPE: CONNECTION_TCP,
                CONF_HOST: data[CONF_HOST],
                CONF_PORT: data[CONF_PORT],
            }
            if self._duplicate_exists(match):
                return self.async_abort(reason="already_configured")
            self._connection_data = data
            self._entry_title = f"TCP {data[CONF_HOST]}:{data[CONF_PORT]}"
            return await self.async_step_address_method()

        schema = TCP_SCHEMA
        if self._is_reconfigure():
            entry = self._get_reconfigure_entry()
            schema = self.add_suggested_values_to_schema(
                TCP_SCHEMA,
                entry.data,
            )
        return self.async_show_form(
            step_id="tcp",
            data_schema=schema,
            errors={},
        )

    async def async_step_address_method(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Choose automatic discovery or manual address entry."""
        del user_input
        return self.async_show_menu(
            step_id="address_method",
            menu_options=["scan", "manual"],
        )

    def _finish(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Create or update the config entry."""
        assert self._entry_title is not None
        if self._is_reconfigure():
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                title=self._entry_title,
                data=data,
            )
        return self.async_create_entry(title=self._entry_title, data=data)

    async def async_step_manual(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Validate explicitly configured battery addresses."""
        errors: dict[str, str] = {}
        default_addresses = DEFAULT_SLAVE_ADDRESSES
        if self._is_reconfigure():
            default_addresses = format_slave_addresses(
                list(
                    self._get_reconfigure_entry().data[
                        CONF_SLAVE_ADDRESSES
                    ]
                )
            )
        if user_input is not None:
            default_addresses = str(user_input[CONF_SLAVE_ADDRESSES])
            try:
                addresses = parse_slave_addresses(default_addresses)
            except ValueError:
                errors[CONF_SLAVE_ADDRESSES] = "invalid_addresses"
            else:
                assert self._connection_data is not None
                data = {
                    **self._connection_data,
                    CONF_SLAVE_ADDRESSES: addresses,
                }
                try:
                    async with self._async_exclusive_bus_access() as transport:
                        await _async_validate_connection(data, transport)
                except SerialPortUnavailableError:
                    errors["base"] = "serial_port_unavailable"
                except ReconfigureInProgressError:
                    errors["base"] = "reconfigure_in_progress"
                except EsmError:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception(
                        "Unexpected error validating ESM-48100 bus"
                    )
                    errors["base"] = "unknown"
                else:
                    return self._finish(data)

        return self.async_show_form(
            step_id="manual",
            data_schema=_manual_schema(default_addresses),
            errors=errors,
        )

    async def async_step_scan(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Configure and run a fixed-round safe bus scan."""
        if self._scan_task is not None:
            if not self._scan_task.done():
                return self.async_show_progress(
                    step_id="scan",
                    progress_action="scan_bus",
                    progress_task=self._scan_task,
                )
            self._scan_results = self._scan_task.result()
            self._scan_task = None
            return self.async_show_progress_done(
                next_step_id="scan_result"
            )

        errors: dict[str, str] = {}
        if user_input is not None:
            self._scan_addresses_text = str(
                user_input[CONF_SCAN_ADDRESSES]
            )
            self._scan_rounds = int(user_input[CONF_SCAN_ROUNDS])
            try:
                addresses = parse_slave_addresses(
                    self._scan_addresses_text
                )
            except ValueError:
                errors[CONF_SCAN_ADDRESSES] = "invalid_addresses"
            else:
                assert self._connection_data is not None
                self._scan_results = []
                self._scan_error = None
                if (
                    self._is_reconfigure()
                    and self._get_reconfigure_entry().state
                    is not ConfigEntryState.LOADED
                ):
                    errors["base"] = "reconfigure_in_progress"
                else:
                    self._scan_task = self.hass.async_create_task(
                        self._async_scan_bus_exclusively(
                            addresses,
                            self._scan_rounds,
                        ),
                        f"{DOMAIN}_bus_scan",
                        eager_start=False,
                    )
                    return self.async_show_progress(
                        step_id="scan",
                        progress_action="scan_bus",
                        progress_task=self._scan_task,
                    )

        return self.async_show_form(
            step_id="scan",
            data_schema=_scan_schema(
                self._scan_addresses_text,
                self._scan_rounds,
            ),
            errors=errors,
        )

    async def _async_scan_bus_exclusively(
        self,
        addresses: list[int],
        rounds: int,
    ) -> list[int]:
        """Scan without leaving the active entry competing for the bus."""
        assert self._connection_data is not None
        try:
            async with self._async_exclusive_bus_access() as transport:
                return await _async_scan_bus(
                    self._connection_data,
                    addresses,
                    rounds,
                    self.async_update_progress,
                    transport,
                )
        except SerialPortUnavailableError:
            self._scan_error = "serial_port_unavailable"
        except ReconfigureInProgressError:
            self._scan_error = "reconfigure_in_progress"
        except Exception:
            _LOGGER.exception("Unexpected error scanning ESM-48100 bus")
            self._scan_error = "unknown"
        return []

    async def async_step_scan_result(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Select which discovered batteries to configure."""
        if self._scan_error is not None:
            error = self._scan_error
            self._scan_error = None
            return self.async_show_form(
                step_id="scan",
                data_schema=_scan_schema(
                    self._scan_addresses_text,
                    self._scan_rounds,
                ),
                errors={"base": error},
            )

        if not self._scan_results:
            return self.async_show_form(
                step_id="scan",
                data_schema=_scan_schema(
                    self._scan_addresses_text,
                    self._scan_rounds,
                ),
                errors={"base": "no_devices_found"},
            )

        options = [
            {"value": str(address), "label": f"0x{address:02X}"}
            for address in self._scan_results
        ]
        address_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=options,
                multiple=True,
                mode=selector.SelectSelectorMode.LIST,
            )
        )
        result_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SLAVE_ADDRESSES,
                    default=[
                        str(address) for address in self._scan_results
                    ],
                ): vol.All(address_selector, vol.Length(min=1)),
            }
        )

        if user_input is not None:
            assert self._connection_data is not None
            data = {
                **self._connection_data,
                CONF_SLAVE_ADDRESSES: [
                    int(address)
                    for address in user_input[CONF_SLAVE_ADDRESSES]
                ],
            }
            return self._finish(data)

        return self.async_show_form(
            step_id="scan_result",
            data_schema=result_schema,
        )


class HuaweiEsm48100OptionsFlow(config_entries.OptionsFlowWithReload):
    """Manage runtime polling and safety options."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Configure polling, keepalive, and advanced controls."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        values = {
            **self.config_entry.data,
            **self.config_entry.options,
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(values),
        )
