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


@dataclass
class RuntimeConfig:
    poll_interval_ms: int = 1
    output_mode: str = "stdout"
    gadget_library: str = "360-w-raw-gadget/target/release/libx360_w_raw_gadget.so"
    gadget_driver: str = "3f980000.usb"
    gadget_device: str | None = None  # None → same as gadget_driver
    interfaces: int = 1
    rumble: bool = True  # forward host rumble to physical devices


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
        devices.append(
            DeviceProfile(
                id=device["id"],
                match=DeviceMatch(**device.get("match", {})),
                mappings=mappings,
            )
        )
    return AppConfig(runtime=runtime, devices=devices)
