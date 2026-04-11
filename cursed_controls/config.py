from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
import json

import yaml

from cursed_controls.xbox import Surface


class TransformKind(str, Enum):
    BUTTON = "button"
    AXIS = "axis"
    HAT = "hat"


class ConnectionType(str, Enum):
    EVDEV = "evdev"  # already present in /dev/input (default)
    BLUETOOTH = "bluetooth"  # paired device, connect by MAC at startup
    WIIMOTE = "wiimote"  # scan for first Nintendo Wii Remote


@dataclass
class ConnectionConfig:
    type: ConnectionType = ConnectionType.EVDEV
    mac: str | None = None  # required for bluetooth, optional for wiimote
    timeout_s: float = 30.0  # seconds to scan/wait before giving up


@dataclass
class DeviceMatch:
    name: str | None = None
    uniq: str | None = None
    phys: str | None = None


@dataclass
class Transform:
    kind: TransformKind
    deadzone: float = 0.0
    invert: bool = False
    threshold: int = 1
    on_value: int | None = None
    off_value: int | None = None
    source_min: int | None = None
    source_max: int | None = None
    target_min: int | None = None
    target_max: int | None = None


@dataclass
class MappingRule:
    source_type: int
    source_code: int
    target: Surface
    transform: Transform
    label: str | None = None


@dataclass
class DeviceProfile:
    id: str
    match: DeviceMatch
    mappings: list[MappingRule] = field(default_factory=list)
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    slot: int = 0  # output slot index 0–3 (displayed as 1–4 in UI)
    rumble: bool = True  # forward host rumble to this device


@dataclass
class RuntimeConfig:
    poll_interval_ms: int = 1
    output_mode: str = "stdout"
    gadget_library: str = "360-w-raw-gadget/target/release/libx360_w_raw_gadget.so"
    gadget_driver: str | None = None  # None = auto-detect from /sys/class/udc/
    gadget_device: str | None = None  # None = same as gadget_driver
    interfaces: int = 1
    rumble: bool = True  # forward host rumble to physical devices
    rescan_interval_ms: int = 2000  # how often to retry pending profiles
    # Rumble tuning
    rumble_timeout_s: float = 0.5  # stop rumble if no packet received for this long
    rumble_heartbeat_s: float = 0.05  # re-send EV_FF interval for Nintendo controllers
    rumble_stop_debounce_s: float = (
        0.4  # delay stop after (0,0) in case ON follows shortly
    )
    rumble_activate_count: int = (
        2  # non-zero packets required to (re)activate from stopped
    )
    rumble_activate_window_s: float = 4.0  # time window for counting activation packets


@dataclass
class AppConfig:
    runtime: RuntimeConfig
    devices: list[DeviceProfile]


def _surface(value: str) -> Surface:
    return Surface[value] if value in Surface.__members__ else Surface(value)


def patch_profile_mac(path: str | Path, profile_id: str, mac: str) -> None:
    """Update the MAC address for a specific profile in the config file in-place.

    Uses load → modify dict → dump so we only touch the mac field.
    """
    p = Path(path)
    data = yaml.safe_load(p.read_text()) or {}
    for device in data.get("devices", []):
        if device.get("id") == profile_id:
            if "connection" not in device:
                device["connection"] = {}
            device["connection"]["mac"] = mac
            break
    p.write_text(yaml.safe_dump(data, default_flow_style=False, allow_unicode=True))


def load_config(path: str | Path) -> AppConfig:
    data: dict[str, Any]
    raw = Path(path).read_text()
    if str(path).endswith(".json"):
        data = json.loads(raw)
    else:
        data = yaml.safe_load(raw)
    runtime = RuntimeConfig(**data.get("runtime", {}))
    devices = []
    for device in data.get("devices", []):
        mappings = []
        for mapping in device.get("mappings", []):
            mappings.append(
                MappingRule(
                    source_type=mapping["source_type"],
                    source_code=mapping["source_code"],
                    target=_surface(mapping["target"]),
                    label=mapping.get("label"),
                    transform=Transform(
                        kind=TransformKind(mapping.get("kind", "button")),
                        deadzone=mapping.get("deadzone", 0.0),
                        invert=mapping.get("invert", False),
                        threshold=mapping.get("threshold", 1),
                        on_value=mapping.get("on_value"),
                        off_value=mapping.get("off_value"),
                        source_min=mapping.get("source_min"),
                        source_max=mapping.get("source_max"),
                        target_min=mapping.get("target_min"),
                        target_max=mapping.get("target_max"),
                    ),
                )
            )
        conn_data = device.get("connection", {})
        connection = ConnectionConfig(
            type=ConnectionType(conn_data.get("type", ConnectionType.EVDEV)),
            mac=conn_data.get("mac"),
            timeout_s=conn_data.get("timeout_s", 30.0),
        )
        devices.append(
            DeviceProfile(
                id=device["id"],
                match=DeviceMatch(**device.get("match", {})),
                mappings=mappings,
                connection=connection,
                slot=device.get("slot", 0),
                rumble=device.get("rumble", True),
            )
        )
    return AppConfig(runtime=runtime, devices=devices)
