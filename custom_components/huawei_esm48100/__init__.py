"""Huawei ESM-48100 Home Assistant integration."""

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from huawei_esm48100.transports import RtuTransport

from .api import create_clients, create_transport
from .const import PLATFORMS
from .coordinator import HuaweiEsm48100Coordinator


@dataclass(slots=True)
class HuaweiEsm48100RuntimeData:
    """Runtime objects owned by one config entry."""

    transport: RtuTransport
    coordinator: HuaweiEsm48100Coordinator


type HuaweiEsm48100ConfigEntry = ConfigEntry[HuaweiEsm48100RuntimeData]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HuaweiEsm48100ConfigEntry,
) -> bool:
    """Set up one RS485 bus."""
    runtime_config = {**entry.data, **entry.options}
    transport = create_transport(runtime_config)
    clients = create_clients(transport, runtime_config)
    coordinator = HuaweiEsm48100Coordinator(
        hass,
        entry,
        clients,
        runtime_config,
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await transport.close()
        raise

    entry.runtime_data = HuaweiEsm48100RuntimeData(transport, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.start_keepalive()
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: HuaweiEsm48100ConfigEntry,
) -> bool:
    """Unload one RS485 bus."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.coordinator.stop_keepalive()
    await entry.runtime_data.transport.close()
    return True
