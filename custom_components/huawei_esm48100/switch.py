"""Explicitly enabled advanced binary controls."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from huawei_esm48100 import BatteryConfiguration, ControlSetting

from . import HuaweiEsm48100ConfigEntry
from .entity import HuaweiEsm48100Entity


@dataclass(frozen=True, slots=True)
class ControlSwitchDefinition:
    """Metadata for one verified boolean control."""

    key: str
    setting: ControlSetting
    value: Callable[[BatteryConfiguration], bool | None]


CONTROL_SWITCHES = (
    ControlSwitchDefinition(
        "do1_alarm_action",
        ControlSetting.DO1_ALARM_ACTION_OPEN,
        lambda data: data.do1_alarm_action_open,
    ),
    ControlSwitchDefinition(
        "do2_alarm_action",
        ControlSetting.DO2_ALARM_ACTION_OPEN,
        lambda data: data.do2_alarm_action_open,
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
        HuaweiEsm48100ControlSwitch(entry, slave_address, definition)
        for slave_address in coordinator.data.batteries
        for definition in CONTROL_SWITCHES
    )


class HuaweiEsm48100ControlSwitch(HuaweiEsm48100Entity, SwitchEntity):
    """A boolean setting with write-back verification."""

    def __init__(
        self,
        entry: HuaweiEsm48100ConfigEntry,
        slave_address: int,
        definition: ControlSwitchDefinition,
    ) -> None:
        super().__init__(entry, slave_address)
        self.definition = definition
        self.client = self.coordinator.clients_by_address[slave_address]
        self._attr_unique_id = (
            f"{entry.entry_id}_{slave_address:02x}_{definition.key}"
        )
        self._attr_translation_key = definition.key

    @property
    def is_on(self) -> bool | None:
        """Return whether the configured alarm action is open."""
        configuration = self.coordinator.data.configurations[self.slave_address]
        return self.definition.value(configuration)

    async def async_turn_on(self, **kwargs: object) -> None:
        """Set the alarm action to open."""
        del kwargs
        await self.coordinator.async_write_control_setting(
            self.slave_address,
            self.definition.setting,
            True,
        )

    async def async_turn_off(self, **kwargs: object) -> None:
        """Set the alarm action to close."""
        del kwargs
        await self.coordinator.async_write_control_setting(
            self.slave_address,
            self.definition.setting,
            False,
        )
