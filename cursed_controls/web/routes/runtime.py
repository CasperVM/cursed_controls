import subprocess

from fastapi import APIRouter, Depends, HTTPException

from cursed_controls.app_state import AppState
from cursed_controls.web.deps import get_state, get_runtime_manager

router = APIRouter()

_SERVICE_NAME = "cursed-controls-web.service"


@router.post("/service/restart")
def restart_service():
    """Restart the systemd service. Reinitialises the gadget and reconnects all devices."""
    try:
        subprocess.Popen(
            ["systemctl", "restart", _SERVICE_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"systemctl failed: {e}")
    return {"ok": True}
