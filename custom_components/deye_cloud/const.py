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

# Option keys
CONF_SCAN_INTERVAL = "scan_interval"
CONF_CONFIG_INTERVAL = "config_interval"

# Loggers upload to the Deye Cloud roughly every 3-5 minutes, so polling faster
# than that returns the same values and only burns API quota.
DEFAULT_SCAN_INTERVAL = 180  # seconds
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 3600

# Inverter configuration (system/battery/TOU) only changes when something writes
# it, so it is read on a slow tier plus a forced re-read after our own writes.
DEFAULT_CONFIG_INTERVAL = 15  # minutes
MIN_CONFIG_INTERVAL = 1
MAX_CONFIG_INTERVAL = 1440

# The station/device inventory is near-static; re-read it only for discovery.
INVENTORY_INTERVAL = 3600  # seconds

# Polls that re-read config after a write, so an optimistic value converges on
# the cloud read-back (which lags a write by a minute or two).
CONFIG_CATCHUP_POLLS = 5

# Upper bound for the rate-limit backoff.
MAX_BACKOFF_INTERVAL = 1800  # seconds

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
