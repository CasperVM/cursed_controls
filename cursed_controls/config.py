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
    EVDEV = "evdev"        # already present in /dev/input (default)
    BLUETOOTH = "bluetooth"  # paired device, connect by MAC at startup
    WIIMOTE = "wiimote"    # scan for first Nintendo Wii Remote


@dataclass
class ConnectionConfig:
    type: ConnectionType = ConnectionType.EVDEV
    mac: str | None = None     # required for bluetooth, optional for wiimote
    timeout_s: float = 30.0    # seconds to scan/wait before giving up


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


@dataclass
class DeviceProfile:
    id: str
    match: DeviceMatch
    mappings: list[MappingRule] = field(default_factory=list)
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)


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


@dataclass
class AppConfig:
    runtime: RuntimeConfig
    devices: list[DeviceProfile]


def _surface(value: str) -> Surface:
    return Surface[value] if value in Surface.__members__ else Surface(value)


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
            )
        )
    return AppConfig(runtime=runtime, devices=devices)
