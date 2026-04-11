from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request

from cursed_controls.app_state import AppState
from cursed_controls.web.deps import get_state

router = APIRouter()

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


def _presets_dir(state: AppState) -> Path | None:
    if not state.config_path:
        return None
    return Path(state.config_path).parent / "presets"


@router.get("/presets")
def list_presets(state: AppState = Depends(get_state)):
    d = _presets_dir(state)
    if d is None or not d.exists():
        return []
    result = []
    for f in sorted(d.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text()) or {}
            result.append(
                {
                    "name": f.stem,
                    "display_name": data.get("display_name", f.stem),
                    "match": data.get("match", {}),
                }
            )
        except Exception:
            pass
    return result


@router.get("/presets/hint")
def get_hint(
    device_path: str,
    source_type: int,
    source_code: int,
    state: AppState = Depends(get_state),
):
    """Return a suggested label for a (device, source_type, source_code) from matching presets."""
    d = _presets_dir(state)
    if d is None or not d.exists():
        return {"label": None}

    device_name = ""
    try:
        import evdev

        dev = evdev.InputDevice(device_path)
        device_name = dev.name
        dev.close()
    except Exception:
        return {"label": None}

    for f in sorted(d.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text()) or {}
            name_pattern = (data.get("match") or {}).get("name", "")
            if name_pattern and name_pattern.lower() not in device_name.lower():
                continue
            for m in data.get("mappings", []):
                if (
                    m.get("source_type") == source_type
                    and m.get("source_code") == source_code
                ):
                    label = m.get("label")
                    if label:
                        return {"label": label}
        except Exception:
            pass

    return {"label": None}


@router.get("/presets/{name}")
def get_preset(name: str, state: AppState = Depends(get_state)):
    if not _SAFE_NAME.match(name):
        raise HTTPException(status_code=400, detail="Invalid preset name")
    d = _presets_dir(state)
    if d is None:
        raise HTTPException(status_code=503, detail="No config loaded")
    path = d / f"{name}.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Preset not found")
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/presets/{name}", status_code=200)
async def save_preset(
    name: str, request: Request, state: AppState = Depends(get_state)
):
    if not _SAFE_NAME.match(name):
        raise HTTPException(status_code=400, detail="Invalid preset name")
    d = _presets_dir(state)
    if d is None:
        raise HTTPException(status_code=503, detail="No config loaded")
    d.mkdir(exist_ok=True)
    body = await request.json()
    path = d / f"{name}.yaml"
    try:
        path.write_text(
            yaml.dump(
                body, default_flow_style=False, sort_keys=False, allow_unicode=True
            )
        )
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "name": name}
