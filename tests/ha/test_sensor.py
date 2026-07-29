"""Test sensor presentation metadata."""

from custom_components.huawei_esm48100.sensor import SENSORS


def test_voltage_display_precision_matches_register_resolution() -> None:
    """Pack values use centivolts and cell values use millivolts."""
    definitions = {definition.key: definition for definition in SENSORS}

    assert definitions["bus_voltage"].suggested_display_precision == 2
    assert definitions["pack_voltage"].suggested_display_precision == 2
    assert definitions["minimum_cell_voltage"].suggested_display_precision == 3
    assert definitions["maximum_cell_voltage"].suggested_display_precision == 3
    assert definitions["cell_voltage_delta"].suggested_display_precision == 3
    assert definitions["bar_code"].entity_category is not None
