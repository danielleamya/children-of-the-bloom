# Hydroponics

Polls Tuya-connected hydroponics sensors (via [`tinytuya`](https://github.com/jasonacox/tinytuya)), logs readings to per-device CSVs, and serves a small local web dashboard to visualize current + historical readings.

## Project layout

```
Hydroponics/
├── polling.py                 # data collection: Cloud/local polling + periodic loop
├── setup_device.py            # syncs devices_config.json from devices.json (see "Adding a device" below)
├── network_recovery.py        # MAC-based LAN IP lookup, used to refresh a stale IP in local mode
├── csv_io.py                   # shared atomic-write/retry helpers for reading & writing the CSVs safely
├── device_names.json          # maps device IDs -> friendly display names / metric units (dashboard only)
├── requirements.txt           # pandas, tinytuya, Flask
├── tinytuya.json              # Tuya Cloud API credentials (gitignored, not in repo)
├── devices_config.json        # durable local device registry - id/ip/key/version/mac/DP-mapping
├── devices.json               # raw `tinytuya wizard` output (gitignored, overwritten on every wizard run)
├── snapshot.json              # raw `tinytuya scan`/wizard-poll output (gitignored, overwritten on every run)
├── data/                      # per-device CSVs written by polling.py (gitignored)
│   └── <name>_<device_id>.csv
└── dashboard/
    ├── server.py               # Flask app serving the dashboard + JSON API
    ├── templates/index.html
    └── static/
        ├── app.js               # fetches API, renders cards + Chart.js charts
        └── style.css
```

## Setup

```powershell
# From the repo root, using the project venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

To activate the venv :
Open Command Prompt in the folder containing the venv directory.
Run venv\Scripts\activate.bat to activate in Command Prompt.
You can then just run python scripts as normal without explicitly starting with the venv

You'll also need a `tinytuya.json` (Tuya Cloud API credentials: `apiKey`, `apiSecret`, `apiRegion`, `apiDeviceID`) for `--mode cloud`, and/or a `devices_config.json` (local device `id`/`ip`/`key`/`version`/`mac`/DP-mapping, built by [`setup_device.py`](setup_device.py) - see "Adding or updating a device" below) for `--mode local`.

## Collecting data (`polling.py`)

Two collection functions in [`polling.py`](polling.py), one row per device per run, each appended to its own CSV in `data/`:

- `collect_device_data_cloud(config_file='tinytuya.json', output_dir='data')` — queries Tuya's Cloud API for each device ID listed in `tinytuya.json`. No local key/IP needed.
- `collect_device_data_local(devices_file='devices_config.json', output_dir='data')` — connects directly over the local network using each device's `id`/`ip`/`key`/`version` from `devices_config.json`.

Both write to the same `data/<name>_<device_id>.csv` file for a given device (the name comes from `devices_config.json` either way), so switching between `--mode cloud`/`--mode local` never fragments one device's history across multiple CSVs.

#### IP recovery (local mode)

A device's IP address in `devices_config.json` can go stale (DHCP lease renewal, router reboot, etc.). Normally `tinytuya scan` would relocate it via its UDP discovery broadcast, but low-power/battery devices mostly sleep and don't broadcast reliably enough for that to work.

So if a device (with a `"mac"` field in its entry) can't be reached at its recorded `ip`, `collect_device_data_local` automatically looks up its current IP by MAC address instead, via [`network_recovery.find_ip_by_mac()`](network_recovery.py) — this checks the OS's ARP table and, if the MAC isn't there yet, does a quick LAN ping sweep to force it to appear, then checks again. If a different IP is found, it retries the poll with it, and on success **rewrites `devices_config.json` with the corrected IP** so future runs start from the right address directly, no manual `arp -a` digging required.

This only works for devices whose entry has a `"mac"` field (`setup_device.py` fills this in automatically). Disable it with `--no-ip-recovery` if you'd rather it just fail than trigger a ping sweep of your LAN.

## Adding or updating a device

Tuya devices need three things before `--mode local` can poll them directly: their `local_key`, their current LAN IP, and (for some devices) a mapping from raw numeric dp ids to human-readable column names. Getting all three onto disk is a two-step process (Assuming you have an active tuya cloud subscription):

```powershell
# 1. Get id/name/local_key/MAC from Tuya's Cloud API into devices.json.
#    Needs a working Cloud API subscription for this one step - if you see
#    "IoT Core service subscription has expired", log into iot.tuya.com and
#    renew it (free) first.
.\venv\Scripts\python.exe -m tinytuya wizard -y

# 2. Sync everything else into devices_config.json: confirms/finds the
#    device's LAN IP (by MAC address, via network_recovery.py), probes which
#    Tuya protocol version it speaks, and fetches its full sensor DP mapping
#    from the Cloud API.
.\venv\Scripts\python.exe setup_device.py
```

`python polling.py --mode local` should then work for the device right away - no manual editing needed.

Useful `setup_device.py` flags:

- `--device-id <id>` — sync just one device instead of everything in `devices.json`.
- `--no-cloud` — skip the Cloud DP-mapping fetch (e.g. if your Cloud subscription is expired again); keeps whatever mapping is already in `devices_config.json`.
- `--no-version-probe` — skip the LAN IP lookup/protocol-version probing; keeps the existing `ip`/`version` (or defaults a brand-new device to `3.3`).

**Why two files?** `devices.json`/`snapshot.json` are tinytuya's own output - they get fully overwritten every time `tinytuya wizard`/`tinytuya scan` runs, silently dropping anything tinytuya itself doesn't produce (a hand-fixed protocol version, a MAC-recovered IP, an enriched DP mapping). `devices_config.json` is never touched by tinytuya's tools - only by `setup_device.py` and `collect_device_data_local`'s own IP self-healing - so it's safe to hand-edit and survives future wizard re-runs. See the comments at the top of [`setup_device.py`](setup_device.py) for more detail.

If a device's dp schema isn't fully covered by the Cloud API's model endpoint, or `setup_device.py` can't reach it, you can always hand-edit its entry in `devices_config.json` directly - it's a plain JSON list of `{"id", "name", "ip", "key", "version", "mac", "mapping"}` objects (see the existing entry for the shape). A device with no `"mapping"` still works with `--mode local`, just with raw `dps_<dp_id>` column names instead of human-readable ones.

### Periodic polling

`polling.py` is a CLI (see `_build_arg_parser()`) with a `--mode {cloud,local}` flag choosing between `collect_device_data_cloud`/`collect_device_data_local`, and an optional `--interval-minutes` flag. If `--interval-minutes` is omitted, it collects once and exits; if set, it hands off to **`run_periodically(collect_fn, interval_minutes, **kwargs)`**, which calls `collect_fn` in a loop, sleeping `interval_minutes` between runs, catches per-run exceptions so one bad poll doesn't kill the loop, and stops cleanly on `Ctrl+C`.

**Expected use case** — poll locally once an hour:

```powershell
.\venv\Scripts\python.exe polling.py --mode local --interval-minutes 60
```

Other useful flags: `--config-file` (defaults to `tinytuya.json` for `--mode cloud` or `devices_config.json` for `--mode local`) and `--output-dir` (defaults to `data`). Run `polling.py --help` for the full list and more examples.

Note: Tuya's free Cloud API tier has a budget of ~26k requests/month (see the comment above `run_periodically` in `polling.py`) — at `--interval-minutes 60` with a handful of sensors this comfortably fits within that budget.

Failed polls (network errors, a device offline, etc.) are still printed to the console/logs, but rows with an error `status` are **not** written to the device's CSV — only successful readings are persisted, so the metrics history/charts don't get polluted with blank `dps_*` values.

## Running the dashboard

```powershell
.\venv\Scripts\python.exe dashboard\server.py
```

Then open **http://127.0.0.1:8877** in a browser.

The dashboard reads every `*.csv` in `data/`, shows the latest reading per device (name, status, current metric values), and a small line chart per metric using historical data. It auto-refreshes every 60 seconds (`REFRESH_HINT_SECONDS` in `dashboard/server.py`). Host/port are constants (`HOST`, `PORT`) near the top of [`dashboard/server.py`](dashboard/server.py).

Each device's id is recovered from its CSV filename (`_device_id_from_csv_path()`) - since `polling.py` always appends `_<device_id>` last, this works whether the file is named `<name>_<device_id>.csv` or just `<device_id>.csv`. A stray CSV that doesn't end in a real device id (e.g. a leftover from before a rename) will show up as a bogus device in the dashboard, so clean those up if you ever rename something in `data/` by hand.

To stop the server, press `Ctrl+C` in its terminal (or find and stop the process listening on port 8877).

### Running both at once

`polling.py` and `dashboard/server.py` are meant to run at the same time (in separate terminals), each with its own device CSVs under `data/` — one writing, one reading. [`csv_io.py`](csv_io.py) makes this safe: writes go through a write-to-temp-file-then-atomic-rename so readers never see a truncated file, and both reads and writes retry briefly on the transient `PermissionError`s Windows can throw when two processes touch the same file (e.g. antivirus/backup tools briefly locking a just-written file).

### Customizing device names/units

Edit [`device_names.json`](device_names.json) to give a device a friendly name and per-metric labels/units/scale factors:

```json
{
  "eb39b05f77133cf7066kmy": {
    "name": "Main Reservoir Sensor",
    "metrics": {
      "temp_current": {"label": "Temp", "unit": "\u00b0C", "scale": 0.1},
      "tds_in": {"label": "TDS", "unit": "ppm"},
      "battery_percentage": {"label": "Battery", "unit": "%"}
    }
  }
}
```

A plain string value (`"id": "Display Name"`) also works if you don't need per-metric metadata. Any device CSV not listed here just falls back to showing its raw ID.
