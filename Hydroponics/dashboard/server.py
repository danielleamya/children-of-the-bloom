"""
Flask dashboard server for the Hydroponics project.

Reads every per-device CSV written by polling.py (collect_device_data_cloud /
collect_device_data_local) out of the repo's data/ directory, maps device IDs
to friendly names/metric metadata via device_names.json, and exposes two
JSON endpoints consumed by the static frontend in templates/ and static/:

    GET /api/devices                   -> latest reading per device
    GET /api/devices/<device_id>/history?max_points=N -> time series per device

Run with:
    python dashboard/server.py

Then open http://127.0.0.1:8877 in a browser.
"""
import glob
import json
import os
import sys

import pandas as pd
from flask import Flask, jsonify, render_template, request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(REPO_ROOT, 'data')
DEVICE_NAMES_FILE = os.path.join(REPO_ROOT, 'device_names.json')

# csv_io.py lives next to polling.py, one level up from this file.
sys.path.insert(0, REPO_ROOT)
from csv_io import read_csv_retry  # noqa: E402 - needs sys.path set up first

HOST = '127.0.0.1'
PORT = 8877
DEFAULT_MAX_POINTS = 500
REFRESH_HINT_SECONDS = 60  # exposed to the frontend for its auto-refresh timer

DPS_PREFIX = 'dps_'

app = Flask(__name__)

# Simple in-memory caches so a device card doesn't disappear/blank out if a
# CSV read fails while polling.py is mid-append.
_last_good_latest = {}
_last_good_history = {}


# ---------------------------------------------------------------------------
# device_names.json helpers
# ---------------------------------------------------------------------------
def _load_device_meta():
    """
    Load device_names.json and normalize every entry to:
        {"name": str, "metrics": {metric_key: {"label": str, "unit": str, "scale": float}}}

    Accepts both a plain string value ("id": "Display Name") and a rich
    object value ("id": {"name": ..., "metrics": {...}}). Missing/invalid
    file just means everything falls back to raw device ids.
    """
    try:
        with open(DEVICE_NAMES_FILE, 'r') as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        raw = {}

    meta = {}
    if isinstance(raw, dict):
        for device_id, entry in raw.items():
            if isinstance(entry, str):
                meta[device_id] = {'name': entry, 'metrics': {}}
            elif isinstance(entry, dict):
                meta[device_id] = {
                    'name': entry.get('name', device_id),
                    'metrics': entry.get('metrics', {}) or {},
                }
    return meta


def _device_meta_for(meta, device_id):
    return meta.get(device_id, {'name': device_id, 'metrics': {}})


def _metric_info(device_meta, metric_key):
    info = device_meta['metrics'].get(metric_key, {})
    return {
        'label': info.get('label', metric_key.replace('_', ' ').title()),
        'unit': info.get('unit', ''),
        'scale': info.get('scale', 1),
    }


def _dps_columns(df):
    return [c for c in df.columns if c.startswith(DPS_PREFIX)]


def _device_id_from_csv_path(csv_path):
    """
    Recover a device's id from its CSV filename. polling.py names files
    "<name>_<id>.csv" when a device's name is known, falling back to plain
    "<id>.csv" otherwise (see `_device_csv_path()` there). Since Tuya device
    ids are plain alphanumeric (no underscores), the id is always exactly
    the last "_"-separated segment of the filename stem, regardless of how
    many underscores the name part contains - so this works for both forms
    without needing to consult any config file.
    """
    stem = os.path.splitext(os.path.basename(csv_path))[0]
    return stem.rsplit('_', 1)[-1]


def _csv_paths_by_device_id():
    """{device_id: csv_path} for every CSV under DATA_DIR, keyed as above."""
    return {
        _device_id_from_csv_path(csv_path): csv_path
        for csv_path in glob.glob(os.path.join(DATA_DIR, '*.csv'))
    }


# ---------------------------------------------------------------------------
# /api/devices - latest reading per device
# ---------------------------------------------------------------------------
def _build_latest_record(device_id, csv_path, meta):
    device_meta = _device_meta_for(meta, device_id)

    try:
        df = read_csv_retry(csv_path)
        if df.empty:
            raise ValueError('CSV has no rows')

        row = df.iloc[-1]
        readings = {}
        for col in _dps_columns(df):
            metric_key = col[len(DPS_PREFIX):]
            metric = _metric_info(device_meta, metric_key)
            raw_value = row[col]
            try:
                value = float(raw_value) * metric['scale']
            except (TypeError, ValueError):
                value = None if pd.isna(raw_value) else raw_value

            readings[metric_key] = {
                'label': metric['label'],
                'unit': metric['unit'],
                'value': value,
            }

        record = {
            'id': device_id,
            'name': device_meta['name'],
            'timestamp': row['timestamp'] if 'timestamp' in df.columns else None,
            'status': row['status'] if 'status' in df.columns else 'unknown',
            'readings': readings,
            'stale': False,
        }
        _last_good_latest[device_id] = record
        return record

    except Exception as e:
        cached = _last_good_latest.get(device_id)
        if cached:
            stale_record = dict(cached)
            stale_record['stale'] = True
            stale_record['error'] = str(e)
            return stale_record

        return {
            'id': device_id,
            'name': device_meta['name'],
            'timestamp': None,
            'status': f'error: {e}',
            'readings': {},
            'stale': True,
        }


@app.route('/api/devices')
def api_devices():
    meta = _load_device_meta()

    devices = []
    for device_id, csv_path in sorted(_csv_paths_by_device_id().items()):
        devices.append(_build_latest_record(device_id, csv_path, meta))

    return jsonify({'devices': devices, 'refresh_seconds': REFRESH_HINT_SECONDS})


# ---------------------------------------------------------------------------
# /api/devices/<device_id>/history - time series per device
# ---------------------------------------------------------------------------
def _build_history(device_id, meta, max_points):
    device_meta = _device_meta_for(meta, device_id)
    csv_path = _csv_paths_by_device_id().get(device_id)

    try:
        if not csv_path:
            raise FileNotFoundError(f'no CSV found for device {device_id}')
        df = read_csv_retry(csv_path)

        if 'status' in df.columns:
            df = df[df['status'] == 'success']

        dps_cols = _dps_columns(df)
        for col in dps_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        if dps_cols:
            df = df.dropna(subset=dps_cols, how='all')

        if max_points and len(df) > max_points:
            df = df.tail(max_points)

        metrics = {}
        for col in dps_cols:
            metric_key = col[len(DPS_PREFIX):]
            metric = _metric_info(device_meta, metric_key)
            scaled = df[col] * metric['scale']
            metrics[metric_key] = {
                'label': metric['label'],
                'unit': metric['unit'],
                'values': [None if pd.isna(v) else v for v in scaled],
            }

        payload = {
            'id': device_id,
            'name': device_meta['name'],
            'timestamps': df['timestamp'].tolist() if 'timestamp' in df.columns else [],
            'metrics': metrics,
        }
        _last_good_history[device_id] = payload
        return payload

    except Exception as e:
        cached = _last_good_history.get(device_id)
        if cached:
            return cached

        return {
            'id': device_id,
            'name': device_meta['name'],
            'timestamps': [],
            'metrics': {},
            'error': str(e),
        }


@app.route('/api/devices/<device_id>/history')
def api_device_history(device_id):
    meta = _load_device_meta()
    max_points = request.args.get('max_points', default=DEFAULT_MAX_POINTS, type=int)
    return jsonify(_build_history(device_id, meta, max_points))


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html', refresh_seconds=REFRESH_HINT_SECONDS)


if __name__ == '__main__':
    os.makedirs(DATA_DIR, exist_ok=True)
    # use_reloader=False: the auto-reloader spawns a second process, which is
    # unnecessary for this small local dashboard and can confuse process
    # supervisors. debug=True still gives helpful tracebacks in the browser.
    app.run(host=HOST, port=PORT, debug=True, use_reloader=False)
