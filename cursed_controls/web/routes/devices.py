from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from cursed_controls.app_state import AppState
from cursed_controls.discovery import list_devices
from cursed_controls.web.deps import get_state, get_runtime_manager

router = APIRouter()


@router.get("/devices")
def get_devices(
    state: AppState = Depends(get_state),
    manager=Depends(get_runtime_manager),
) -> list[dict]:
    devices = list_devices()
    with state._lock:
        statuses = list(state.device_statuses.values())
    ff_status = manager.get_ff_status()
    result = []
    for d in devices:
        row = asdict(d)
        profile_id = next(
            (
                s.profile_id
                for s in statuses
                if s.path == d.path and s.status == "bound"
            ),
            None,
        )
        row["bound_profile"] = profile_id
        row["has_ff"] = ff_status.get(profile_id, False) if profile_id else False
        result.append(row)
    return result


@router.post("/devices/{profile_id}/rumble_test")
def rumble_test(profile_id: str, manager=Depends(get_runtime_manager)):
    ok = manager.rumble_test(profile_id)
    if not ok:
        raise HTTPException(
            status_code=409, detail="device not bound or no FF capability"
        )
    return {"ok": True}
