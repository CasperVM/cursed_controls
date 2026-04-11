from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from cursed_controls.app_state import AppState
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
    mock_cd.assert_called_once_with("AA:BB:CC:DD:EE:FF", timeout=15.0)


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
