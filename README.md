# Deye Cloud for Home Assistant

Home Assistant integration for Deye solar inverters and hybrid energy storage
systems, using the official [Deye Cloud OpenAPI](https://developer.deyecloud.com/).

## Why this exists

The usual way to get a Deye inverter into Home Assistant is a local connection:
the [Solarman](https://github.com/StephanJoubert/home_assistant_solarman)
integrations talk Modbus to the WiFi data logger over TCP port `8899`.

On newer loggers that no longer works. Since a firmware update Deye began rolling
out across its loggers in mid-2024, port `8899` is filtered. The simple Modbus
mode is gone and the logger only accepts the full Solarman V5 handshake (some
batches also add TLS on the cloud port). On the current WiBLE generation the
local port is closed entirely, the local integrations fail to connect, and there
is no firmware rollback.

The remaining local options need extra hardware: an ESP32 with an RS485 adapter
wired to the inverter's Modbus port, or SolarAssistant on a Pi. Those are the
better choice if you want fully local, low latency data.

This integration is for the other case: you just want the numbers in Home
Assistant without adding hardware. It uses Deye's official Cloud API, so any
inverter that already reports to the Deye Cloud app works with only developer
API credentials.

## This integration is cloud dependent

The trade-offs, stated plainly:

- It needs the internet and Deye's cloud. If your connection or Deye Cloud is
  down, entities go unavailable and controls will not apply.
- Data is not real time. Loggers upload to the Deye Cloud roughly every 3 to 5
  minutes, so that is the real granularity no matter how often this integration
  polls. It is not suitable for fast automations.
- It depends on Deye's API availability and quotas, and needs a developer
  application (App ID and Secret) from the Deye Cloud developer portal.
- Controls are best effort. Commands are asynchronous and confirmed against the
  cloud order status, but still depend on the cloud round trip.

If you need real time data or operation that survives an internet or cloud
outage, use a local option (RS485 with ESP32, or SolarAssistant) instead.

## Who it's for

- Good fit: you want your inverter's numbers in Home Assistant with no extra
  hardware and no wiring, for dashboards, energy tracking and occasional control.
- Not the right tool: you need sub-minute data, second-by-second automations, or
  operation that keeps working during an internet or cloud outage. Use a local
  option for that.

## Features

- Cloud polling of station and device measure points, discovered dynamically
  from the API, so new fields a firmware exposes show up automatically.
- Units come straight from the API payload, with correct device and state
  classes, so energy sensors feed the Energy dashboard and long term statistics.
- Controls: work mode, energy pattern, solar sell, max charge current, max
  discharge current and max sell power. Control commands are asynchronous and are
  confirmed against the order status before reporting success.

## Installation (HACS)

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add `https://github.com/maxbanton/hass-deye-cloud` with category **Integration**.
3. Install **Deye Cloud** and restart Home Assistant.
4. Go to **Settings > Devices & Services > Add Integration** and pick **Deye Cloud**.

## Configuration

Create an application at
[developer.deyecloud.com](https://developer.deyecloud.com/) with *Station and
Device Monitoring* and *Commission Control* permissions, then provide:

| Field | Description |
|-------|-------------|
| Region | `Europe, EMEA, Asia-Pacific` or `Americas` |
| App ID and App Secret | From your Deye developer application |
| Email and Password | Your Deye Cloud account login |

## Requirements

- A Deye Cloud developer application (App ID and App Secret).
- Home Assistant 2024.1 or newer.

## License

MIT, see [LICENSE](LICENSE).
