"""Alarm binary sensor for Huawei ESM-48100."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HuaweiEsm48100ConfigEntry
from .entity import HuaweiEsm48100Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HuaweiEsm48100ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one aggregate alarm sensor per battery."""
    del hass
    async_add_entities(
        ActiveAlarmSensor(entry, slave_address)
        for slave_address in entry.runtime_data.coordinator.data.batteries
    )


class ActiveAlarmSensor(HuaweiEsm48100Entity, BinarySensorEntity):
    """Report whether any non-reserved captured alarm bit is active."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "active_alarm"

    def __init__(
        self,
        entry: HuaweiEsm48100ConfigEntry,
        slave_address: int,
    ) -> None:
        super().__init__(entry, slave_address)
        self._attr_unique_id = (
            f"{entry.entry_id}_{slave_address:02x}_active_alarm"
        )

    @property
    def is_on(self) -> bool:
        """Return true when at least one alarm is active."""
        return bool(
            self.coordinator.data.batteries[self.slave_address].active_alarms
        )

    @property
    def extra_state_attributes(self) -> dict[str, list[str]]:
        """Expose decoded active alarm names."""
        alarms = self.coordinator.data.batteries[self.slave_address].active_alarms
        return {"active_alarms": list(alarms)}
