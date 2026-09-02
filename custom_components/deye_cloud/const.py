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
