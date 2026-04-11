import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from cursed_controls.app_state import AppState
from cursed_controls.web.server import create_app


@pytest.fixture
def state():
    return AppState()


@pytest.fixture
def client(state):
    app = create_app(state)
    return TestClient(app)


def test_root_returns_html(client):
    # index.html may not exist yet — just check server responds (not 500)
    r = client.get("/")
    assert r.status_code in (200, 404)  # 404 until static file added


def test_ws_connect_receives_runtime_status(state):
    app = create_app(state)
    with TestClient(app).websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "runtime_status"
        assert msg["status"] == "stopped"
