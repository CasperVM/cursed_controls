"""Tests for cursed_controls.bluetooth (no hardware required)."""

from io import StringIO
from unittest.mock import MagicMock, patch

from cursed_controls.bluetooth import (
    connect_device,
    is_device_connected,
    reconnect_bluetooth,
    scan_for_wiimote,
    wait_for_evdev,
)
from cursed_controls.discovery import DiscoveredDevice


def _make_discovered(name: str) -> DiscoveredDevice:
    return DiscoveredDevice(
        path="/dev/input/event0",
        name=name,
        uniq="",
        phys="",
        parent_uhid=None,
        is_composite=False,
        is_composite_parent=False,
    )


# ---------------------------------------------------------------------------
# connect_device
# ---------------------------------------------------------------------------


def test_connect_device_returns_true_on_success():
    # pair → "", trust → "", connect → "Connection successful"
    responses = [
        "",
        "",
        "Attempting to connect to AA:BB:CC:DD:EE:FF\nConnection successful\n",
    ]

    def side_effect(*args, **kwargs):
        r = MagicMock()
        r.stdout = responses.pop(0) if responses else ""
        return r

    with patch("cursed_controls.bluetooth.subprocess.run", side_effect=side_effect):
        assert connect_device("AA:BB:CC:DD:EE:FF", timeout=5.0) is True


def test_connect_device_returns_false_on_failure():
    def side_effect(*args, **kwargs):
        r = MagicMock()
        r.stdout = "Failed to connect: org.bluez.Error.Failed\n"
        return r

    with patch("cursed_controls.bluetooth.subprocess.run", side_effect=side_effect):
        assert connect_device("AA:BB:CC:DD:EE:FF", timeout=5.0) is False


def test_connect_device_returns_false_on_timeout():
    import subprocess

    with patch(
        "cursed_controls.bluetooth.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="bluetoothctl", timeout=7),
    ):
        assert connect_device("AA:BB:CC:DD:EE:FF", timeout=5.0) is False


# ---------------------------------------------------------------------------
# scan_for_wiimote
# ---------------------------------------------------------------------------


def test_scan_for_wiimote_returns_known_mac_immediately():
    # If known_mac provided, no subprocess is launched.
    with patch("cursed_controls.bluetooth.subprocess.Popen") as mock_popen:
        result = scan_for_wiimote(timeout=30.0, known_mac="AA:BB:CC:DD:EE:FF")
    assert result == "AA:BB:CC:DD:EE:FF"
    mock_popen.assert_not_called()


def _mock_run(stdout=""):
    """Return a mock subprocess.run result with given stdout."""
    r = MagicMock()
    r.stdout = stdout
    return r


def test_scan_for_wiimote_finds_nintendo_device():
    lines = [
        "Discovery started\n",
        "[CHG] Controller AA:BB:CC:DD:EE:FF Discovering: yes\n",
        "[NEW] Device 11:22:33:44:55:66 Nintendo RVL-CNT-01\n",
        "[NEW] Device 77:88:99:AA:BB:CC Some Other Device\n",
    ]
    line_iter = iter(lines)

    mock_stdout = MagicMock()
    mock_stdout.readline = lambda: next(line_iter, "")

    mock_proc = MagicMock()
    mock_proc.stdout = mock_stdout
    mock_proc.terminate = MagicMock()
    mock_proc.wait = MagicMock()

    def fake_select(rlist, wlist, xlist, timeout=None):
        return rlist, [], []

    with (
        patch("cursed_controls.bluetooth.subprocess.run", return_value=_mock_run()),
        patch("cursed_controls.bluetooth.subprocess.Popen", return_value=mock_proc),
        patch("cursed_controls.bluetooth.select.select", side_effect=fake_select),
    ):
        result = scan_for_wiimote(timeout=10.0)

    assert result == "11:22:33:44:55:66"
    mock_proc.terminate.assert_called_once()


def test_scan_for_wiimote_returns_none_when_no_nintendo_found():
    scan_output = (
        "Discovery started\n[NEW] Device 77:88:99:AA:BB:CC Some Other Device\n"
    )
    mock_proc = MagicMock()
    # After the two lines, readline returns "" (EOF)
    lines = iter(scan_output.splitlines(keepends=True))

    def fake_readline():
        return next(lines, "")

    mock_proc.stdout.readline = fake_readline
    mock_proc.wait = MagicMock()
    mock_proc.terminate = MagicMock()

    import select as _select

    def fake_select(rlist, wlist, xlist, timeout=None):
        return rlist, [], []

    with (
        patch("cursed_controls.bluetooth.subprocess.run", return_value=_mock_run()),
        patch("cursed_controls.bluetooth.subprocess.Popen", return_value=mock_proc),
        patch("cursed_controls.bluetooth.select.select", side_effect=fake_select),
        patch(
            "cursed_controls.bluetooth.time.monotonic",
            side_effect=[0, 0, 1, 1, 2, 2, 99],
        ),
    ):
        result = scan_for_wiimote(timeout=1.5)

    assert result is None


# ---------------------------------------------------------------------------
# wait_for_evdev
# ---------------------------------------------------------------------------


def test_wait_for_evdev_finds_device():
    wiimote = _make_discovered("Nintendo Wii Remote")
    with (
        patch("cursed_controls.bluetooth.list_devices", return_value=[wiimote]),
        patch("cursed_controls.bluetooth.time.sleep"),
    ):
        assert wait_for_evdev("Nintendo Wii Remote", timeout=5.0) is True


# ---------------------------------------------------------------------------
# is_device_connected
# ---------------------------------------------------------------------------


def test_is_device_connected_returns_true_when_yes():
    with patch(
        "cursed_controls.bluetooth.subprocess.run",
        return_value=_mock_run(
            "Device AA:BB:CC:DD:EE:FF (public)\n\tConnected: yes\n\tPaired: yes\n"
        ),
    ):
        assert is_device_connected("AA:BB:CC:DD:EE:FF") is True


def test_is_device_connected_returns_false_when_no():
    with patch(
        "cursed_controls.bluetooth.subprocess.run",
        return_value=_mock_run(
            "Device AA:BB:CC:DD:EE:FF (public)\n\tConnected: no\n\tPaired: yes\n"
        ),
    ):
        assert is_device_connected("AA:BB:CC:DD:EE:FF") is False


def test_is_device_connected_returns_false_on_empty_output():
    with patch(
        "cursed_controls.bluetooth.subprocess.run",
        return_value=_mock_run(""),
    ):
        assert is_device_connected("AA:BB:CC:DD:EE:FF") is False


# ---------------------------------------------------------------------------
# reconnect_bluetooth
# ---------------------------------------------------------------------------


def test_reconnect_bluetooth_returns_true_on_first_attempt():
    with patch(
        "cursed_controls.bluetooth.connect_wiimote", return_value=True
    ) as mock_conn:
        result = reconnect_bluetooth(
            "AA:BB:CC:DD:EE:FF", is_wiimote=True, timeout=5.0, max_retries=3
        )
    assert result is True
    assert mock_conn.call_count == 1


def test_reconnect_bluetooth_retries_and_succeeds():
    # Wiimotes use a single connect_wiimote call with a combined scan window,
    # not individual retries, so we only expect one call.
    with (
        patch(
            "cursed_controls.bluetooth.connect_wiimote", return_value=True
        ) as mock_conn,
        patch("cursed_controls.bluetooth.time.sleep"),
    ):
        result = reconnect_bluetooth(
            "AA:BB:CC:DD:EE:FF", is_wiimote=True, timeout=5.0, max_retries=3
        )
    assert result is True
    assert mock_conn.call_count == 1


def test_reconnect_bluetooth_returns_false_after_max_retries():
    with (
        patch("cursed_controls.bluetooth.connect_device", return_value=False),
        patch("cursed_controls.bluetooth.time.sleep"),
    ):
        result = reconnect_bluetooth(
            "AA:BB:CC:DD:EE:FF", is_wiimote=False, timeout=5.0, max_retries=3
        )
    assert result is False


def test_reconnect_bluetooth_uses_connect_device_for_non_wiimote():
    with (
        patch("cursed_controls.bluetooth.connect_device", return_value=True) as mock_bt,
        patch("cursed_controls.bluetooth.connect_wiimote") as mock_wii,
    ):
        reconnect_bluetooth(
            "AA:BB:CC:DD:EE:FF", is_wiimote=False, timeout=5.0, max_retries=1
        )
    mock_bt.assert_called_once()
    mock_wii.assert_not_called()


def test_wait_for_evdev_times_out():
    import time as _time

    calls = [0]
    start = _time.monotonic()

    def fake_monotonic():
        # Advance time by 1 second each call to force timeout quickly
        calls[0] += 1
        return start + calls[0]

    with (
        patch("cursed_controls.bluetooth.list_devices", return_value=[]),
        patch("cursed_controls.bluetooth.time.monotonic", side_effect=fake_monotonic),
        patch("cursed_controls.bluetooth.time.sleep"),
    ):
        assert wait_for_evdev("Nintendo Wii Remote", timeout=2.0) is False
