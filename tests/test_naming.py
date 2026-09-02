"""Tests for measure-point naming and classification."""
import pytest
from homeassistant.components.sensor import (
    SensorDeviceClass as DC,
    SensorStateClass as SC,
)

try:
    from homeassistant.components.sensor.const import DEVICE_CLASS_STATE_CLASSES
except ImportError:  # pragma: no cover
    from homeassistant.components.sensor import DEVICE_CLASS_STATE_CLASSES
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfReactivePower,
    UnitOfTime,
)

from custom_components.deye_cloud import const
from custom_components.deye_cloud.naming import (
    DEVICE_SENSOR_NAMES,
    STATION_SENSOR_NAMES,
    device_class_for,
    humanize_key,
    map_api_unit,
    slugify_key,
    state_class_for,
    unit_fallback,
)

ALL_DEVICE_KEYS = sorted(DEVICE_SENSOR_NAMES)
ALL_STATION_KEYS = sorted(STATION_SENSOR_NAMES)


def _combo_valid(dc, sc):
    if dc is None or sc is None:
        return True
    allowed = DEVICE_CLASS_STATE_CLASSES.get(dc)
    return True if allowed is None else sc in allowed


@pytest.mark.parametrize("key", ALL_DEVICE_KEYS + ALL_STATION_KEYS)
def test_class_combo_is_ha_valid(key):
    assert _combo_valid(device_class_for(key), state_class_for(key)), key


@pytest.mark.parametrize(
    "key,slug",
    [
        ("BatteryPower", "battery_power"),
        ("DCVoltagePV1", "dc_voltage_pv1"),
        ("SOC", "soc"),
        ("Temperature- Battery", "temperature_battery"),
        ("DC Temperature", "dc_temperature"),
        ("ACOutputFrequencyR", "ac_output_frequency_r"),
        ("generationPower", "generation_power"),
        ("UPSLoadPower", "ups_load_power"),
    ],
)
def test_slugify(key, slug):
    assert slugify_key(key) == slug


def test_humanize_fallback_uses_acronyms():
    assert humanize_key("DCPowerPV2") == "DC Power PV2"
    assert humanize_key("someNewField") == "Some New Field"


# device_class / state_class / fallback-unit for the corrected fields
DEVICE_EXPECTATIONS = {
    "PVDailyPowerGenerationActive": (DC.ENERGY, SC.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR),
    "PVCumulativePowerGenerationActive": (DC.ENERGY, SC.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR),
    "CumulativeGridFeedIn": (DC.ENERGY, SC.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR),
    "TotalConsumptionPower": (DC.POWER, SC.MEASUREMENT, UnitOfPower.WATT),
    "InverterTotalReactivePower": (DC.REACTIVE_POWER, SC.MEASUREMENT, UnitOfReactivePower.VOLT_AMPERE_REACTIVE),
    "PowerFactor": (DC.POWER_FACTOR, SC.MEASUREMENT, None),
    "GenDailyRunTime": (DC.DURATION, SC.TOTAL_INCREASING, UnitOfTime.HOURS),
    "BatteryRatedCapacity": (None, None, "Ah"),
    "BatteryVoltage": (DC.VOLTAGE, SC.MEASUREMENT, UnitOfElectricPotential.VOLT),
    "SOC": (DC.BATTERY, SC.MEASUREMENT, PERCENTAGE),
    "TotalChargeEnergy": (DC.ENERGY, SC.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR),
}


@pytest.mark.parametrize("key,expected", DEVICE_EXPECTATIONS.items())
def test_device_classification(key, expected):
    dc, sc, unit = expected
    assert device_class_for(key) == dc
    assert state_class_for(key) == sc
    _, fallback = unit_fallback(key)
    assert fallback == unit


def test_station_irradiance():
    assert state_class_for("irradiateIntensity") == SC.MEASUREMENT
    _, unit = unit_fallback("irradiateIntensity")
    assert unit == "W/m²"


@pytest.mark.parametrize(
    "api_unit,expected",
    [
        ("V", UnitOfElectricPotential.VOLT),
        ("kWh", UnitOfEnergy.KILO_WATT_HOUR),
        ("var", UnitOfReactivePower.VOLT_AMPERE_REACTIVE),
        ("Ah", "Ah"),
        ("h", UnitOfTime.HOURS),
        ("W/m2", "W/m²"),
        ("", None),
        (None, None),
        ("nonsense", None),
    ],
)
def test_map_api_unit(api_unit, expected):
    assert map_api_unit(api_unit) == expected


def test_names_non_empty_and_slugs_unique():
    combined = {**DEVICE_SENSOR_NAMES, **STATION_SENSOR_NAMES}
    assert all(isinstance(v, str) and v.strip() for v in combined.values())
    dev_slugs = [slugify_key(k) for k in DEVICE_SENSOR_NAMES]
    sta_slugs = [slugify_key(k) for k in STATION_SENSOR_NAMES]
    assert len(set(dev_slugs)) == len(dev_slugs)
    assert len(set(sta_slugs)) == len(sta_slugs)


def test_select_label_maps():
    assert set(const.WORK_MODE_LABELS) == set(const.WORK_MODES)
    assert set(const.ENERGY_PATTERN_LABELS) == set(const.ENERGY_PATTERNS)
    for labels in (const.WORK_MODE_LABELS, const.ENERGY_PATTERN_LABELS):
        assert len(set(labels.values())) == len(labels)
