import pytest
from fastapi.testclient import TestClient

from cursed_controls.app_state import AppState
from cursed_controls.config import AppConfig, RuntimeConfig
from cursed_controls.web.server import create_app
from cursed_controls.output import FakeSink


def _minimal_config():
    return AppConfig(runtime=RuntimeConfig(output_mode="stdout"), devices=[])


@pytest.fixture
def state():
    return AppState()


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def test_start_runtime_no_config_returns_422(client):
    r = client.post("/api/runtime/start")
    assert r.status_code == 422


def test_start_runtime_with_config_returns_200(client, state):
    state.config = _minimal_config()
    r = client.post("/api/runtime/start")
    assert r.status_code == 200
    assert state.runtime_status == "running"
    # cleanup
    client.post("/api/runtime/stop")


def test_stop_runtime(client, state):
    state.config = _minimal_config()
    client.post("/api/runtime/start")
    r = client.post("/api/runtime/stop")
    assert r.status_code == 200
    assert state.runtime_status == "stopped"


def test_stop_runtime_when_never_started(client):
    """Stopping runtime that was never started should return 200 cleanly."""
    r = client.post("/api/runtime/stop")
    assert r.status_code == 200
