import sys
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from cursed_controls.app_state import AppState
from cursed_controls.web.routes.bluetooth import _do_scan
from cursed_controls.web.server import create_app


@pytest.fixture
def client():
    return TestClient(create_app(AppState()))


def test_bt_scan_returns_200(client):
    with patch("cursed_controls.web.routes.bluetooth._do_scan"):
        r = client.post("/api/bt/scan")
    assert r.status_code == 200


def test_bt_connect_calls_connect_device(client):
    with patch(
        "cursed_controls.web.routes.bluetooth.connect_device", return_value=True
    ) as mock_cd:
        r = client.post("/api/bt/connect", json={"mac": "AA:BB:CC:DD:EE:FF"})
    assert r.status_code == 200
    mock_cd.assert_called_once_with("AA:BB:CC:DD:EE:FF", timeout=30.0)


def test_bt_connect_missing_mac_returns_422(client):
    r = client.post("/api/bt/connect", json={})
    assert r.status_code == 422


def test_bt_scan_dispatches_background_work(client):
    with patch("cursed_controls.web.routes.bluetooth._do_scan") as mock_scan:
        r = client.post("/api/bt/scan")
    assert r.status_code == 200
    mock_scan.assert_called_once()


def test_bt_connect_returns_ok_false_on_failure(client):
    with patch(
        "cursed_controls.web.routes.bluetooth.connect_device", return_value=False
    ):
        r = client.post("/api/bt/connect", json={"mac": "AA:BB:CC:DD:EE:FF"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_bt_scan_polls_devices_when_no_live_events_arrive():
    state = AppState()
    state.broadcast = MagicMock()

    mock_proc = MagicMock()
    mock_proc.stdout.readline = lambda: ""
    mock_proc.wait = MagicMock()
    mock_proc.terminate = MagicMock()

    outputs = [
        "",
        "Device AA:BB:CC:DD:EE:FF Xbox Wireless Controller\n",
    ]
    last_output = outputs[-1]

    def fake_check_output(*args, **kwargs):
        return outputs.pop(0) if outputs else last_output

    fake_subprocess = MagicMock()
    fake_subprocess.check_output.side_effect = fake_check_output
    fake_subprocess.Popen.return_value = mock_proc
    fake_subprocess.CalledProcessError = RuntimeError

    fake_select = MagicMock()
    fake_select.select.return_value = ([], [], [])

    fake_time = MagicMock()
    fake_time.monotonic.side_effect = [0.0, 0.0, 0.4, 0.4, 31.0]

    patched_modules = dict(sys.modules)
    patched_modules["subprocess"] = fake_subprocess
    patched_modules["select"] = fake_select
    patched_modules["time"] = fake_time

    with (
        patch.dict(sys.modules, patched_modules, clear=False),
    ):
        _do_scan(state)

    assert any(
        call.args[0].get("event") == "found"
        and call.args[0].get("mac") == "AA:BB:CC:DD:EE:FF"
        for call in state.broadcast.call_args_list
    )
