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
- Controls on the device page. Time Of Use is exposed slot by slot: for each of
  the six slots a **SOC** target and a **Time Start**, with **Power**, **Voltage**,
  **Grid Charge** and **Generator** available per slot too (disabled by default,
  enable any you need). Alongside them a **Battery DC Charge Current** number, an
  **Energy Pattern** select (Load First / Battery First) and the **Time Of Use**
  master switch. Battery DC Discharge Current, Low Battery SOC, Solar Sell and Max
  Sell Power are provided but disabled by default. A `set_tou_schedule` service
  writes the whole table in one call. Commands are asynchronous and confirmed
  against the order status.
- Inputs are validated only against universal limits (SOC 0-100, slot times kept
  in ascending order). Per-model limits are left to the inverter, which is the
  authority: values it will not accept are rejected with a visible error rather
  than silently dropped.
- Non-essential sensors are hidden by default (enable any from the entity
  settings); the essentials (SOC, powers, temperatures, key energies) stay on.

## Time Of Use control

The inverter's Time Of Use table has six slots. Each slot has a start time, a
battery **SOC** target, a **Power** limit and **Grid Charge** / **Generator**
flags (a per-slot **Voltage** target is used instead of SOC when the inverter is
in voltage mode, for lead-acid or no-BMS batteries). When Time Of Use is on the
inverter holds the battery to each slot's SOC for that part of the day: it
charges up to it and discharges down to it.

This integration exposes the table directly as entities, so you set each value
the way you set anything else in Home Assistant:

- **Time Of Use** (switch) turns the schedule on or off. It must be on for the
  slots to apply.
- **TOU Slot N SOC** (number, N = 1-6) is the battery level to hold in that slot.
- **TOU Slot N Time Start** (time, N = 1-6) is when the slot begins. Each slot's
  end is the next slot's start, and times are kept in ascending order.
- **TOU Slot N Power / Voltage / Grid Charge / Generator** are provided too but
  disabled by default; enable the ones you want to control per slot.

Editing one entity rewrites only that field of that slot and leaves the other
five untouched.

Drive the SOC targets from automations, for example more reserve in winter and
more solar headroom in summer:

```yaml
# Summer: lower the held level in every slot so the battery leaves room for solar
service: number.set_value
target:
  entity_id:
    - number.deye_tou1_batt
    - number.deye_tou2_batt
    - number.deye_tou3_batt
    - number.deye_tou4_batt
    - number.deye_tou5_batt
    - number.deye_tou6_batt
data:
  value: 30
```

To write several slots at once (times, powers, flags included), use the
**`deye_cloud.set_tou_schedule`** service. Or configure Time Of Use on the
**inverter's own screen** and simply turn the **Time Of Use** switch off here, so
the integration never changes your schedule.


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

### Polling and API usage

Deye has announced usage tracking, quotas and rate limits for the Cloud
OpenAPI, so this integration is deliberately frugal with calls. It polls in
tiers: measurements every cycle, the station and device inventory hourly, and
inverter settings (system, battery, Time Of Use) only every few minutes, plus a
short burst of re-reads right after this integration writes a setting.

Two intervals are adjustable under **Settings > Devices & Services > Deye Cloud
> Configure**:

| Option | Default | What it controls |
|--------|---------|------------------|
| Measurement poll interval | 180 s | How often live station and device data is read |
| Inverter settings poll interval | 15 min | How often system, battery and Time Of Use settings are re-read |

Loggers upload to the Deye Cloud only every 3 to 5 minutes, so polling faster
than the default gains little and costs quota. With the defaults and a single
inverter the integration makes roughly 1,300 API calls per day; at a 5 minute
measurement interval, roughly 700.

If the API answers with a rate limit, polling backs off automatically (doubling
up to 30 minutes) and returns to normal once the limit clears.

## Requirements

- A Deye Cloud developer application (App ID and App Secret).
- Home Assistant 2024.11 or newer.

## Disclaimer

This integration is provided as is, without warranty of any kind. It can change
inverter and battery settings, so use it at your own risk and responsibility.
The author is not responsible for any misuse, damage, data loss, or any other
consequences resulting from its use.

## License

MIT, see [LICENSE](LICENSE).
