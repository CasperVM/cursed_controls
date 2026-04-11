from __future__ import annotations

import ctypes
from abc import ABC, abstractmethod
from ctypes import byref
from pathlib import Path
from typing import Optional


def detect_udc() -> str:
    """Return the first UDC driver name from /sys/class/udc/.

    Works on any hardware after dwc2 is loaded. Raises RuntimeError
    with a helpful message if no UDC is found.
    """
    udc_path = Path("/sys/class/udc")
    try:
        entries = sorted(udc_path.iterdir())
        if entries:
            return entries[0].name
    except Exception:
        pass
    raise RuntimeError(
        "No UDC found in /sys/class/udc/ — is dwc2 loaded? "
        "Run init-raspbian.sh first, or check that dtoverlay=dwc2 is in config.txt and reboot."
    )


from cursed_controls.xbox import XboxControllerState


class OutputSink(ABC):
    """Base class for output sinks."""

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def send(self, state: XboxControllerState, slot: int = 0) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    def poll_rumble(self, slot: int = 0) -> tuple[int, int] | None:
        """Return (left_motor, right_motor) if a new rumble command is pending, else None."""
        return None

    def poll_led(self, slot: int = 0) -> int | None:
        """Return LED animation id (0-13) if pending, else None."""
        return None


class StdoutSink(OutputSink):
    """Print packets to stdout (useful for debugging/testing)."""

    def open(self) -> None:
        pass

    def send(self, state: XboxControllerState, slot: int = 0) -> None:
        packet = state.to_packet()
        print(f"[slot {slot}] {packet.hex()}")

    def close(self) -> None:
        pass


class FakeSink(OutputSink):
    """In-memory sink for testing. Collects packets without real hardware."""

    def __init__(self):
        self.packets: list[bytes] = []
        self.is_open = False
        self._pending_rumble: dict[int, tuple[int, int]] = {}
        self._pending_led: dict[int, int] = {}

    def open(self) -> None:
        self.is_open = True
        self.packets = []

    def send(self, state: XboxControllerState, slot: int = 0) -> None:
        if not self.is_open:
            raise RuntimeError("sink not open")
        self.packets.append(state.to_packet())

    def close(self) -> None:
        self.is_open = False

    def clear(self) -> None:
        self.packets = []

    def queue_rumble(self, slot: int, left: int, right: int) -> None:
        self._pending_rumble[slot] = (left, right)

    def queue_led(self, slot: int, animation: int) -> None:
        self._pending_led[slot] = animation

    def poll_rumble(self, slot: int = 0) -> tuple[int, int] | None:
        return self._pending_rumble.pop(slot, None)

    def poll_led(self, slot: int = 0) -> int | None:
        return self._pending_led.pop(slot, None)


class RawGadgetSink(OutputSink):
    """Hardware sink, sends packets via libx360_w_raw_gadget.so."""

    def __init__(
        self,
        library_path: str,
        num_slots: int = 1,
        driver: str | None = None,
        device: str | None = None,
    ):
        self._library_path = library_path
        self._num_slots = num_slots
        self._driver = (
            driver  # resolved in open() so detect_udc() runs at the right time
        )
        self._device = device
        self._lib = None
        self._handle: Optional[int] = None

    def open(self) -> None:
        try:
            lib = ctypes.CDLL(str(Path(self._library_path)))
        except OSError as e:
            raise RuntimeError(
                f"Failed to load gadget library {self._library_path!r}: {e}"
            )

        lib.x360_open.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p]
        lib.x360_open.restype = ctypes.c_void_p
        lib.x360_close.argtypes = [ctypes.c_void_p]
        lib.x360_close.restype = None
        lib.x360_send.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        lib.x360_send.restype = ctypes.c_int
        lib.x360_poll_rumble.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.POINTER(ctypes.c_uint8),
        ]
        lib.x360_poll_rumble.restype = ctypes.c_int
        lib.x360_poll_led.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.x360_poll_led.restype = ctypes.c_int
        lib.x360_set_debug.argtypes = [ctypes.c_int]
        lib.x360_set_debug.restype = None
        self._lib = lib

        resolved_driver = self._driver or detect_udc()
        # device_name in usb_raw_init is the UDC instance name, same as driver_name.
        # It is NOT the /dev/raw-gadget path (that is opened internally by the library).
        resolved_device = self._device or resolved_driver
        handle = None
        for attempt in range(5):
            handle = lib.x360_open(
                self._num_slots, resolved_driver.encode(), resolved_device.encode()
            )
            if handle:
                break
            print(f"[x360] x360_open failed (attempt {attempt + 1}/5), retrying in 1s…")
            import time as _time

            _time.sleep(1.0)
        if not handle:
            raise RuntimeError(
                "x360_open failed (check UDC driver name and root permissions)"
            )
        self._handle = handle

    def send(self, state: XboxControllerState, slot: int = 0) -> None:
        if self._handle is None or self._lib is None:
            raise RuntimeError("sink not open")
        packet = state.to_packet()
        arr = (ctypes.c_uint8 * len(packet))(*packet)
        self._lib.x360_send(self._handle, slot, arr, len(packet))

    def poll_rumble(self, slot: int = 0) -> tuple[int, int] | None:
        if self._handle is None or self._lib is None:
            return None
        left, right = ctypes.c_uint8(0), ctypes.c_uint8(0)
        r = self._lib.x360_poll_rumble(self._handle, slot, byref(left), byref(right))
        return (left.value, right.value) if r == 1 else None

    def poll_led(self, slot: int = 0) -> int | None:
        if self._handle is None or self._lib is None:
            return None
        r = self._lib.x360_poll_led(self._handle, slot)
        return r if r >= 0 else None

    def close(self) -> None:
        if self._handle is not None and self._lib is not None:
            self._lib.x360_close(self._handle)
        self._handle = None
        self._lib = None
