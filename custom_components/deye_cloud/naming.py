"""Naming, slugs and measurement classification for Deye measure points.

Kept free of Home Assistant entity machinery so it can be unit-tested directly.
The Deye API returns measure points as ``{key, unit, value}``; the unit is taken
from that payload at runtime, and this module supplies the friendly name,
object-id slug and the device_class / state_class for each key.
"""
from __future__ import annotations

import re

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactivePower,
    UnitOfTemperature,
    UnitOfTime,
)

# Acronyms that should stay upper-cased when a name is generated from a key.
_ACRONYMS = {
    "ac": "AC", "dc": "DC", "pv": "PV", "soc": "SOC", "ct": "CT", "ups": "UPS",
    "bms": "BMS", "pv1": "PV1", "pv2": "PV2", "pv3": "PV3", "l1": "L1", "l2": "L2",
    "rua": "R-UA", "r": "R",
}

_ENERGY_TOKENS = ("production", "consumption", "charge", "discharge", "buy", "sell")


def slugify_key(key: str) -> str:
    """Turn a Deye API key into a snake_case object id.

    ``BatteryPower`` -> ``battery_power``; ``DCVoltagePV1`` -> ``dc_voltage_pv1``;
    ``Temperature- Battery`` -> ``temperature_battery``.
    """
    s = re.sub(r"[\s\-]+", "_", key.strip())
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)          # aB -> a_B
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)        # ABc -> A_Bc
    return re.sub(r"_+", "_", s).strip("_").lower()


def humanize_key(key: str) -> str:
    """Fallback display name for keys not in the curated overlay."""
    words = slugify_key(key).split("_")
    return " ".join(_ACRONYMS.get(w, w.capitalize()) for w in words) or key


# --- curated friendly names (exact) ------------------------------------------

DEVICE_SENSOR_NAMES = {
    "RatedPower": "Rated Power",
    "DCVoltagePV1": "DC Voltage PV1",
    "DCVoltagePV2": "DC Voltage PV2",
    "DCVoltagePV3": "DC Voltage PV3",
    "PVDailyPowerGenerationActive": "PV Daily Power Generation Active",
    "PVCumulativePowerGenerationActive": "PV Cumulative Power Generation Active",
    "InverterTotalReactivePower": "Inverter Total Reactive Power",
    "DCCurrentPV1": "DC Current PV1",
    "DCCurrentPV2": "DC Current PV2",
    "DCCurrentPV3": "DC Current PV3",
    "DCPowerPV1": "DC Power PV1",
    "DCPowerPV2": "DC Power PV2",
    "DCPowerPV3": "DC Power PV3",
    "TotalDCInputPower": "Total DC Input Power",
    "ACVoltageRUA": "AC Voltage R-UA",
    "ACCurrentRUA": "AC Current R-UA",
    "ACOutputFrequencyR": "AC Output Frequency R",
    "PowerFactor": "Power Factor",
    "TotalActiveProduction": "Total Active Production",
    "DailyActiveProduction": "Daily Active Production",
    "InverterOutputPowerL1L2": "Inverter Output Power L1-L2",
    "GridVoltageL1L2": "Grid Voltage L1-L2",
    "GridCurrentL1L2": "Grid Current L1-L2",
    "ExternalCTPowerL1L2": "External CT Power L1-L2",
    "GridFrequency": "Grid Frequency",
    "TotalGridPower": "Total Grid Power",
    "CumulativeGridFeedIn": "Cumulative Grid Feed-In",
    "CumulativeEnergyPurchased": "Cumulative Energy Purchased",
    "DailyGridFeedIn": "Daily Grid Feed-In",
    "DailyEnergyPurchased": "Daily Energy Purchased",
    "GridTotalReactivePower": "Grid Total Reactive Power",
    "LoadVoltageL1L2": "Load Voltage L1-L2",
    "TotalConsumptionPower": "Total Consumption Power",
    "CumulativeConsumption": "Cumulative Consumption",
    "DailyConsumption": "Daily Consumption",
    "BatteryVoltage": "Battery Voltage",
    "BatteryCurrent": "Battery Current",
    "BatteryPower": "Battery Power",
    "SOC": "SOC",
    "TotalChargeEnergy": "Total Charge Energy",
    "TotalDischargeEnergy": "Total Discharge Energy",
    "DailyChargingEnergy": "Daily Charging Energy",
    "DailyDischargingEnergy": "Daily Discharging Energy",
    "BatteryRatedCapacity": "Battery Rated Capacity",
    "Temperature- Battery": "Battery Temperature",
    "DC Temperature": "DC Temperature",
    "AC Temperature": "AC Temperature",
    "GenDailyRunTime": "Generator Daily Run Time",
    "GeneratorFrequency": "Generator Frequency",
    "GenVoltage": "Generator Voltage",
    "TotalGenPower": "Total Generator Power",
    "DailyProductionGenerator": "Daily Generator Production",
    "TotalProductionGenerator": "Total Generator Production",
    "UPSLoadPower": "UPS Load Power",
}

# Station names are stored plain; the station entity appends " (Station)".
STATION_SENSOR_NAMES = {
    "generationPower": "Generation Power",
    "consumptionPower": "Consumption Power",
    "gridPower": "Grid Power",
    "purchasePower": "Purchase Power",
    "wirePower": "Wire Power",
    "chargePower": "Charge Power",
    "dischargePower": "Discharge Power",
    "batteryPower": "Battery Power",
    "batterySOC": "Battery SOC",
    "irradiateIntensity": "Irradiate Intensity",
}

# --- classification overrides for misleading keys ----------------------------

DEVICE_CLASS_OVERRIDES = {
    "PowerFactor": SensorDeviceClass.POWER_FACTOR,
    "GenDailyRunTime": SensorDeviceClass.DURATION,
    "PVCumulativePowerGenerationActive": SensorDeviceClass.ENERGY,
    "CumulativeGridFeedIn": SensorDeviceClass.ENERGY,
}

STATE_CLASS_OVERRIDES = {
    "PowerFactor": SensorStateClass.MEASUREMENT,
    "GenDailyRunTime": SensorStateClass.TOTAL_INCREASING,
    "PVCumulativePowerGenerationActive": SensorStateClass.TOTAL_INCREASING,
    "CumulativeGridFeedIn": SensorStateClass.TOTAL_INCREASING,
}

# Unit fallbacks, used only when the API payload carries no unit for the key.
# Membership is checked, so an explicit None means "unitless".
UNIT_OVERRIDES = {
    "PowerFactor": None,
    "GenDailyRunTime": UnitOfTime.HOURS,
    "BatteryRatedCapacity": "Ah",
    "PVCumulativePowerGenerationActive": UnitOfEnergy.KILO_WATT_HOUR,
    "CumulativeGridFeedIn": UnitOfEnergy.KILO_WATT_HOUR,
}

API_UNIT_MAP = {
    "V": UnitOfElectricPotential.VOLT,
    "A": UnitOfElectricCurrent.AMPERE,
    "W": UnitOfPower.WATT,
    "kW": UnitOfPower.KILO_WATT,
    "Wh": UnitOfEnergy.WATT_HOUR,
    "kWh": UnitOfEnergy.KILO_WATT_HOUR,
    "Hz": UnitOfFrequency.HERTZ,
    "℃": UnitOfTemperature.CELSIUS,
    "°C": UnitOfTemperature.CELSIUS,
    "%": PERCENTAGE,
    "VA": UnitOfApparentPower.VOLT_AMPERE,
    "var": UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
    "Var": UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
    "Ah": "Ah",
    "h": UnitOfTime.HOURS,
    "min": UnitOfTime.MINUTES,
    "s": UnitOfTime.SECONDS,
    "W/m²": "W/m²",
    "W/m2": "W/m²",
}


def map_api_unit(unit: str | None) -> str | None:
    """Translate a Deye API unit string to a Home Assistant unit, else None."""
    if not unit:
        return None
    return API_UNIT_MAP.get(unit.strip())


def device_class_for(key: str) -> SensorDeviceClass | None:
    """device_class for a device measure point (overrides, then heuristic)."""
    if key in DEVICE_CLASS_OVERRIDES:
        return DEVICE_CLASS_OVERRIDES[key]
    kl = key.lower()
    if "daily" in kl:
        return SensorDeviceClass.ENERGY
    if "reactivepower" in kl or ("reactive" in kl and "power" in kl):
        return SensorDeviceClass.REACTIVE_POWER
    if "apparentpower" in kl or ("apparent" in kl and "power" in kl):
        return SensorDeviceClass.APPARENT_POWER
    if "power" in kl:
        return SensorDeviceClass.POWER
    if "energy" in kl or any(t in kl for t in _ENERGY_TOKENS):
        return SensorDeviceClass.ENERGY
    if "voltage" in kl:
        return SensorDeviceClass.VOLTAGE
    if "current" in kl:
        return SensorDeviceClass.CURRENT
    if "frequency" in kl:
        return SensorDeviceClass.FREQUENCY
    if "temperature" in kl:
        return SensorDeviceClass.TEMPERATURE
    if "soc" in kl:
        return SensorDeviceClass.BATTERY
    return None


def state_class_for(key: str) -> SensorStateClass | None:
    """state_class for a device measure point (overrides, then heuristic)."""
    if key in STATE_CLASS_OVERRIDES:
        return STATE_CLASS_OVERRIDES[key]
    kl = key.lower()
    if "daily" in kl:
        return SensorStateClass.TOTAL_INCREASING
    if "power" in kl:
        return SensorStateClass.MEASUREMENT
    # Deye energy counters (daily and lifetime) are monotonic
    if "energy" in kl or any(t in kl for t in _ENERGY_TOKENS):
        return SensorStateClass.TOTAL_INCREASING
    if "irradiate" in kl:
        return SensorStateClass.MEASUREMENT
    if any(x in kl for x in ["voltage", "current", "frequency", "soc", "temperature"]):
        return SensorStateClass.MEASUREMENT
    return None


def unit_fallback(key: str) -> tuple[bool, str | None]:
    """Return (has_override, unit) for the API-less fallback path.

    The name heuristic is a last resort for keys with no API unit and no
    explicit override.
    """
    if key in UNIT_OVERRIDES:
        return True, UNIT_OVERRIDES[key]
    kl = key.lower()
    if "daily" in kl:
        return True, UnitOfEnergy.KILO_WATT_HOUR
    if "reactivepower" in kl or ("reactive" in kl and "power" in kl):
        return True, UnitOfReactivePower.VOLT_AMPERE_REACTIVE
    if "apparentpower" in kl or ("apparent" in kl and "power" in kl):
        return True, UnitOfApparentPower.VOLT_AMPERE
    if "power" in kl:
        return True, UnitOfPower.WATT
    if "energy" in kl or any(t in kl for t in _ENERGY_TOKENS):
        return True, UnitOfEnergy.KILO_WATT_HOUR
    if "voltage" in kl:
        return True, UnitOfElectricPotential.VOLT
    if "current" in kl:
        return True, UnitOfElectricCurrent.AMPERE
    if "frequency" in kl:
        return True, UnitOfFrequency.HERTZ
    if "temperature" in kl:
        return True, UnitOfTemperature.CELSIUS
    if "soc" in kl:
        return True, PERCENTAGE
    if "irradiate" in kl:
        return True, "W/m²"
    return False, None
