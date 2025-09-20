from dataclasses import dataclass
import struct
from enum import Enum
from evdev import ecodes


class X360Surfaces(Enum):
    A = ("A", ecodes.BTN_A)
    B = ("B", ecodes.BTN_B)
    X = ("X", ecodes.BTN_X)
    Y = ("Y", ecodes.BTN_Y)
    OPTIONS = ("OPTIONS", ecodes.BTN_SELECT)
    XBOX = ("XBOX", ecodes.BTN_MODE)
    START = ("START", ecodes.BTN_START)
    STICK_L = ("STICK_L", ecodes.BTN_THUMBL)
    STICK_R = ("STICK_R", ecodes.BTN_THUMBR)
    BUMPER_L = (("BUMPER_L", ecodes.BTN_TL),)
    BUMPER_R = ("BUMPER_R", ecodes.BTN_TR)

    # Dpad
    DPAD_UP = ("DPAD_UP", ecodes.ABS_HAT0Y)  # -1
    DPAD_DOWN = ("DPAD_DOWN", ecodes.ABS_HAT0Y)  # 1
    DPAD_LEFT = ("DPAD_LEFT", ecodes.ABS_HAT0X)  # -1
    DPAD_RIGHT = ("DPAD_RIGHT", ecodes.ABS_HAT0X)  # 1

    # Triggers
    LEFT_TRIGGER = ("LEFT_TRIGGER", ecodes.ABS_BRAKE)  # 8-bit 0-1024
    RIGHT_TRIGGER = ("RIGHT_TRIGGER", ecodes.ABS_GAS)  # 8-bit 0-1024

    # Joystick axis
    LEFT_JOYSTICK_X = ("LEFT_JOYSTICK_X", ecodes.ABS_X)
    LEFT_JOYSTICK_Y = ("LEFT_JOYSTICK_Y", ecodes.ABS_Y)
    RIGHT_JOYSTICK_X = ("RIGHT_JOYSTICK_X", ecodes.ABS_RZ)
    RIGHT_JOYSTICK_Y = ("RIGHT_JOYSTICK_Y", ecodes.ABS_Z)


@dataclass
class BitPackedButton:
    name: str
    bit: int
    value: bool = False


class BitPackedButtons:
    def __init__(self, buttons):
        self.buttons = buttons

    def to_bytes_repr(self) -> int:
        result = 0
        for b in self.buttons:
            if b.value:
                result |= 1 << b.bit
        return result & 0xFF


@dataclass
class Axis:
    value: int = 0  # default
    bits: int = 8  # triggers are 8-bit by default

    def to_u8(self) -> int:
        return max(0, min(255, self.value))


@dataclass
class JoystickAxis:
    value: int = 0

    def to_i16(self) -> int:
        return max(-32768, min(32767, self.value))


@dataclass
class JoystickState:
    x: JoystickAxis
    y: JoystickAxis


class XboxButtonState:
    def __init__(self):
        self.a = BitPackedButton("A", 0x04)
        self.b = BitPackedButton("B", 0x05)
        self.x = BitPackedButton("X", 0x06)
        self.y = BitPackedButton("Y", 0x07)
        self.lb = BitPackedButton("LB", 0x00)
        self.rb = BitPackedButton("RB", 0x01)
        self.l3 = BitPackedButton("L3", 0x06)
        self.r3 = BitPackedButton("R3", 0x07)
        self.start = BitPackedButton("START", 0x04)
        self.options = BitPackedButton("OPTIONS", 0x05)
        self.xbox = BitPackedButton("XBOX", 0x02)
        self.dpad_up = BitPackedButton("DPAD_UP", 0x00)
        self.dpad_down = BitPackedButton("DPAD_DOWN", 0x01)
        self.dpad_left = BitPackedButton("DPAD_LEFT", 0x02)
        self.dpad_right = BitPackedButton("DPAD_RIGHT", 0x03)

        self.all = [
            self.a,
            self.b,
            self.x,
            self.y,
            self.lb,
            self.rb,
            self.l3,
            self.r3,
            self.start,
            self.options,
            self.xbox,
            self.dpad_up,
            self.dpad_down,
            self.dpad_left,
            self.dpad_right,
        ]

    def get_control_byte_2(self) -> int:
        return BitPackedButtons(
            [
                self.dpad_up,
                self.dpad_down,
                self.dpad_left,
                self.dpad_right,
                self.start,
                self.options,
                self.l3,
                self.r3,
            ]
        ).to_bytes_repr()

    def get_control_byte_3(self) -> int:
        return BitPackedButtons(
            [
                self.lb,
                self.rb,
                self.xbox,
                self.a,
                self.b,
                self.x,
                self.y,
            ]
        ).to_bytes_repr()

    def get_button(self, name: str):
        """Return a BitPackedButton by its name (case-insensitive)."""
        name = name.upper()
        for btn in self.all:
            if btn.name.upper() == name:
                return btn
        raise ValueError(f"No button found with name '{name}'")


class XboxControllerState:
    def __init__(self):
        self.buttons = XboxButtonState()
        self.left_trigger = Axis(0, 8)
        self.right_trigger = Axis(0, 8)
        self.left_joystick = JoystickState(JoystickAxis(0), JoystickAxis(0))
        self.right_joystick = JoystickState(JoystickAxis(0), JoystickAxis(0))

    def to_packet(self) -> bytes:
        packet = bytearray(20)
        packet[0] = 0x00  # Report ID
        packet[1] = 0x14  # Length
        packet[2] = self.buttons.get_control_byte_2()
        packet[3] = self.buttons.get_control_byte_3()
        packet[4] = self.left_trigger.to_u8()
        packet[5] = self.right_trigger.to_u8()

        # pack little-endian signed 16-bit joystick values
        packet[6:8] = struct.pack("<h", self.left_joystick.x.to_i16())
        packet[8:10] = struct.pack("<h", self.left_joystick.y.to_i16())
        packet[10:12] = struct.pack("<h", self.right_joystick.x.to_i16())
        packet[12:14] = struct.pack("<h", self.right_joystick.y.to_i16())

        return bytes(packet)

    def by_enum(self, enum_member: X360Surfaces):
        """Return the corresponding controller attribute for the given X360Surfaces enum."""
        mapping = {
            X360Surfaces.A: self.buttons.a,
            X360Surfaces.B: self.buttons.b,
            X360Surfaces.X: self.buttons.x,
            X360Surfaces.Y: self.buttons.y,
            X360Surfaces.BUMPER_L: self.buttons.lb,
            X360Surfaces.BUMPER_R: self.buttons.rb,
            X360Surfaces.STICK_L: self.buttons.l3,
            X360Surfaces.STICK_R: self.buttons.r3,
            X360Surfaces.START: self.buttons.start,
            X360Surfaces.OPTIONS: self.buttons.options,
            X360Surfaces.XBOX: self.buttons.xbox,
            X360Surfaces.DPAD_UP: self.buttons.dpad_up,
            X360Surfaces.DPAD_DOWN: self.buttons.dpad_down,
            X360Surfaces.DPAD_LEFT: self.buttons.dpad_left,
            X360Surfaces.DPAD_RIGHT: self.buttons.dpad_right,
            X360Surfaces.LEFT_TRIGGER: self.left_trigger,
            X360Surfaces.RIGHT_TRIGGER: self.right_trigger,
            X360Surfaces.LEFT_JOYSTICK_X: self.left_joystick.x,
            X360Surfaces.LEFT_JOYSTICK_Y: self.left_joystick.y,
            X360Surfaces.RIGHT_JOYSTICK_X: self.right_joystick.x,
            X360Surfaces.RIGHT_JOYSTICK_Y: self.right_joystick.y,
        }
        try:
            return mapping[enum_member]
        except KeyError:
            raise ValueError(f"No control found for enum {enum_member}")
