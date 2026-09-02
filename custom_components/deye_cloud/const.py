"""Constants for the Deye Cloud integration."""
from __future__ import annotations

DOMAIN = "deye_cloud"

# Entity id prefix (kept short and stable so history survives renames).
ID_PREFIX = "deye"

# Config keys
CONF_APP_ID = "app_id"
CONF_APP_SECRET = "app_secret"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_REGION = "region"

DEFAULT_SCAN_INTERVAL = 60  # seconds

REGION_EU = "eu"
REGION_US = "us"

REGIONS = {
    REGION_EU: {
        "name": "Europe, EMEA, Asia-Pacific",
        "base_url": "https://eu1-developer.deyecloud.com/v1.0",
    },
    REGION_US: {
        "name": "Americas",
        "base_url": "https://us1-developer.deyecloud.com/v1.0",
    },
}

COORDINATOR = "coordinator"

# Control enums (raw API values)
WORK_MODES = ["SELLING_FIRST", "ZERO_EXPORT_TO_LOAD", "ZERO_EXPORT_TO_CT"]
WORK_MODE_LABELS = {
    "SELLING_FIRST": "Selling First",
    "ZERO_EXPORT_TO_LOAD": "Zero Export to Load",
    "ZERO_EXPORT_TO_CT": "Zero Export to CT",
}

ENERGY_PATTERNS = ["BATTERY_FIRST", "LOAD_FIRST"]
ENERGY_PATTERN_LABELS = {
    "BATTERY_FIRST": "Battery First",
    "LOAD_FIRST": "Load First",
}
