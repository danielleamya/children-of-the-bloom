import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone

import pandas as pd
import requests
import tinytuya

from csv_io import atomic_write_csv, read_csv_retry
from network_recovery import find_ip_by_mac

# Windows consoles often default to a legacy codepage (e.g. cp1252) that can't
# encode the checkmark/cross-mark characters used in status messages below,
# which would otherwise crash mid-run ( if it happens inside an `except`
# block's own error print, take down the whole script without writing the
# row to CSV). Force UTF-8 with lossy fallback instead of failing outright.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8', errors='replace')

# How many times to retry a Cloud API call (token fetch or data request)
# after a transient network error before giving up on that collection run.
NETWORK_RETRY_ATTEMPTS = 3
NETWORK_RETRY_BACKOFF_SECONDS = 10


def _call_with_retries(fn, description, attempts=NETWORK_RETRY_ATTEMPTS,
                        backoff_seconds=NETWORK_RETRY_BACKOFF_SECONDS):
    """
    Call `fn()`, retrying on transient network errors (e.g. connection reset/
    aborted, timeouts) before giving up.

    tinytuya's Cloud client doesn't retry or catch these itself - a dropped
    socket surfaces as a raw `requests.exceptions.RequestException` (on
    Windows this is often a `ConnectionAbortedError`/WSAECONNABORTED, which
    usually means something *local* interrupted the connection - the machine
    waking from sleep, a VPN/network adapter reconnecting, antivirus HTTPS
    inspection, etc. - rather than a real Tuya outage). Without retrying
    here, one blip during a long `--interval-minutes` sleep throws away an
    entire collection run instead of just that one request.
    """
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < attempts:
                print(f"\u26a0 Network error during {description} "
                      f"(attempt {attempt}/{attempts}): {e}. Retrying in {backoff_seconds}s...")
                time.sleep(backoff_seconds)
    raise last_error

# Some Tuya devices (e.g. this project's "YINMIK/Yieryi WF-3188" 7-in-1 water
# quality tester, Tuya category "szjcy") only have a handful of their dps
# officially registered in Tuya's per-category schema. `Cloud.getstatus()`
# (used below) queries `iot-03/devices/{id}/status`, which is filtered by
# that registered schema - for this device it only ever returns tds_in,
# temp_current, and battery_percentage, even though the device is actively
# reporting many more values (ph, conductivity_value, orp_value, etc.).
#
# The device's full "shadow" (every dp the device has ever reported, schema
# or not) is available via the Cloud API's shadow/properties endpoint, so we
# query that instead and keep only the dps that are real sensor readings
# (as opposed to device settings like phbuffer/backlight/*limit). Verified
# against this device via `cloud.cloudrequest('/v2.0/cloud/thing/<id>/model')`.
CLOUD_SENSOR_DP_CODES = {
    'tds_in', 'temp_current', 'battery_percentage',
    'ph', 'conductivity_value', 'orp_value',
    'humidity', 'eccf', 'salt_tds',
}

def _local_dp_code_map(dev):
    """
    Build a {dp_id: code} map for translating one device's raw local dps ids
    (e.g. tinytuya's `Device.status()` returns data['dps'] == {'1': 942, ...})
    into the Cloud API's human-readable "code" names (e.g. "tds_in"), from
    that device's own "mapping" field in devices.json/snapshot.json - the
    same {"<dp_id>": {"code": "<name>", ...}, ...} shape `tinytuya wizard`
    already writes there. This lets collect_device_data_local() produce the
    same dps_<code> column names as collect_device_data_cloud() (so cloud-
    and local-collected readings for the same device can share one CSV)
    entirely from device data, with no hardcoded per-device knowledge in this
    file and no Cloud access needed at collection time.

    Only codes recognized as real sensor readings (CLOUD_SENSOR_DP_CODES) are
    kept, so settings/limits (phbuffer, backlight, *maxlimit/*minlimit, etc.)
    get dropped here too, same as collect_device_data_cloud()'s filtering -
    this matters because the wizard's own "mapping" capture has the same
    officially-registered-schema limitation described above for
    `Cloud.getstatus()`, so it may need enriching by hand: fetch
    `cloud.cloudrequest('/v2.0/cloud/thing/<id>/model')`, and add any missing
    sensor dps' "code" under that dp id in the device's "mapping".

    Returns None (rather than an empty dict) if the device has no usable
    "mapping" at all, so callers can fall back to keeping raw dps_<dp_id>
    columns instead of silently dropping every dp.
    """
    mapping = dev.get('mapping')
    if not isinstance(mapping, dict) or not mapping:
        return None
    code_map = {
        str(dp_id): info['code']
        for dp_id, info in mapping.items()
        if isinstance(info, dict) and info.get('code') in CLOUD_SENSOR_DP_CODES
    }
    return code_map or None


def _sanitize_filename(label):
    """Turn a device name/id into a filesystem-safe filename stem."""
    label = str(label).strip() or 'unknown_device'
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', label)


def _device_csv_path(output_dir, device_id, name=None):
    """
    Build a device's CSV path: "<name>_<id>.csv" when a name is known (so the
    file stays human-readable, and reads naturally if more devices are added
    later), falling back to just "<id>.csv" otherwise.

    The id always comes last and is never itself sanitized/split (Tuya
    device ids are plain alphanumeric - no separator characters), so it's
    always exactly the last "_"-separated segment of the filename stem,
    regardless of how many underscores the sanitized name contains. That's
    what lets dashboard/server.py recover a device's id from its filename
    without needing to consult any config file - see
    `_device_id_from_csv_path()` there.
    """
    stem = f"{_sanitize_filename(name)}_{device_id}" if name else str(device_id)
    return os.path.join(output_dir, f"{stem}.csv")


def _load_device_names(devices_config_file='devices_config.json'):
    """
    Load {device_id: name} from a devices_config.json-style file (flat list
    or {"devices": [...]} dict - same shapes `collect_device_data_local`
    accepts), so `collect_device_data_cloud` (which otherwise has no concept
    of device names - `tinytuya.json` only lists bare ids) can name its CSVs
    consistently with `collect_device_data_local`, so switching between
    `--mode cloud`/`--mode local` for the same device doesn't fragment its
    history across two differently-named CSVs.

    A missing/invalid/absent file just means no names are available; callers
    fall back to naming that device's CSV by bare id.
    """
    try:
        with open(devices_config_file, 'r') as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    entries = raw.get('devices', []) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return {}
    return {
        entry['id']: entry['name']
        for entry in entries
        if isinstance(entry, dict) and entry.get('id') and entry.get('name')
    }


def _export_to_csv(df, output_file):
    """
    Append df's rows to output_file, creating it (with header) if needed.

    Rows whose `status` is an error (starts with "error", e.g. "error:
    network error after 3 attempts: ...") are skipped - only successful
    readings get persisted to the CSV. Otherwise every failed poll (a
    network blip, a device offline, etc.) would log a row with all the
    `dps_*` metric columns blank, polluting the history the dashboard charts
    and making gaps in real sensor data harder to spot. The full `df`
    (including any error rows) is still returned, so callers/`main()` still
    print/see what happened for this run even though it wasn't written.

    If df has columns the existing file's header doesn't (e.g. a device
    starts/stops reporting a dp), naively appending would produce a ragged
    CSV where rows have more/fewer fields than the header - so in that case
    the whole file is rewritten with a unioned header instead.

    Writes go through `csv_io.atomic_write_csv()` (write-to-temp-file then
    atomic rename) rather than writing/appending to output_file directly.
    dashboard/server.py reads these same files on a timer in a separate
    process, so a plain `to_csv()` risks the dashboard catching the file
    mid-write (truncated/empty) or hitting a transient Windows
    `PermissionError` from the two processes touching the same path at once.
    See csv_io.py for details.
    """
    if df.empty:
        print("No data collected - nothing to export")
        return df

    if 'status' in df.columns:
        to_write = df[~df['status'].astype(str).str.startswith('error')]
    else:
        to_write = df

    skipped = len(df) - len(to_write)
    if skipped:
        print(f"\u26a0 Skipping {skipped} error row(s) - not written to {output_file}")

    if to_write.empty:
        return df

    file_exists = os.path.exists(output_file)

    if file_exists:
        existing_columns = read_csv_retry(output_file, nrows=0).columns.tolist()
        new_columns = [c for c in to_write.columns if c not in existing_columns]
        existing_df = read_csv_retry(output_file)
        if new_columns:
            union_columns = existing_columns + new_columns
            combined = pd.concat([existing_df, to_write], ignore_index=True).reindex(columns=union_columns)
        else:
            combined = pd.concat([existing_df, to_write.reindex(columns=existing_columns)], ignore_index=True)
        atomic_write_csv(combined, output_file)
    else:
        atomic_write_csv(to_write, output_file)

    action = "Appended" if file_exists else "Created"
    print(f"\u2713 {action} {len(to_write)} row(s) in {output_file}")
    return df


def collect_device_data_cloud(config_file='tinytuya.json', output_dir='data'):
    """
    Collect device status via the Tuya Cloud API and export it to per-device CSVs.

    Reads apiKey/apiSecret/apiRegion/apiDeviceID from `config_file` (the format
    produced by `tinytuya wizard`) and queries the status of every device
    listed under "apiDeviceID" using tinytuya's Cloud client. Use this when you
    only have Tuya Cloud credentials and no local_key/IP for your devices.

    Queries the device "shadow" (`/v2.0/cloud/thing/<id>/shadow/properties`)
    rather than `Cloud.getstatus()`, since `getstatus()` only returns dps that
    are part of the device's officially registered per-category schema -
    some devices (see CLOUD_SENSOR_DP_CODES above) report additional sensor
    values that never show up there. Results are filtered down to
    CLOUD_SENSOR_DP_CODES to avoid also recording device settings/limits.

    Each device's row is appended to its own "<name>_<device_id>.csv" file
    inside `output_dir` (created if it doesn't exist) - the name, if any,
    comes from `devices_config.json` (see `_load_device_names()`), so this
    lines up with whatever `collect_device_data_local` names the same
    device's CSV, keeping one continuous history regardless of which mode
    collected which row.

    Args:
        config_file (str): Path to tinytuya.json with Cloud API credentials and device ID(s).
        output_dir (str): Directory to write/append the per-device CSV files to.

    Returns:
        pd.DataFrame: DataFrame containing the rows collected this run (all devices).
    """
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"Error: {config_file} not found")
        return pd.DataFrame()
    except json.JSONDecodeError:
        print(f"Error: {config_file} is not valid JSON")
        return pd.DataFrame()

    device_ids = config.get('apiDeviceID')
    if isinstance(device_ids, str):
        device_ids = [device_ids]
    elif not isinstance(device_ids, list):
        print("Error: apiDeviceID must be a string or list of strings")
        return pd.DataFrame()

    try:
        cloud = _call_with_retries(
            lambda: tinytuya.Cloud(configFile=config_file),
            description='Tuya Cloud authentication',
        )
    except requests.exceptions.RequestException as e:
        print(f"\u2717 Network error authenticating with Tuya Cloud after {NETWORK_RETRY_ATTEMPTS} attempts: {e}")
        return pd.DataFrame()

    if cloud.error:
        print(f"\u2717 Could not authenticate with Tuya Cloud: {cloud.error}")
        return pd.DataFrame()

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    device_names = _load_device_names()
    exported = []

    for device_id in device_ids:
        name = device_names.get(device_id)
        record = {'timestamp': timestamp, 'device_id': device_id, 'name': name}
        try:
            result = _call_with_retries(
                lambda: cloud.cloudrequest(f'/v2.0/cloud/thing/{device_id}/shadow/properties'),
                description=f'fetching status for device {device_id}',
            ) or {}
        except requests.exceptions.RequestException as e:
            record['status'] = f'error: network error after {NETWORK_RETRY_ATTEMPTS} attempts: {e}'
            print(f"\u2717 {record['status']}")
            csv_path = _device_csv_path(output_dir, device_id, name)
            exported.append(_export_to_csv(pd.DataFrame([record]), csv_path))
            continue

        if result.get('success'):
            record['status'] = 'success'
            for dp in result.get('result', {}).get('properties', []):
                dp_key = dp.get('code', dp.get('dp_id'))
                if dp_key not in CLOUD_SENSOR_DP_CODES:
                    continue
                record[f'dps_{dp_key}'] = dp.get('value')
            print(f"\u2713 Successfully collected data from device {device_id}")
        else:
            record['status'] = f"error: {result.get('msg', 'unknown error')}"
            print(f"\u2717 Error collecting data from device {device_id}: {record['status']}")

        csv_path = _device_csv_path(output_dir, device_id, name)
        exported.append(_export_to_csv(pd.DataFrame([record]), csv_path))
        print(f"Exported data to {csv_path}")

    return pd.concat(exported, ignore_index=True) if exported else pd.DataFrame()


def _poll_local_device(device_id, ip, local_key, version):
    """
    Query one device's status over the LAN.

    Returns (data, error_message): on success `data` is tinytuya's status
    dict (containing "dps") and `error_message` is None; on failure `data`
    is None and `error_message` describes what went wrong (exception text,
    or the specific reason tinytuya gave for a response without "dps").
    """
    try:
        device = tinytuya.Device(dev_id=device_id, address=ip, local_key=local_key, version=version)
        data = device.status()
    except Exception as e:
        return None, str(e)

    if data and 'dps' in data:
        return data, None
    return None, (data.get('Error', 'no data received') if data else 'no response')


def _write_devices_file(devices_file, raw, devices):
    """
    Persist `devices` (with any recovered "ip" values) back to
    `devices_file`, preserving the file's original shape - either a flat
    devices.json-style list, or a snapshot.json-style {"timestamp",
    "devices"} dict, whose "timestamp" is refreshed to now.

    Writes via a temp-file-then-`os.replace()` so a concurrent reader (e.g.
    another `polling.py` run, or a future edit) never sees a truncated file,
    mirroring `csv_io.atomic_write_csv()`'s approach for the CSVs.
    """
    if isinstance(raw, dict):
        payload = dict(raw)
        payload['devices'] = devices
        payload['timestamp'] = datetime.now(timezone.utc).timestamp()
    else:
        payload = devices

    directory = os.path.dirname(devices_file) or '.'
    fd, tmp_path = tempfile.mkstemp(
        prefix=f'.{os.path.basename(devices_file)}.tmp-', dir=directory,
    )
    try:
        os.close(fd)
        with open(tmp_path, 'w') as f:
            json.dump(payload, f, indent=4)
        os.replace(tmp_path, devices_file)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def collect_device_data_local(devices_file='devices_config.json', output_dir='data', allow_ip_recovery=True):
    """
    Collect device status via direct local network connections and export it to per-device CSVs.

    Reads id/name/ip/key/version/mac/mapping entries from `devices_file`,
    which can be either a flat list (`devices.json`'s shape) or a dict with a
    "devices" key (`snapshot.json`'s shape). Use this when you have each
    device's local_key and IP and want to avoid depending on the Tuya Cloud
    API at collection time.

    Defaults to `devices_config.json` rather than `tinytuya wizard`'s own
    `devices.json`/`snapshot.json`, because those get overwritten every time
    `tinytuya wizard`/`tinytuya scan` runs - silently dropping anything they
    don't themselves produce, e.g. this function's own IP-recovery writes
    below, or a hand-fixed protocol version. `devices_config.json` is never
    touched by tinytuya's own tools, only by this function (IP recovery) and
    `setup_device.py` (which *reads* devices.json/tuya-raw.json to build/
    refresh it) - see setup_device.py and the README for the intended
    workflow for adding/updating a device.

    IP recovery: if a device with a "mac" field can't be
    reached at its recorded "ip" (stale after a DHCP renewal, router
    reboot, etc.), and `allow_ip_recovery` is True, this looks up its
    current IP by MAC address via `network_recovery.find_ip_by_mac()` -
    which checks (and if needed, actively repopulates via a LAN ping sweep)
    the OS's ARP table - and retries the poll with the recovered IP. To provide 
    reliability for devices that mostly sleep instead of broadcasting. 
    On a successful recovery, the corrected IP is written back to `devices_file`
    so subsequent runs start from the right address directly.

    Each device's row is appended to its own "<name>_<device_id>.csv" file
    inside `output_dir` (created if it doesn't exist) - the same file
    `collect_device_data_cloud` writes to for that device, so switching
    between `--mode cloud`/`--mode local` (or a device's `local_key`
    expiring and needing re-fetching) doesn't fragment one device's history
    across multiple CSVs. For devices with a usable "mapping" field (see
    `_local_dp_code_map()`), columns are named "dps_<code>" (e.g.
    "dps_tds_in") to match `collect_device_data_cloud`'s columns; devices
    without one keep raw "dps_<dp_id>" columns (e.g. "dps_1") since the
    numeric-id-to-code mapping isn't derivable without Cloud access.

    Args:
        devices_file (str): Path to a devices.json or snapshot.json file with local_key/ip per device.
        output_dir (str): Directory to write/append the per-device CSV files to.
        allow_ip_recovery (bool): Attempt MAC-based IP recovery (see above) for
            unreachable devices that have a "mac" field. Default: True.

    Returns:
        pd.DataFrame: DataFrame containing the rows collected this run (all devices).
    """
    try:
        with open(devices_file, 'r') as f:
            raw = json.load(f)
    except FileNotFoundError:
        print(f"Error: {devices_file} not found")
        return pd.DataFrame()
    except json.JSONDecodeError:
        print(f"Error: {devices_file} is not valid JSON")
        return pd.DataFrame()

    devices = raw.get('devices', []) if isinstance(raw, dict) else raw
    if not isinstance(devices, list):
        print(f"Error: could not find a device list in {devices_file}")
        return pd.DataFrame()
    if not devices:
        print(f"No devices listed in {devices_file}. Run `tinytuya wizard` or `tinytuya scan` to populate it.")
        return pd.DataFrame()

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    exported = []
    devices_file_dirty = False

    for dev in devices:
        device_id = dev.get('id') or dev.get('gwId')
        ip = dev.get('ip')
        local_key = dev.get('key')
        version = float(dev.get('version') or dev.get('ver') or 3.3)
        mac = dev.get('mac')
        record = {'timestamp': timestamp, 'device_id': device_id, 'name': dev.get('name')}

        if not local_key:
            record['status'] = 'error: missing local_key (run `tinytuya wizard`)'
            print(f"\u2717 Skipping device {device_id}: missing local_key")
        else:
            data, error = (None, 'missing ip') if not ip else _poll_local_device(device_id, ip, local_key, version)

            if data is None and mac and allow_ip_recovery:
                print(f"\u26a0 {device_id} unreachable at {ip or '<no ip>'} ({error}) - "
                      f"trying MAC-based IP recovery for {mac}...")
                recovered_ip = find_ip_by_mac(mac)
                if recovered_ip and recovered_ip != ip:
                    retry_data, retry_error = _poll_local_device(device_id, recovered_ip, local_key, version)
                    if retry_data is not None:
                        print(f"\u2713 IP recovery: {device_id} is now at {recovered_ip} "
                              f"(was {ip or '<none>'}) - updating {devices_file}")
                        data, error = retry_data, None
                        ip = recovered_ip
                        dev['ip'] = recovered_ip
                        devices_file_dirty = True
                    else:
                        error = f'{error}; MAC recovery found {recovered_ip} but it was also unreachable: {retry_error}'
                elif recovered_ip:
                    error = f'{error}; MAC recovery found the same IP {recovered_ip}, so this is not a stale-IP issue'
                else:
                    error = f'{error}; MAC-based IP recovery found no ARP entry for {mac}'

            if data and 'dps' in data:
                record['status'] = 'success'
                dp_code_map = _local_dp_code_map(dev)
                for key, value in data['dps'].items():
                    if dp_code_map is None:
                        record[f'dps_{key}'] = value
                    elif key in dp_code_map:
                        record[f'dps_{dp_code_map[key]}'] = value
                    # else: known device, unmapped dp (a setting/limit) - drop it,
                    # same as collect_device_data_cloud's CLOUD_SENSOR_DP_CODES filter.
                print(f"\u2713 Successfully collected data from device {device_id}")
            else:
                record['status'] = f'error: {error}'
                print(f"\u2717 Error collecting data from device {device_id}: {error}")

        csv_path = _device_csv_path(output_dir, device_id, dev.get('name'))
        exported.append(_export_to_csv(pd.DataFrame([record]), csv_path))
        print(f"Exported data to {csv_path}")

    if devices_file_dirty:
        try:
            _write_devices_file(devices_file, raw, devices)
            print(f"\u2713 Saved recovered IP address(es) to {devices_file}")
        except OSError as e:
            print(f"\u26a0 Recovered an IP but failed to save it to {devices_file}: {e}")

    return pd.concat(exported, ignore_index=True) if exported else pd.DataFrame()

def run_periodically(collect_fn, interval_minutes=10, **kwargs):
    """
    Repeatedly call `collect_fn(**kwargs)` every `interval_minutes` until stopped.
    Args:
        collect_fn (callable): A collection function, e.g. collect_device_data_cloud
            or collect_device_data_local.
        interval_minutes (float): Minutes to wait between collection runs.
        **kwargs: Passed through to `collect_fn` on every call (e.g. output_dir).

    * Note The api free tier has a budget of 26k requests per month.  USE WITH CAUTION!
    To be conservative we should avoid doing more than half that which ends up as 17 per hour.
    To be conservative assume each sensor counts as its own request. 
    One sensor -> every 4 minutes
    two sensors -> every 8 etc
    """
    interval_seconds = interval_minutes * 60
    print(f"Polling with {collect_fn.__name__} every {interval_minutes} minute(s). Press Ctrl+C to stop.")
    try:
        while True:
            print(f"\n--- Collection run at {datetime.now(timezone.utc).isoformat()} ---")
            try:
                collect_fn(**kwargs)
            except Exception as e:
                print(f"\u2717 Unexpected error during collection: {e}")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\nStopped periodic collection.")


def _build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Poll Tuya hydroponics sensors and export readings to per-device CSVs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # One-off collection via the Tuya Cloud API (uses tinytuya.json)
  python polling.py

  # Same, but explicit
  python polling.py --mode cloud

  # Collect via direct LAN connections (uses devices_config.json), once
  python polling.py --mode local

  # Poll the Cloud API every 4 minutes until Ctrl+C (mind the API budget - see run_periodically())
  python polling.py --mode cloud --interval-minutes 4

  # Poll locally every 30 seconds, using a custom devices file and output dir
  python polling.py --mode local --interval-minutes 0.5 --config-file devices_config.json --output-dir data

  # Poll the Cloud API every hour until Ctrl+C -> This is expected use
  python polling.py --mode cloud --interval-minutes 60

To add or update a device for --mode local (fetch its local_key, MAC, LAN IP,
protocol version, and DP-code mapping), see setup_device.py.
""",
    )
    parser.add_argument(
        '--mode', choices=['cloud', 'local'], default='cloud',
        help="Collection method: 'cloud' queries the Tuya Cloud API (credentials from "
             "tinytuya.json), 'local' connects directly over the LAN (device list from "
             "devices_config.json). Default: cloud.",
    )
    parser.add_argument(
        '--config-file', default=None,
        help="Path to the credentials/devices file. Defaults to 'tinytuya.json' for "
             "--mode cloud, or 'devices_config.json' for --mode local.",
    )
    parser.add_argument(
        '--output-dir', default='data',
        help="Directory to write/append per-device CSV files to. Default: data",
    )
    parser.add_argument(
        '--interval-minutes', type=float, default=None,
        help="If set, poll repeatedly every N minutes (Ctrl+C to stop) instead of running "
             "once. For --mode cloud, the Tuya free tier budget is ~26k requests/month - "
             "see run_periodically()'s docstring before using a low interval.",
    )
    parser.add_argument(
        '--no-ip-recovery', action='store_true',
        help="--mode local only: disable automatic MAC-based IP recovery (and the LAN "
             "ping sweep it can trigger) for devices that are unreachable at their "
             "recorded IP. See collect_device_data_local()'s docstring for details.",
    )
    return parser


def main():
    args = _build_arg_parser().parse_args()

    collect_fn = collect_device_data_cloud if args.mode == 'cloud' else collect_device_data_local
    kwargs = {'output_dir': args.output_dir}
    if args.config_file:
        kwargs['config_file' if args.mode == 'cloud' else 'devices_file'] = args.config_file
    if args.mode == 'local' and args.no_ip_recovery:
        kwargs['allow_ip_recovery'] = False

    source = "Tuya Cloud API" if args.mode == 'cloud' else "local network"

    if args.interval_minutes:
        run_periodically(collect_fn, interval_minutes=args.interval_minutes, **kwargs)
    else:
        print(f"Collecting device data via {source}...")
        df = collect_fn(**kwargs)
        print("\nCollected Data:")
        print(df)


if __name__ == '__main__':
    main()
