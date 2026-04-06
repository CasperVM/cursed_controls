from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

import evdev


@dataclass
class DiscoveredDevice:
    path: str
    name: str
    uniq: str
    phys: str
    parent_uhid: str | None
    is_composite: bool
    is_composite_parent: bool

    @property
    def identifier(self) -> str:
        return self.uniq or self.phys or self.name or self.path


def _parent_info(event_path: str) -> tuple[str | None, bool, bool]:
    event_sys = Path("/sys/class/input") / Path(event_path).name / "device"
    event_real = os.path.realpath(str(event_sys))
    parts = event_real.split("/")
    parent = None
    try:
        parent = parts[parts.index("uhid") + 1]
    except Exception:
        parent = None
    is_parent = parent is None
    try:
        if parent:
            uhid_input_path = Path(f"/sys/devices/virtual/misc/uhid/{parent}/input")
            if uhid_input_path.is_dir():
                inputs = sorted(os.listdir(uhid_input_path))
                first = inputs[0] if inputs else None
                if (
                    first
                    and os.path.realpath(str(uhid_input_path / first)) == event_real
                ):
                    is_parent = True
    except Exception:
        pass
    return parent, bool(parent), is_parent


def list_devices() -> list[DiscoveredDevice]:
    devices: list[DiscoveredDevice] = []
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        parent, is_comp, is_parent = _parent_info(path)
        devices.append(
            DiscoveredDevice(
                path=path,
                name=dev.name or "",
                uniq=dev.uniq or "",
                phys=dev.phys or "",
                parent_uhid=parent,
                is_composite=is_comp,
                is_composite_parent=is_parent,
            )
        )
    return devices
