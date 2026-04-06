from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import struct


class Surface(str, Enum):
    A = "A"
    B = "B"
    X = "X"
    Y = "Y"
    OPTIONS = "OPTIONS"
    XBOX = "XBOX"
    START = "START"
    STICK_L = "STICK_L"
    STICK_R = "STICK_R"
    BUMPER_L = "BUMPER_L"
    BUMPER_R = "BUMPER_R"
    DPAD_UP = "DPAD_UP"
    DPAD_DOWN = "DPAD_DOWN"
    DPAD_LEFT = "DPAD_LEFT"
    DPAD_RIGHT = "DPAD_RIGHT"
    LEFT_TRIGGER = "LEFT_TRIGGER"
    RIGHT_TRIGGER = "RIGHT_TRIGGER"
    LEFT_JOYSTICK_X = "LEFT_JOYSTICK_X"
    LEFT_JOYSTICK_Y = "LEFT_JOYSTICK_Y"
    RIGHT_JOYSTICK_X = "RIGHT_JOYSTICK_X"
    RIGHT_JOYSTICK_Y = "RIGHT_JOYSTICK_Y"

    @property
    def is_button(self) -> bool:
        return self not in AXIS_SURFACES

    @property
    def is_axis(self) -> bool:
        return self in AXIS_SURFACES


AXIS_SURFACES = {
    Surface.LEFT_TRIGGER,
    Surface.RIGHT_TRIGGER,
    Surface.LEFT_JOYSTICK_X,
    Surface.LEFT_JOYSTICK_Y,
    Surface.RIGHT_JOYSTICK_X,
    Surface.RIGHT_JOYSTICK_Y,
}


@dataclass
class XboxControllerState:
    a: bool = False
    b: bool = False
    x: bool = False
    y: bool = False
    lb: bool = False
    rb: bool = False
    l3: bool = False
    r3: bool = False
    start: bool = False
    options: bool = False
    xbox: bool = False
    dpad_up: bool = False
    dpad_down: bool = False
    dpad_left: bool = False
    dpad_right: bool = False
    left_trigger: int = 0
    right_trigger: int = 0
    left_joystick_x: int = 0
    left_joystick_y: int = 0
    right_joystick_x: int = 0
    right_joystick_y: int = 0

    def set_button(self, surface: Surface, pressed: bool) -> bool:
        mapping = {
            Surface.A: "a",
            Surface.B: "b",
            Surface.X: "x",
            Surface.Y: "y",
            Surface.BUMPER_L: "lb",
            Surface.BUMPER_R: "rb",
            Surface.STICK_L: "l3",
            Surface.STICK_R: "r3",
            Surface.START: "start",
            Surface.OPTIONS: "options",
            Surface.XBOX: "xbox",
            Surface.DPAD_UP: "dpad_up",
            Surface.DPAD_DOWN: "dpad_down",
            Surface.DPAD_LEFT: "dpad_left",
            Surface.DPAD_RIGHT: "dpad_right",
        }
        attr = mapping[surface]
        pressed = bool(pressed)
        changed = getattr(self, attr) != pressed
        setattr(self, attr, pressed)
        return changed

    def set_axis(self, surface: Surface, value: int) -> bool:
        attr = {
            Surface.LEFT_TRIGGER: "left_trigger",
            Surface.RIGHT_TRIGGER: "right_trigger",
            Surface.LEFT_JOYSTICK_X: "left_joystick_x",
            Surface.LEFT_JOYSTICK_Y: "left_joystick_y",
            Surface.RIGHT_JOYSTICK_X: "right_joystick_x",
            Surface.RIGHT_JOYSTICK_Y: "right_joystick_y",
        }[surface]
        if surface in {Surface.LEFT_TRIGGER, Surface.RIGHT_TRIGGER}:
            value = max(0, min(255, int(value)))
        else:
            value = max(-32767, min(32767, int(value)))
        changed = getattr(self, attr) != value
        setattr(self, attr, value)
        return changed

    def to_packet(self) -> bytes:
        b2 = (
            (1 if self.dpad_up else 0) << 0
            | (1 if self.dpad_down else 0) << 1
            | (1 if self.dpad_left else 0) << 2
            | (1 if self.dpad_right else 0) << 3
            | (1 if self.start else 0) << 4
            | (1 if self.options else 0) << 5
            | (1 if self.l3 else 0) << 6
            | (1 if self.r3 else 0) << 7
        )
        b3 = (
            (1 if self.lb else 0) << 0
            | (1 if self.rb else 0) << 1
            | (1 if self.xbox else 0) << 2
            | (1 if self.a else 0) << 4
            | (1 if self.b else 0) << 5
            | (1 if self.x else 0) << 6
            | (1 if self.y else 0) << 7
        )
        packet = bytearray(20)
        packet[0] = 0x00
        packet[1] = 0x14
        packet[2] = b2
        packet[3] = b3
        packet[4] = self.left_trigger
        packet[5] = self.right_trigger
        packet[6:8] = struct.pack("<h", self.left_joystick_x)
        packet[8:10] = struct.pack("<h", self.left_joystick_y)
        packet[10:12] = struct.pack("<h", self.right_joystick_x)
        packet[12:14] = struct.pack("<h", self.right_joystick_y)
        return bytes(packet)
