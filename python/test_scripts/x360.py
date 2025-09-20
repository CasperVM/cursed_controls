from dataclasses import dataclass
import struct

# --- BitPackedButton and helpers ---


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


# --- Axes and Joystick ---


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


# --- Xbox button state ---


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


# --- Xbox controller state ---


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
