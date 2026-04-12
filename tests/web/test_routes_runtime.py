import subprocess

import pytest
from fastapi.testclient import TestClient

from cursed_controls.app_state import AppState
from cursed_controls.web.server import create_app


@pytest.fixture
def state():
    return AppState()


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def test_restart_service_returns_200(client, monkeypatch):
    called = {}

    class DummyProc:
        pass

    def fake_popen(args, stdout=None, stderr=None):
        called["args"] = args
        called["stdout"] = stdout
        called["stderr"] = stderr
        return DummyProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    r = client.post("/api/service/restart")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert called["args"] == [
        "systemctl",
        "restart",
        "cursed-controls-web.service",
    ]
    assert called["stdout"] is subprocess.DEVNULL
    assert called["stderr"] is subprocess.DEVNULL


def test_restart_service_returns_500_on_oserror(client, monkeypatch):
    def fake_popen(args, stdout=None, stderr=None):
        raise OSError("boom")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    r = client.post("/api/service/restart")
    assert r.status_code == 500
    assert "systemctl failed: boom" in r.text
