from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from cursed_controls.config import AppConfig

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import Response

from cursed_controls.app_state import AppState
from cursed_controls.config import AppConfig, load_config
from cursed_controls.web.deps import get_state

router = APIRouter()


def _config_to_yaml(config: AppConfig) -> str:
    """Serialize AppConfig to a YAML string that load_config can round-trip."""
    data: dict[str, Any] = {}

    rt = config.runtime
    rt_dict: dict[str, Any] = {
        "output_mode": rt.output_mode,
        "poll_interval_ms": rt.poll_interval_ms,
        "gadget_library": rt.gadget_library,
        "interfaces": rt.interfaces,
        "rumble": rt.rumble,
        "rescan_interval_ms": rt.rescan_interval_ms,
        "rumble_timeout_s": rt.rumble_timeout_s,
        "rumble_heartbeat_s": rt.rumble_heartbeat_s,
        "rumble_stop_debounce_s": rt.rumble_stop_debounce_s,
        "rumble_activate_count": rt.rumble_activate_count,
        "rumble_activate_window_s": rt.rumble_activate_window_s,
    }
    if rt.gadget_driver:
        rt_dict["gadget_driver"] = rt.gadget_driver
    if rt.gadget_device:
        rt_dict["gadget_device"] = rt.gadget_device
    data["runtime"] = rt_dict

    data["devices"] = []
    for dev in config.devices:
        d: dict[str, Any] = {"id": dev.id}
        if dev.slot != 0:
            d["slot"] = dev.slot
        if not dev.rumble:
            d["rumble"] = False

        match: dict[str, Any] = {}
        if dev.match.name:
            match["name"] = dev.match.name
        if dev.match.uniq:
            match["uniq"] = dev.match.uniq
        if dev.match.phys:
            match["phys"] = dev.match.phys
        d["match"] = match

        conn = dev.connection
        if conn.type.value != "evdev":
            conn_dict: dict[str, Any] = {"type": conn.type.value}
            if conn.mac:
                conn_dict["mac"] = conn.mac
            if conn.timeout_s != 30.0:
                conn_dict["timeout_s"] = conn.timeout_s
            d["connection"] = conn_dict

        mappings = []
        for m in dev.mappings:
            row: dict[str, Any] = {
                "source_type": m.source_type,
                "source_code": m.source_code,
                "target": m.target.value,
                "kind": m.transform.kind.value,
            }
            if m.label:
                row["label"] = m.label
            if m.transform.deadzone:
                row["deadzone"] = m.transform.deadzone
            if m.transform.invert:
                row["invert"] = True
            if m.transform.threshold != 1:
                row["threshold"] = m.transform.threshold
            if m.transform.on_value is not None:
                row["on_value"] = m.transform.on_value
            if m.transform.off_value is not None:
                row["off_value"] = m.transform.off_value
            if m.transform.source_min is not None:
                row["source_min"] = m.transform.source_min
            if m.transform.source_max is not None:
                row["source_max"] = m.transform.source_max
            if m.transform.target_min is not None:
                row["target_min"] = m.transform.target_min
            if m.transform.target_max is not None:
                row["target_max"] = m.transform.target_max
            mappings.append(row)
        d["mappings"] = mappings
        data["devices"].append(d)

    return yaml.dump(
        data, default_flow_style=False, sort_keys=False, allow_unicode=True
    )


def _normalize_enums(obj: Any) -> None:
    """Recursively convert Enum values to their .value strings in-place."""
    from enum import Enum

    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, Enum):
                obj[k] = v.value
            else:
                _normalize_enums(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, Enum):
                obj[i] = v.value
            else:
                _normalize_enums(v)


def _load_from_text(text: str, suffix: str = ".yaml") -> AppConfig:
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as f:
        f.write(text)
        fname = f.name
    try:
        return load_config(fname)
    finally:
        os.unlink(fname)


@router.get("/config")
def get_config(state: AppState = Depends(get_state)):
    if state.config is None:
        return None
    # Use the canonical YAML serializer so the returned structure matches what
    # load_config (used by PUT) expects — flat mapping fields, no nested transform.
    return yaml.safe_load(_config_to_yaml(state.config))


@router.put("/config", status_code=200)
async def put_config(request: Request, state: AppState = Depends(get_state)):
    body = await request.body()
    content_type = request.headers.get("content-type", "text/yaml")
    suffix = ".json" if "json" in content_type else ".yaml"
    try:
        config = _load_from_text(body.decode(), suffix=suffix)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    state.config = config
    _persist(state, config)
    return {"ok": True}


@router.get("/config/export")
def export_config(state: AppState = Depends(get_state)):
    if state.config is None:
        raise HTTPException(status_code=404, detail="no config loaded")
    text = _config_to_yaml(state.config)
    return Response(
        content=text,
        media_type="text/yaml",
        headers={"Content-Disposition": 'attachment; filename="mapping.yaml"'},
    )


@router.post("/config/import", status_code=200)
async def import_config(
    file: UploadFile = File(...),
    state: AppState = Depends(get_state),
):
    content = await file.read()
    suffix = ".json" if (file.filename or "").endswith(".json") else ".yaml"
    try:
        config = _load_from_text(content.decode(), suffix=suffix)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    state.config = config
    _persist(state, config)
    return {"ok": True}


def _persist(state: AppState, config: "AppConfig") -> None:
    """Write config back to the file it was loaded from, if known."""
    if not state.config_path:
        return
    try:
        Path(state.config_path).write_text(_config_to_yaml(config))
    except OSError as e:
        print(f"[config] failed to persist to {state.config_path}: {e}")
