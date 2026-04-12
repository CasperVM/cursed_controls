from __future__ import annotations

import re
import select
import subprocess
import time

from cursed_controls.discovery import list_devices


def _run_bluetoothctl(*args: str, timeout: float) -> str:
    """Run a single bluetoothctl command and return stdout."""
    try:
        result = subprocess.run(
            ["bluetoothctl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _parse_bluetooth_devices(output: str) -> dict[str, str]:
    devices: dict[str, str] = {}
    for line in output.splitlines():
        m = re.match(r"Device ([0-9A-Fa-f:]{17})\s+(.*)", line)
        if m:
            devices[m.group(1)] = m.group(2).strip()
    return devices


def connect_device(mac: str, timeout: float) -> bool:
    """Pair, trust, and connect a standard Bluetooth device by MAC.

    Returns True if connection was successful.
    """
    _run_bluetoothctl("pair", mac, timeout=timeout + 2)
    _run_bluetoothctl("trust", mac, timeout=5.0)
    out = _run_bluetoothctl("connect", mac, timeout=timeout + 2)
    return "Connection successful" in out


def connect_wiimote(mac: str, timeout: float) -> bool:
    """Connect a Wii Remote using legacy one-shot HID.

    Wiimotes are stateless between power cycles — any stored link key is
    invalid after power-off. We remove the stored bonding first, then scan
    until the device appears advertising (user presses 1+2 or Sync), then
    trust+connect fresh without pairing.

    Returns True if connection was successful.
    """
    import select as _select

    # Remove stale bonding info — old link key causes BlueZ to fail auth
    _run_bluetoothctl("remove", mac, timeout=5.0)
    time.sleep(0.3)

    _run_bluetoothctl("pairable", "on", timeout=5.0)

    _strip = re.compile(r"[\x01\x02]|\x1b\[[0-9;]*m")
    mac_norm = mac.upper().replace(":", "")

    # Scan until the Wiimote appears advertising, then immediately connect
    print(f"[wiimote] Scanning for {mac} (press 1+2 or Sync)…")
    found = False
    try:
        proc = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if proc.stdout is None or proc.stdin is None:
            return False
        proc.stdin.write("scan on\n")
        proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = _select.select([proc.stdout], [], [], 1.0)
            if not ready:
                continue
            raw = proc.stdout.readline()
            if not raw:
                break
            line = _strip.sub("", raw)
            if mac_norm in line.upper().replace(":", ""):
                found = True
                break
        proc.stdin.write("scan off\n")
        proc.stdin.flush()
        proc.terminate()
        proc.wait()
    except (OSError, FileNotFoundError):
        return False

    if not found:
        return False

    # Device is now in the discovery cache — trust, make discoverable, then connect.
    # discoverable on lets the Wiimote see the host and initiate its own HID channels.
    _run_bluetoothctl("trust", mac, timeout=5.0)
    _run_bluetoothctl("discoverable", "on", timeout=5.0)
    out = _run_bluetoothctl("connect", mac, timeout=12.0)
    _run_bluetoothctl("discoverable", "off", timeout=5.0)
    return "Connection successful" in out


def scan_for_wiimote(timeout: float, known_mac: str | None = None) -> str | None:
    """Scan for a Nintendo Wii Remote and return its MAC address.

    If known_mac is provided, returns it directly without scanning.
    Otherwise, starts a bluetoothctl scan and watches for a Nintendo device.
    Uses stdbuf to force line-buffering so output isn't held in a block buffer.
    Returns the MAC address if found, or None if the scan timed out.
    """
    if known_mac is not None:
        return known_mac

    # Check already-known devices first. bluetoothctl only emits the full name
    # on [NEW] lines; re-seen devices only produce [CHG] RSSI lines with no name,
    # so a previously-discovered Wiimote would never match the scan regex below.
    known = _parse_bluetooth_devices(_run_bluetoothctl("devices", timeout=5.0))
    for mac, name in known.items():
        if name.startswith("Nintendo"):
            print(f"Found known Wiimote: {mac}")
            return mac

    # Put adapter in pairable mode so the Wiimote can be accepted
    _run_bluetoothctl("pairable", "on", timeout=5.0)

    try:
        proc = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if proc.stdout is None or proc.stdin is None:
            return None
        proc.stdin.write("scan on\n")
        proc.stdin.flush()

        _strip = re.compile(r"[\x01\x02]|\x1b\[[0-9;]*m")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if not ready:
                known = _parse_bluetooth_devices(_run_bluetoothctl("devices", timeout=5.0))
                for mac, name in known.items():
                    if name.startswith("Nintendo"):
                        proc.stdin.write("scan off\n")
                        proc.stdin.flush()
                        proc.terminate()
                        proc.wait()
                        return mac
                continue
            raw = proc.stdout.readline()
            if not raw:
                known = _parse_bluetooth_devices(_run_bluetoothctl("devices", timeout=5.0))
                for mac, name in known.items():
                    if name.startswith("Nintendo"):
                        proc.stdin.write("scan off\n")
                        proc.stdin.flush()
                        proc.terminate()
                        proc.wait()
                        return mac
                continue
            line = _strip.sub("", raw)
            m = re.search(r"Device ([0-9A-Fa-f:]{17}) Nintendo", line)
            if m:
                proc.stdin.write("scan off\n")
                proc.stdin.flush()
                proc.terminate()
                proc.wait()
                return m.group(1)

        proc.stdin.write("scan off\n")
        proc.stdin.flush()
        proc.terminate()
        proc.wait()
    except (OSError, FileNotFoundError):
        pass
    return None


def auto_connect_wiimote(timeout_s: float = 60.0) -> None:
    """Scan for and connect a Wiimote if not already present in evdev.

    Used by interactive tools (map, show_axis_range) before showing a device menu.
    Safe to call when already connected — returns immediately.
    """
    if any("Nintendo Wii Remote" in d.name for d in list_devices()):
        print("Wiimote already connected.")
        return
    print(f"Scanning for Wiimote (press 1+2 or Sync)...")
    mac = scan_for_wiimote(timeout_s)
    if mac:
        print(f"Connecting {mac}...")
        connect_wiimote(mac, timeout=10.0)
        if wait_for_evdev("Nintendo Wii Remote", timeout=10.0):
            print("Wiimote ready.")
        else:
            print("Connected but evdev node not found yet, continuing.")
    else:
        print("No Wiimote found, continuing without.")


def wait_for_evdev(name: str, timeout: float) -> bool:
    """Poll list_devices() until a device with the given name appears.

    Returns True if found within timeout seconds, False otherwise.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(d.name == name for d in list_devices()):
            return True
        time.sleep(0.5)
    return False


def is_device_connected(mac: str) -> bool:
    """Return True if bluetoothctl reports the device as currently connected."""
    out = _run_bluetoothctl("info", mac, timeout=5.0)
    return "Connected: yes" in out


def reconnect_bluetooth(
    mac: str,
    is_wiimote: bool,
    timeout: float,
    max_retries: int = 5,
    backoff: float = 2.0,
) -> bool:
    """Attempt to reconnect a Bluetooth device.

    For Wiimotes: runs a single scan window (remove → scan → trust → connect).
    The scan window is sized to cover all retry budget so the user only needs
    to press 1+2 once during the window.

    For standard BT devices: bounded retries with backoff.
    """
    if is_wiimote:
        scan_window = timeout * max_retries + backoff * (max_retries - 1)
        return connect_wiimote(mac, timeout=scan_window)

    connect_fn = connect_device
    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(backoff)
        print(f"Reconnect attempt {attempt + 1}/{max_retries} for {mac}...")
        if connect_fn(mac, timeout=timeout):
            return True
    return False
