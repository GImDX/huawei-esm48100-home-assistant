"""Explicitly enabled advanced numeric controls."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from huawei_esm48100 import BatteryConfiguration, ControlSetting

from . import HuaweiEsm48100ConfigEntry
from .entity import HuaweiEsm48100Entity


@dataclass(frozen=True, slots=True)
class ControlNumberDefinition:
    """Metadata for one verified coefficient control."""

    key: str
    setting: ControlSetting
    value: Callable[[BatteryConfiguration], float | None]


CONTROL_NUMBERS = (
    ControlNumberDefinition(
        "discharge_limit_coefficient",
        ControlSetting.DISCHARGE_LIMIT_COEFFICIENT,
        lambda data: data.discharge_limit_coefficient,
    ),
    ControlNumberDefinition(
        "charge_limit_coefficient",
        ControlSetting.CHARGE_LIMIT_COEFFICIENT,
        lambda data: data.charge_limit_coefficient,
    ),
    ControlNumberDefinition(
        "default_charge_limit_coefficient",
        ControlSetting.DEFAULT_CHARGE_LIMIT_COEFFICIENT,
        lambda data: data.default_charge_limit_coefficient,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HuaweiEsm48100ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create controls only after the user explicitly enabled them."""
    del hass
    coordinator = entry.runtime_data.coordinator
    if not coordinator.controls_enabled:
        return
    async_add_entities(
        HuaweiEsm48100ControlNumber(entry, slave_address, definition)
        for slave_address in coordinator.data.batteries
        for definition in CONTROL_NUMBERS
    )


class HuaweiEsm48100ControlNumber(HuaweiEsm48100Entity, NumberEntity):
    """A coefficient with strict range validation and write-back checking."""

    _attr_native_min_value = 0.0
    _attr_native_max_value = 1.05
    _attr_native_step = 0.001
    _attr_native_unit_of_measurement = "C"
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        entry: HuaweiEsm48100ConfigEntry,
        slave_address: int,
        definition: ControlNumberDefinition,
    ) -> None:
        super().__init__(entry, slave_address)
        self.definition = definition
        self.client = self.coordinator.clients_by_address[slave_address]
        self._attr_unique_id = (
            f"{entry.entry_id}_{slave_address:02x}_{definition.key}"
        )
        self._attr_translation_key = definition.key

    @property
    def native_value(self) -> float | None:
        """Return the setting read from the battery."""
        configuration = self.coordinator.data.configurations[self.slave_address]
        return self.definition.value(configuration)

    async def async_set_native_value(self, value: float) -> None:
        """Write the allowlisted setting and verify it by reading it back."""
        await self.client.write_control_setting(self.definition.setting, value)
        await self.coordinator.async_request_refresh()
