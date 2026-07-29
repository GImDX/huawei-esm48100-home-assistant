"""Base entities for Huawei ESM-48100 batteries."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HuaweiEsm48100ConfigEntry
from .const import DOMAIN
from .coordinator import HuaweiEsm48100Coordinator


class HuaweiEsm48100Entity(CoordinatorEntity[HuaweiEsm48100Coordinator]):
    """Base class for one battery on a shared bus."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: HuaweiEsm48100ConfigEntry,
        slave_address: int,
    ) -> None:
        """Initialize the entity."""
        super().__init__(entry.runtime_data.coordinator)
        self.slave_address = slave_address
        snapshot = entry.runtime_data.coordinator.data.batteries[slave_address]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}:{slave_address}")},
            manufacturer="Huawei",
            model="ESM-48100",
            name=f"Huawei ESM-48100 @ 0x{slave_address:02X}",
            sw_version=snapshot.software_version,
        )

    @property
    def available(self) -> bool:
        """Return whether this battery succeeded in the latest bus poll."""
        return (
            super().available
            and self.slave_address
            not in self.coordinator.data.unavailable_addresses
        )
