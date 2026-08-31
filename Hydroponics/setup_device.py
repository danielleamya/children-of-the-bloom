"""
Sync devices_config.json - the durable device registry polling.py's local
mode reads from - from tinytuya's own wizard output (devices.json), filling
in the extra info tinytuya doesn't reliably provide on its own:

- The device's full DP-code mapping, fetched from the Cloud API's model
  endpoint (`/v2.0/cloud/thing/<id>/model`). `tinytuya wizard`'s own
  devices.json "mapping" only includes dps that are part of the device's
  officially registered per-category schema, which for some devices (see
  polling.py's CLOUD_SENSOR_DP_CODES comment) is a small subset of what it
  actually reports - this fetches the rest.
- Its current LAN IP, looked up by MAC address (network_recovery's
  find_ip_by_mac) rather than relying on tinytuya's UDP discovery scan,
  since low-power/battery devices often sleep through it.
- Its working Tuya protocol version, found by probing candidates directly
  against the device rather than assuming 3.3.

Unlike devices.json/snapshot.json - which `tinytuya wizard`/`tinytuya scan`
overwrite every time they run, discarding anything not in their own schema -
devices_config.json is only ever touched by this script and by polling.py's
own MAC-based IP recovery, so it's safe to hand-edit (e.g. to override a
wrong protocol version) without a later wizard run silently wiping it out.

Workflow for adding a new device or refreshing an existing one:

    # 1. Get id/name/key/mac into devices.json (needs a working Cloud API
    #    subscription for this one step - see the project README):
    python -m tinytuya wizard -y

    # 2. Sync everything else (LAN IP, protocol version, DP mapping) into
    #    devices_config.json:
    python setup_device.py

Then `python polling.py --mode local` should work for it right away.

Usage:
    python setup_device.py                       # sync every device in devices.json
    python setup_device.py --device-id <id>       # sync just one device
    python setup_device.py --no-cloud             # skip the Cloud mapping fetch entirely
    python setup_device.py --no-version-probe     # skip the LAN IP/version probing
"""
import argparse
import json
import sys

import tinytuya

from network_recovery import find_ip_by_mac

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

WIZARD_DEVICES_FILE = 'devices.json'
REGISTRY_FILE = 'devices_config.json'
CLOUD_CONFIG_FILE = 'tinytuya.json'
PROTOCOL_VERSIONS_TO_TRY = (3.5, 3.4, 3.3, 3.1)


def _load_json(path, default):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_registry(registry):
    with open(REGISTRY_FILE, 'w') as f:
        json.dump(registry, f, indent=4)
    print(f"\n\u2713 Saved {REGISTRY_FILE} ({len(registry)} device(s))")


def _try_local_status(device_id, ip, local_key, version):
    try:
        device = tinytuya.Device(dev_id=device_id, address=ip, local_key=local_key, version=version)
        device.set_socketTimeout(5)
        data = device.status()
    except Exception:
        return False
    return bool(data and 'dps' in data)


def _detect_ip_and_version(device_id, local_key, mac, existing_ip, existing_version):
    """
    Confirm (or find) a working ip/version pair for this device.

    Tries the existing ip/version first (if any), so an already-working
    device isn't needlessly re-probed. Otherwise, looks up its current IP by
    MAC address and tries each protocol version in PROTOCOL_VERSIONS_TO_TRY
    against it - tinytuya has no generic way to just ask a device which
    version it speaks.

    Returns (ip, version, note) - `ip`/`version` are the best values found
    (falling back to the existing ones if nothing better was found), and
    `note` is a human-readable summary for the console.
    """
    if existing_ip and existing_version and _try_local_status(device_id, existing_ip, local_key, existing_version):
        return existing_ip, existing_version, f'already working at {existing_ip} (v{existing_version})'

    ip = find_ip_by_mac(mac) if mac else None
    if not ip:
        reason = 'no MAC address on file' if not mac else 'no ARP entry found for its MAC'
        return existing_ip, existing_version, (
            f'could not find its LAN IP ({reason}) - is this machine on the same LAN as the device?'
        )

    versions_to_try = ([existing_version] if existing_version else []) + [
        v for v in PROTOCOL_VERSIONS_TO_TRY if v != existing_version
    ]
    for version in versions_to_try:
        if _try_local_status(device_id, ip, local_key, version):
            return ip, version, f'found at {ip}, protocol v{version}'

    return ip, existing_version, (
        f'found IP {ip} via its MAC address, but it did not respond on any of {versions_to_try} - is it online?'
    )


def _fetch_dp_mapping(cloud, device_id):
    """
    Fetch this device's full DP schema from the Cloud API's model endpoint
    and build a devices_config.json-style "mapping" dict from it, keeping
    only dps that look like sensor readings: accessMode "ro" (read-only -
    excludes settings/limits like phbuffer, backlight, *maxlimit/*minlimit)
    and a non-bool type (excludes read-only device-internal flags, e.g.
    "newprog", that aren't actually a sensor value).

    Returns None (leaving any existing mapping untouched) on any failure -
    missing/expired Cloud credentials, a network error, or an unexpected
    response shape - so a Cloud hiccup during sync can't wipe out a mapping
    that took manual work to build.
    """
    try:
        resp = cloud.cloudrequest(f'/v2.0/cloud/thing/{device_id}/model')
        model = json.loads(resp['result']['model'])
    except Exception as e:
        print(f"  \u26a0 Could not fetch DP mapping from Cloud: {e}")
        return None

    mapping = {}
    for service in model.get('services', []):
        for prop in service.get('properties', []):
            dp_id = prop.get('abilityId')
            code = prop.get('code')
            type_spec = prop.get('typeSpec') or {}
            if dp_id is None or not code:
                continue
            if prop.get('accessMode') != 'ro' or type_spec.get('type') == 'bool':
                continue
            mapping[str(dp_id)] = {
                'code': code,
                'type': 'Integer' if type_spec.get('type') == 'value' else type_spec.get('type', 'Unknown'),
                'values': {
                    'unit': type_spec.get('unit', ''),
                    'min': type_spec.get('min'),
                    'max': type_spec.get('max'),
                    'scale': type_spec.get('scale'),
                    'step': type_spec.get('step'),
                } if type_spec.get('type') == 'value' else {},
            }
    return mapping or None


def sync_devices(device_id_filter=None, use_cloud=True, probe_version=True):
    wizard_devices = _load_json(WIZARD_DEVICES_FILE, [])
    if not wizard_devices:
        print(f"Error: {WIZARD_DEVICES_FILE} has no devices - run `python -m tinytuya wizard -y` first.")
        return

    registry = _load_json(REGISTRY_FILE, [])
    registry_by_id = {entry['id']: entry for entry in registry if isinstance(entry, dict) and entry.get('id')}

    cloud = None
    if use_cloud:
        cloud = tinytuya.Cloud(configFile=CLOUD_CONFIG_FILE)
        if cloud.error:
            print(f"\u26a0 Could not authenticate with Tuya Cloud ({cloud.error}); "
                  "will keep any existing DP mapping as-is and skip fetching new ones.")
            cloud = None

    matched_any = False
    for wizard_dev in wizard_devices:
        device_id = wizard_dev.get('id')
        if not device_id or (device_id_filter and device_id != device_id_filter):
            continue
        matched_any = True

        print(f"\n{wizard_dev.get('name', device_id)} ({device_id})")
        existing = registry_by_id.get(device_id, {})

        entry = dict(existing)
        entry['id'] = device_id
        entry['name'] = wizard_dev.get('name') or existing.get('name') or device_id
        entry['key'] = wizard_dev.get('key') or existing.get('key')
        entry['mac'] = wizard_dev.get('mac') or existing.get('mac')

        if not entry.get('key'):
            print("  \u2717 No local_key available (from devices.json or the existing registry) - skipping.")
            continue

        if probe_version:
            ip, version, note = _detect_ip_and_version(
                device_id, entry['key'], entry.get('mac'),
                existing.get('ip'), existing.get('version'),
            )
            entry['ip'] = ip
            entry['version'] = version
            print(f"  IP/version: {note}")
        else:
            entry.setdefault('version', 3.3)

        if cloud:
            mapping = _fetch_dp_mapping(cloud, device_id)
            if mapping:
                entry['mapping'] = mapping
                print(f"  \u2713 DP mapping: {len(mapping)} sensor dp(s) - "
                      f"{', '.join(v['code'] for v in mapping.values())}")
            elif 'mapping' in existing:
                print("  Keeping existing DP mapping (Cloud fetch found nothing new).")

        registry_by_id[device_id] = entry

    if not matched_any:
        print(f"No matching device found in {WIZARD_DEVICES_FILE}"
              + (f" for --device-id {device_id_filter}" if device_id_filter else ""))
        return

    _save_registry(list(registry_by_id.values()))


def _build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Sync devices_config.json from devices.json (tinytuya wizard's output), "
                    "filling in each device's LAN IP, protocol version, and DP-code mapping.",
    )
    parser.add_argument('--device-id', default=None, help="Only sync this one device ID.")
    parser.add_argument(
        '--no-cloud', action='store_true',
        help="Skip fetching DP mapping from the Cloud API; keep any existing mapping as-is.",
    )
    parser.add_argument(
        '--no-version-probe', action='store_true',
        help="Skip the local IP lookup/protocol-version probing; keep whatever's already in "
             "devices_config.json (or default to version 3.3 for a brand-new device).",
    )
    return parser


def main():
    args = _build_arg_parser().parse_args()
    sync_devices(
        device_id_filter=args.device_id,
        use_cloud=not args.no_cloud,
        probe_version=not args.no_version_probe,
    )


if __name__ == '__main__':
    main()
