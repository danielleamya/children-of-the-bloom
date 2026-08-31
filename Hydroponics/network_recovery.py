"""
Helper for recovering a local Tuya device's current LAN IP address from its
MAC address, for use when `polling.py`'s local-mode collection can't reach
the IP address recorded in snapshot.json/devices.json (e.g. after a DHCP
lease renewal or router reboot).

`tinytuya scan`/`tinytuya wizard` normally relocate a device via its UDP
discovery broadcast, but low-power/battery devices (see polling.py's
low-battery YINMIK water quality sensor) mostly sleep and don't broadcast
reliably enough for that to work - a scan can come back with 0 devices found
even though the device is online. This falls back to reading (and, if
needed, actively repopulating) the OS's ARP table instead - the same
approach used manually via `arp -a` to relocate a device by MAC address.
"""
import platform
import re
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

PING_TIMEOUT_SECONDS = 0.5
PING_SWEEP_MAX_WORKERS = 64


def _normalize_mac(mac):
    return re.sub(r'[^0-9a-f]', '', mac.lower())


def _read_arp_table():
    """Return {normalized_mac: ip} parsed from the OS's current ARP cache."""
    try:
        output = subprocess.run(
            ['arp', '-a'], capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}

    if platform.system() == 'Windows':
        # e.g. "  192.168.0.117         20-f1-b2-c1-a7-96     dynamic"
        pattern = re.compile(r'(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})')
    else:
        # e.g. "? (192.168.0.117) at 20:f1:b2:c1:a7:96 [ether] on eth0"
        pattern = re.compile(r'\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]{17})')

    table = {}
    for line in output.splitlines():
        match = pattern.search(line)
        if match:
            ip, mac = match.groups()
            table[_normalize_mac(mac)] = ip
    return table


def _local_subnet_hosts():
    """
    Guess this machine's local /24 subnet (e.g. ["192.168.0.1", ...,
    "192.168.0.254"]) from the interface it would use to reach the internet.

    Uses a UDP socket's connect() purely to ask the OS to pick a local
    source address/route for an external target - no packet is actually
    sent for UDP until data is written, so this doesn't touch the network.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('10.255.255.255', 1))
        local_ip = sock.getsockname()[0]
    except OSError:
        return []
    finally:
        sock.close()

    prefix = '.'.join(local_ip.split('.')[:3])
    return [f'{prefix}.{i}' for i in range(1, 255)]


def _ping(host):
    """Send one OS ping to `host` to (re)populate the ARP cache; result is ignored."""
    if platform.system() == 'Windows':
        cmd = ['ping', '-n', '1', '-w', str(int(PING_TIMEOUT_SECONDS * 1000)), host]
    else:
        cmd = ['ping', '-c', '1', '-W', str(max(1, int(PING_TIMEOUT_SECONDS))), host]
    try:
        subprocess.run(cmd, capture_output=True, timeout=PING_TIMEOUT_SECONDS + 2)
    except (OSError, subprocess.SubprocessError):
        pass


def _refresh_arp_cache_via_ping_sweep():
    hosts = _local_subnet_hosts()
    if not hosts:
        return
    with ThreadPoolExecutor(max_workers=PING_SWEEP_MAX_WORKERS) as pool:
        list(pool.map(_ping, hosts))


def find_ip_by_mac(mac, allow_ping_sweep=True):
    """
    Look up the current LAN IP address for a device's MAC address.

    First checks the OS's existing ARP cache (same info `arp -a` shows).
    That cache only has entries for hosts this machine has talked to
    recently, so if the MAC isn't there and `allow_ping_sweep` is True, this
    does a quick parallel ping sweep of the local /24 subnet - which makes
    every live host answer an ARP request regardless of whether it responds
    to the ping itself - and checks again.

    Returns the IP as a string, or None if the MAC wasn't found either way.
    """
    if not mac:
        return None
    target = _normalize_mac(mac)

    table = _read_arp_table()
    if target in table:
        return table[target]

    if not allow_ping_sweep:
        return None

    _refresh_arp_cache_via_ping_sweep()
    table = _read_arp_table()
    return table.get(target)
