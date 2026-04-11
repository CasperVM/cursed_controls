from dataclasses import asdict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cursed_controls.app_state import AppState
from cursed_controls.discovery import DiscoveredDevice
from cursed_controls.web.server import create_app


def _dev(name="TestPad", path="/dev/input/event0"):
    return DiscoveredDevice(
        path=path,
        name=name,
        uniq="",
        phys="",
        parent_uhid=None,
        is_composite=False,
        is_composite_parent=True,
    )


@pytest.fixture
def client():
    return TestClient(create_app(AppState()))


def test_list_devices_returns_list(client):
    with patch(
        "cursed_controls.web.routes.devices.list_devices", return_value=[_dev()]
    ):
        r = client.get("/api/devices")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["name"] == "TestPad"


def test_list_devices_empty(client):
    with patch("cursed_controls.web.routes.devices.list_devices", return_value=[]):
        r = client.get("/api/devices")
    assert r.status_code == 200
    assert r.json() == []


def test_list_devices_has_bound_profile_field(client):
    """Device entries include bound_profile field (None when no runtime)."""
    with patch(
        "cursed_controls.web.routes.devices.list_devices", return_value=[_dev()]
    ):
        r = client.get("/api/devices")
    assert r.status_code == 200
    data = r.json()
    assert "bound_profile" in data[0]
    assert data[0]["bound_profile"] is None
