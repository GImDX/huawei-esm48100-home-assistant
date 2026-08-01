"""Coordinated polling for a shared RS485 bus."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from huawei_esm48100 import (
    BatteryConfiguration,
    BatterySnapshot,
    ControlSetting,
    EsmClient,
    EsmError,
)
from huawei_esm48100.transports import RtuTransport

from .const import (
    CONF_ENABLE_CONTROLS,
    CONF_KEEPALIVE_INTERVAL,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ENABLE_CONTROLS,
    DEFAULT_KEEPALIVE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BusSnapshot:
    """Latest poll data and per-battery communication state."""

    batteries: dict[int, BatterySnapshot]
    configurations: dict[int, BatteryConfiguration]
    unavailable_addresses: frozenset[int]
    battery_errors: dict[int, str]
    response_time_ms: float
    last_success_at: datetime


class HuaweiEsm48100Coordinator(DataUpdateCoordinator[BusSnapshot]):
    """Serialize polling for every battery on one RS485 bus."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        transport: RtuTransport,
        clients: list[EsmClient],
        runtime_config: dict[str, object],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=float(
                    runtime_config.get(
                        CONF_UPDATE_INTERVAL,
                        DEFAULT_UPDATE_INTERVAL,
                    )
                )
            ),
            always_update=False,
        )
        self.transport = transport
        self.clients = clients
        self.clients_by_address = {
            client.slave_address: client for client in clients
        }
        self.controls_enabled = bool(
            runtime_config.get(
                CONF_ENABLE_CONTROLS,
                DEFAULT_ENABLE_CONTROLS,
            )
        )
        self.keepalive_interval = float(
            runtime_config.get(
                CONF_KEEPALIVE_INTERVAL,
                DEFAULT_KEEPALIVE_INTERVAL,
            )
        )
        self._keepalive_task: asyncio.Task[None] | None = None
        self._bus_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._transport_shutdown = False

    def start_keepalive(self) -> None:
        """Start the lightweight read-only keepalive loop."""
        if self._keepalive_task is not None:
            return
        self._keepalive_task = self.hass.async_create_background_task(
            self._keepalive_loop(),
            f"{DOMAIN}_keepalive",
        )

    async def stop_keepalive(self) -> None:
        """Stop the keepalive loop."""
        task = self._keepalive_task
        self._keepalive_task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _keepalive_loop(self) -> None:
        """Keep configured batteries awake with register 0x0000 reads."""
        while True:
            await asyncio.sleep(self.keepalive_interval)
            async with self._bus_lock:
                for client in self.clients:
                    try:
                        await client.ensure_awake()
                    except (EsmError, ValueError) as err:
                        _LOGGER.warning(
                            "Unable to keep ESM-48100 battery 0x%02X awake: %s",
                            client.slave_address,
                            err,
                        )

    @asynccontextmanager
    async def async_exclusive_bus_access(self) -> AsyncIterator[RtuTransport]:
        """Lend the active transport while pausing every runtime bus user."""
        async with self._lifecycle_lock, self._bus_lock:
            restart_keepalive = self._keepalive_task is not None
            await self.stop_keepalive()
            try:
                yield self.transport
            finally:
                if restart_keepalive:
                    self.start_keepalive()

    async def async_write_control_setting(
        self,
        slave_address: int,
        setting: ControlSetting,
        value: float | bool,
    ) -> None:
        """Serialize an allowlisted write with polling and bus scans."""
        async with self._bus_lock:
            await self.clients_by_address[slave_address].write_control_setting(
                setting,
                value,
            )
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        """Stop runtime activity and close the transport after it becomes idle."""
        async with self._lifecycle_lock:
            if self._transport_shutdown:
                return
            await super().async_shutdown()
            async with self._bus_lock:
                await self.stop_keepalive()
                await self.transport.close()
            self._transport_shutdown = True

    async def _async_update_data(self) -> BusSnapshot:
        """Poll slaves sequentially while isolating individual failures."""
        async with self._bus_lock:
            return await self._async_update_data_locked()

    async def _async_update_data_locked(self) -> BusSnapshot:
        """Poll the bus while the caller owns the coordinator bus lock."""
        started = monotonic()
        previous = self.data
        batteries = (
            {} if previous is None else dict(previous.batteries)
        )
        configurations = (
            {} if previous is None else dict(previous.configurations)
        )
        battery_errors: dict[int, str] = {}
        successful_addresses: set[int] = set()

        for client in self.clients:
            try:
                snapshot = await client.read_snapshot()
                if self.controls_enabled:
                    configuration = await client.read_configuration()
            except (EsmError, ValueError) as err:
                battery_errors[client.slave_address] = (
                    f"{type(err).__name__}: {err}"
                )
                _LOGGER.warning(
                    "Unable to read ESM-48100 battery 0x%02X: %s",
                    client.slave_address,
                    err,
                )
                continue

            batteries[client.slave_address] = snapshot
            if self.controls_enabled:
                configurations[client.slave_address] = configuration
            successful_addresses.add(client.slave_address)

        if battery_errors and previous is None:
            addresses = ", ".join(
                f"0x{address:02X}" for address in battery_errors
            )
            raise UpdateFailed(
                f"Unable to complete initial ESM-48100 poll: {addresses}"
            )

        if not successful_addresses:
            raise UpdateFailed("Unable to read any configured ESM-48100 battery")

        return BusSnapshot(
            batteries=batteries,
            configurations=configurations,
            unavailable_addresses=frozenset(battery_errors),
            battery_errors=battery_errors,
            response_time_ms=(monotonic() - started) * 1000,
            last_success_at=datetime.now(UTC),
        )
