import io
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from cursed_controls.app_state import AppState
from cursed_controls.web.server import create_app

_VALID_YAML = """\
runtime:
  output_mode: stdout
devices:
  - id: testpad
    match:
      name: TestPad
    mappings: []
"""

_INVALID_YAML = "{ bad yaml: [unclosed"


@pytest.fixture
def state():
    return AppState()


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def test_get_config_null_when_empty(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    assert r.json() is None


def test_put_config_valid_yaml(client, state):
    r = client.put(
        "/api/config", content=_VALID_YAML, headers={"Content-Type": "text/yaml"}
    )
    assert r.status_code == 200
    assert state.config is not None
    assert state.config.devices[0].id == "testpad"


def test_put_config_invalid_returns_422(client):
    r = client.put(
        "/api/config", content=_INVALID_YAML, headers={"Content-Type": "text/yaml"}
    )
    assert r.status_code == 422


def test_export_returns_yaml_file(client, state):
    import yaml
    import tempfile, os
    from cursed_controls.config import load_config

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(_VALID_YAML)
        fname = f.name
    try:
        state.config = load_config(fname)
    finally:
        os.unlink(fname)

    r = client.get("/api/config/export")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    body = r.text
    loaded = yaml.safe_load(body)
    assert "devices" in loaded


def test_import_yaml_file(client, state):
    r = client.post(
        "/api/config/import",
        files={"file": ("mapping.yaml", _VALID_YAML.encode(), "text/yaml")},
    )
    assert r.status_code == 200
    assert state.config is not None


def test_import_invalid_yaml_returns_422(client):
    r = client.post(
        "/api/config/import",
        files={"file": ("bad.yaml", _INVALID_YAML.encode(), "text/yaml")},
    )
    assert r.status_code == 422


def test_get_config_when_loaded(client, state):
    """GET /config returns config as JSON dict when config is loaded."""
    import tempfile, os
    from cursed_controls.config import load_config

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(_VALID_YAML)
        fname = f.name
    try:
        state.config = load_config(fname)
    finally:
        os.unlink(fname)
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)
    assert "devices" in data
    assert data["devices"][0]["id"] == "testpad"


def test_export_config_null_returns_404(client):
    """GET /config/export returns 404 when no config loaded."""
    r = client.get("/api/config/export")
    assert r.status_code == 404
