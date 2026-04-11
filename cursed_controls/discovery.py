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
    except ValueError:
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
    except OSError:
        pass
    return parent, bool(parent), is_parent


def list_devices() -> list[DiscoveredDevice]:
    devices: list[DiscoveredDevice] = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue  # device disappeared between listing and opening
        try:
            phys = dev.phys or ""
            name = dev.name or ""
            name_lower = name.lower()
            if "hdmi" in phys.lower() or "hdmi" in name_lower:
                continue  # skip vc4-hdmi and similar display devices
            if any(
                kw in name_lower
                for kw in (" imu", "accelerometer", "motion sensor", "gyro")
            ):
                continue  # skip IMU/motion sensor nodes (e.g. hid-nintendo IMU)
            parent, is_comp, is_parent = _parent_info(path)
            devices.append(
                DiscoveredDevice(
                    path=path,
                    name=name,
                    uniq=dev.uniq or "",
                    phys=phys,
                    parent_uhid=parent,
                    is_composite=is_comp,
                    is_composite_parent=is_parent,
                )
            )
        finally:
            dev.close()
    return devices
