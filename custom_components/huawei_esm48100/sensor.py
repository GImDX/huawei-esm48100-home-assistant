"""Read-only sensors for Huawei ESM-48100 batteries."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from huawei_esm48100 import BatterySnapshot

from . import HuaweiEsm48100ConfigEntry
from .entity import HuaweiEsm48100Entity


@dataclass(frozen=True, slots=True)
class EsmSensorDefinition:
    """Metadata and value accessor for one sensor."""

    key: str
    value: Callable[[BatterySnapshot], Any]
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    entity_category: EntityCategory | None = None
    enabled_default: bool = True
    suggested_display_precision: int | None = None


SENSORS = (
    EsmSensorDefinition(
        "bus_voltage",
        lambda data: data.bus_voltage_v,
        "V",
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    EsmSensorDefinition(
        "pack_voltage",
        lambda data: data.pack_voltage_v,
        "V",
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    EsmSensorDefinition(
        "battery_current",
        lambda data: data.current_a,
        "A",
        SensorDeviceClass.CURRENT,
        SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    EsmSensorDefinition(
        "state_of_charge",
        lambda data: data.state_of_charge,
        "%",
        SensorDeviceClass.BATTERY,
        SensorStateClass.MEASUREMENT,
    ),
    EsmSensorDefinition(
        "state_of_health",
        lambda data: data.state_of_health,
        "%",
        None,
        SensorStateClass.MEASUREMENT,
    ),
    EsmSensorDefinition(
        "highest_cell_temperature",
        lambda data: data.highest_cell_temperature_c,
        "°C",
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
    ),
    EsmSensorDefinition(
        "lowest_cell_temperature",
        lambda data: data.lowest_cell_temperature_c,
        "°C",
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
    ),
    EsmSensorDefinition("battery_state", lambda data: data.state),
    EsmSensorDefinition(
        "discharge_ah",
        lambda data: data.discharge_ah,
        "Ah",
        None,
        SensorStateClass.TOTAL_INCREASING,
    ),
    EsmSensorDefinition(
        "discharge_times",
        lambda data: data.discharge_times,
        "times",
        None,
        SensorStateClass.TOTAL_INCREASING,
    ),
    EsmSensorDefinition(
        "minimum_cell_voltage",
        lambda data: data.minimum_cell_voltage_v,
        "V",
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
    ),
    EsmSensorDefinition(
        "maximum_cell_voltage",
        lambda data: data.maximum_cell_voltage_v,
        "V",
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
    ),
    EsmSensorDefinition(
        "cell_voltage_delta",
        lambda data: data.cell_voltage_delta_v,
        "V",
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
    ),
    EsmSensorDefinition(
        "software_version",
        lambda data: data.software_version,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EsmSensorDefinition(
        "bar_code",
        lambda data: data.bar_code,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EsmSensorDefinition(
        "cell_count",
        lambda data: data.cell_count,
        "cells",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HuaweiEsm48100ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up decoded and per-cell sensors."""
    del hass
    entities: list[SensorEntity] = []
    batteries = entry.runtime_data.coordinator.data.batteries
    for slave_address, snapshot in batteries.items():
        entities.extend(
            HuaweiEsm48100Sensor(entry, slave_address, description)
            for description in SENSORS
        )
        entities.append(EsmElectricalLabelSensor(entry, slave_address))
        entities.extend(
            CellSensor(entry, slave_address, "voltage", index)
            for index in range(snapshot.cell_count)
        )
        entities.extend(
            CellSensor(entry, slave_address, "temperature", index)
            for index in range(snapshot.cell_count)
        )
    async_add_entities(entities)


class HuaweiEsm48100Sensor(HuaweiEsm48100Entity, SensorEntity):
    """A decoded battery-level sensor."""

    def __init__(
        self,
        entry: HuaweiEsm48100ConfigEntry,
        slave_address: int,
        definition: EsmSensorDefinition,
    ) -> None:
        super().__init__(entry, slave_address)
        self.definition = definition
        self._attr_unique_id = (
            f"{entry.entry_id}_{slave_address:02x}_{definition.key}"
        )
        self._attr_translation_key = definition.key
        self._attr_native_unit_of_measurement = definition.unit
        self._attr_device_class = definition.device_class
        self._attr_state_class = definition.state_class
        self._attr_entity_category = definition.entity_category
        self._attr_entity_registry_enabled_default = definition.enabled_default
        self._attr_suggested_display_precision = (
            definition.suggested_display_precision
        )

    @property
    def native_value(self) -> Any:
        """Return the decoded value."""
        snapshot = self.coordinator.data.batteries[self.slave_address]
        return self.definition.value(snapshot)


class EsmElectricalLabelSensor(HuaweiEsm48100Entity, SensorEntity):
    """Expose the complete label text without exceeding HA's state limit."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "electrical_label"

    def __init__(
        self,
        entry: HuaweiEsm48100ConfigEntry,
        slave_address: int,
    ) -> None:
        super().__init__(entry, slave_address)
        self._attr_unique_id = (
            f"{entry.entry_id}_{slave_address:02x}_electrical_label"
        )

    @property
    def native_value(self) -> str | None:
        """Return a short state; the full archive is stored in an attribute."""
        snapshot = self.coordinator.data.batteries[self.slave_address]
        return "loaded" if snapshot.electrical_label_text is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return the complete decoded ASCII label archive."""
        snapshot = self.coordinator.data.batteries[self.slave_address]
        if snapshot.electrical_label_text is None:
            return None
        return {"text": snapshot.electrical_label_text}


class CellSensor(HuaweiEsm48100Entity, SensorEntity):
    """One cell voltage or temperature."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        entry: HuaweiEsm48100ConfigEntry,
        slave_address: int,
        kind: str,
        index: int,
    ) -> None:
        super().__init__(entry, slave_address)
        self.kind = kind
        self.index = index
        self._attr_unique_id = (
            f"{entry.entry_id}_{slave_address:02x}_cell_{index + 1}_{kind}"
        )
        self._attr_translation_key = f"cell_{kind}"
        self._attr_translation_placeholders = {"number": str(index + 1)}
        if kind == "voltage":
            self._attr_native_unit_of_measurement = "V"
            self._attr_device_class = SensorDeviceClass.VOLTAGE
            self._attr_suggested_display_precision = 3
        else:
            self._attr_native_unit_of_measurement = "°C"
            self._attr_device_class = SensorDeviceClass.TEMPERATURE

    @property
    def native_value(self) -> float | int | None:
        """Return this cell's latest value."""
        snapshot = self.coordinator.data.batteries[self.slave_address]
        if self.kind == "voltage":
            return snapshot.cell_voltages_v[self.index]
        return snapshot.cell_temperatures_c[self.index]
