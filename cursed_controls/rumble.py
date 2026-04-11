"""Force-feedback (rumble) forwarding to physical input devices.

Two backends:
  ForceFeedback   — generic evdev EV_FF/FF_RUMBLE (Nintendo Pro Controller, etc.)
  WiimoteFeedback — libxwiimote xwii_iface_rumble() (Wiimote: binary ON/OFF)

The caller (runtime._dispatch_rumble) drives the timing:
  - set_rumble(l, r) on new packets from the gadget
  - heartbeat()      every 50 ms while active (keeps evdev drivers happy)
  - stop()           on timeout (500 ms without a new packet) or explicit 0,0
"""

from __future__ import annotations

import array
import ctypes
import fcntl
import os
from pathlib import Path

import evdev


# ---------------------------------------------------------------------------
# ff_effect struct, mirroring <linux/input.h>.
# ctypes computes sizeof() correctly for 32-bit ARM (Pi) and x86-64.
#
# Critical field types (verified against kernel header and C sizeof probe):
#   ff_periodic_effect.magnitude  → __s16  (c_int16, NOT c_int32)
#   ff_periodic_effect.offset     → __s16  (c_int16, NOT c_int32)
#   ff_periodic_effect.custom_data → __s16* pointer (c_void_p picks right width)
#
# sizeof(_FfEffect) == 44 on ARM32, 48 on x86-64.
# EVIOCSFF == 0x402c4580 on ARM32, 0x40304580 on x86-64.
# Wrong int32 types produce 48/56 → wrong ioctl number → EFAULT on every call.
# ---------------------------------------------------------------------------


class _FfEnvelope(ctypes.Structure):
    _fields_ = [
        ("attack_length", ctypes.c_uint16),
        ("attack_level", ctypes.c_uint16),
        ("fade_length", ctypes.c_uint16),
        ("fade_level", ctypes.c_uint16),
    ]


class _FfPeriodic(ctypes.Structure):
    _fields_ = [
        ("waveform", ctypes.c_uint16),
        ("period", ctypes.c_uint16),
        ("magnitude", ctypes.c_int16),  # __s16, NOT __s32
        ("offset", ctypes.c_int16),  # __s16, NOT __s32
        ("phase", ctypes.c_uint16),
        ("envelope", _FfEnvelope),
        ("custom_len", ctypes.c_uint32),
        ("custom_data", ctypes.c_void_p),  # pointer: 4 B on ARM32, 8 B on x86-64
    ]


class _FfCondition(ctypes.Structure):
    _fields_ = [
        ("right_saturation", ctypes.c_uint16),
        ("left_saturation", ctypes.c_uint16),
        ("right_coeff", ctypes.c_int16),
        ("left_coeff", ctypes.c_int16),
        ("deadband", ctypes.c_uint16),
        ("center", ctypes.c_int16),
    ]


class _FfRumble(ctypes.Structure):
    _fields_ = [
        ("strong_magnitude", ctypes.c_uint16),
        ("weak_magnitude", ctypes.c_uint16),
    ]


class _FfUnion(ctypes.Union):
    _fields_ = [
        ("periodic", _FfPeriodic),
        ("condition", _FfCondition * 2),
        ("rumble", _FfRumble),
    ]


class _FfTrigger(ctypes.Structure):
    _fields_ = [("button", ctypes.c_uint16), ("interval", ctypes.c_uint16)]


class _FfReplay(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint16), ("delay", ctypes.c_uint16)]


class _FfEffect(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint16),
        ("id", ctypes.c_int16),
        ("direction", ctypes.c_uint16),
        ("trigger", _FfTrigger),
        ("replay", _FfReplay),
        ("u", _FfUnion),
    ]


def _eviocsff() -> int:
    """Compute EVIOCSFF ioctl number for the current architecture."""
    size = ctypes.sizeof(_FfEffect)
    return 0x40000000 | (size << 16) | (0x45 << 8) | 0x80  # _IOW('E', 0x80, size)


def _upload_ff_rumble(
    fd: int, effect_id: int, strong: int, weak: int, duration_ms: int = 100
) -> int:
    """Upload (or update) a FF_RUMBLE effect. Returns the kernel-assigned effect id.

    duration_ms=100: each play lasts 100 ms. The runtime heartbeat (50 ms)
    re-writes EV_FF before the effect expires, giving continuous rumble
    while keeping hid-nintendo happy.
    """
    eff = _FfEffect()
    eff.type = 0x50  # FF_RUMBLE
    eff.id = effect_id  # -1 → kernel allocates a new slot
    eff.replay.length = duration_ms
    eff.replay.delay = 0
    eff.u.rumble.strong_magnitude = strong
    eff.u.rumble.weak_magnitude = weak

    buf = array.array("b", bytes(eff))
    fcntl.ioctl(fd, _eviocsff(), buf)
    return _FfEffect.from_buffer(buf).id


# ---------------------------------------------------------------------------
# ForceFeedback — generic evdev backend (Nintendo Pro Controller, etc.)
# ---------------------------------------------------------------------------


class ForceFeedback:
    """Drives rumble on a single evdev device that supports FF_RUMBLE."""

    def __init__(self, device: evdev.InputDevice):
        self._device = device
        self._effect_id: int = -1
        self._last: tuple[int, int] = (-1, -1)  # sentinel, force first upload

        caps = device.capabilities()
        ff_caps = caps.get(evdev.ecodes.EV_FF, [])
        # capabilities() may return ints or (int, AbsInfo) tuples
        codes = [c if isinstance(c, int) else c[0] for c in ff_caps]
        self.supported: bool = evdev.ecodes.FF_RUMBLE in codes

    def set_rumble(self, left: int, right: int) -> None:
        """Set motor intensities (0-255 each). Call with (0, 0) to stop."""
        if not self.supported:
            return
        if (left, right) == self._last:
            return
        self._last = (left, right)

        # Scale 0-255 → 0-65535 (Linux FF magnitude range)
        strong = min((left * 257), 0xFFFF)
        weak = min((right * 257), 0xFFFF)

        try:
            self._effect_id = _upload_ff_rumble(
                self._device.fd, self._effect_id, strong, weak
            )
            # Always play(1) first so the new intensity (including zero) is
            # immediately pushed to the hardware. Controllers like Xbox One BT
            # hold the last motor state indefinitely — without an explicit
            # zero-intensity report the motor never stops. play(0) then dequeues.
            self._device.write(evdev.ecodes.EV_FF, self._effect_id, 1)
            if left == 0 and right == 0:
                self._device.write(evdev.ecodes.EV_FF, self._effect_id, 0)
        except OSError as e:
            print(f"[rumble] ioctl failed on {self._device.path}: {e}", flush=True)

    def heartbeat(self) -> None:
        """Re-send the current play event to prevent the 100 ms effect from expiring.

        hid-nintendo stops vibrating after ~100 ms without a refresh;
        the runtime calls this every 50 ms while rumble is active.
        """
        if not self.supported or self._effect_id < 0 or self._last == (0, 0):
            return
        try:
            self._device.write(evdev.ecodes.EV_FF, self._effect_id, 1)
        except OSError as e:
            print(f"[rumble] heartbeat failed on {self._device.path}: {e}", flush=True)

    def stop(self) -> None:
        self.set_rumble(0, 0)


# ---------------------------------------------------------------------------
# WiimoteFeedback — libxwiimote backend (binary ON/OFF motor)
# ---------------------------------------------------------------------------

# Lazily loaded libxwiimote handle (None if not installed)
_libxwii: ctypes.CDLL | None = None
_libxwii_loaded: bool = False


def _get_libxwiimote() -> ctypes.CDLL | None:
    global _libxwii, _libxwii_loaded
    if _libxwii_loaded:
        return _libxwii
    _libxwii_loaded = True
    try:
        from ctypes.util import find_library

        name = find_library("xwiimote")
        if not name:
            return None
        lib = ctypes.CDLL(name)

        class _XwiiIface(ctypes.Structure):
            pass

        lib.xwii_iface_new.restype = ctypes.c_int
        lib.xwii_iface_new.argtypes = [
            ctypes.POINTER(ctypes.POINTER(_XwiiIface)),
            ctypes.c_char_p,
        ]
        lib.xwii_iface_open.restype = ctypes.c_int
        lib.xwii_iface_open.argtypes = [ctypes.POINTER(_XwiiIface), ctypes.c_uint]
        lib.xwii_iface_unref.argtypes = [ctypes.POINTER(_XwiiIface)]
        lib.xwii_iface_rumble.restype = ctypes.c_int
        lib.xwii_iface_rumble.argtypes = [ctypes.POINTER(_XwiiIface), ctypes.c_bool]
        lib.xwii_iface_set_led.restype = ctypes.c_int
        lib.xwii_iface_set_led.argtypes = [
            ctypes.POINTER(_XwiiIface),
            ctypes.c_uint,
            ctypes.c_bool,
        ]

        lib._XwiiIface = _XwiiIface  # stash for use in WiimoteFeedback
        _libxwii = lib
    except Exception:
        pass
    return _libxwii


_XWII_IFACE_CORE: int = 1
_XWII_IFACE_WRITABLE: int = 65536
_XWII_LED1: int = 1
_XWII_LED2: int = 2
_XWII_LED3: int = 3
_XWII_LED4: int = 4


def _find_hid_syspath(event_path: str) -> str | None:
    """Walk sysfs to find the HID device path for an evdev event node."""
    event_sys = Path("/sys/class/input") / Path(event_path).name / "device"
    try:
        event_real = os.path.realpath(str(event_sys))
    except Exception:
        return None
    hid_base = "/sys/bus/hid/devices"
    try:
        entries = os.listdir(hid_base)
    except Exception:
        return None
    for entry in entries:
        hid_path = os.path.realpath(os.path.join(hid_base, entry))
        try:
            if os.path.commonpath([event_real, hid_path]) == hid_path:
                return hid_path
        except ValueError:
            continue
    return None


class WiimoteFeedback:
    """Drives rumble on a Wiimote via libxwiimote (binary ON/OFF).

    The Wiimote motor has no magnitude control — any non-zero request turns it
    on, zero turns it off. The motor is stateful: it stays on until explicitly
    stopped, so no heartbeat is needed.

    Falls back gracefully if libxwiimote is not installed.
    """

    def __init__(self, device: evdev.InputDevice):
        self._device_path = device.path
        self._iface = None  # ctypes POINTER(_XwiiIface)
        self._on: bool = False
        self.supported: bool = False

        lib = _get_libxwiimote()
        if lib is None:
            print(
                f"[rumble] libxwiimote not available — Wiimote rumble disabled",
                flush=True,
            )
            return

        hid_path = _find_hid_syspath(device.path)
        if hid_path is None:
            print(
                f"[rumble] could not find HID sysfs path for {device.path}", flush=True
            )
            return

        _XwiiIface = lib._XwiiIface
        iface_pp = ctypes.POINTER(_XwiiIface)()
        ret = lib.xwii_iface_new(ctypes.byref(iface_pp), hid_path.encode())
        if ret != 0:
            print(f"[rumble] xwii_iface_new failed ({ret}) for {hid_path}", flush=True)
            return

        ret = lib.xwii_iface_open(iface_pp, _XWII_IFACE_CORE | _XWII_IFACE_WRITABLE)
        if ret != 0:
            lib.xwii_iface_unref(iface_pp)
            print(f"[rumble] xwii_iface_open failed ({ret}) for {hid_path}", flush=True)
            return

        self._iface = iface_pp
        self.supported = True

    def set_rumble(self, left: int, right: int) -> None:
        """Turn motor on if any intensity is non-zero, off otherwise."""
        if not self.supported or self._iface is None:
            return
        want_on = left > 0 or right > 0
        if want_on == self._on:
            return
        self._on = want_on
        lib = _get_libxwiimote()
        if lib is None:
            return
        ret = lib.xwii_iface_rumble(self._iface, want_on)
        if ret != 0:
            print(f"[rumble] xwii_iface_rumble({want_on}) failed ({ret})", flush=True)

    def set_player_led(self, slot: int) -> None:
        """Light up the player LED corresponding to slot (0-indexed → LED 1–4). All other LEDs off."""
        if not self.supported or self._iface is None:
            return
        lib = _get_libxwiimote()
        if lib is None:
            return
        for i, const in enumerate((_XWII_LED1, _XWII_LED2, _XWII_LED3, _XWII_LED4)):
            ret = lib.xwii_iface_set_led(self._iface, const, i == slot)
            if ret != 0:
                print(
                    f"[rumble] xwii_iface_set_led(led={const}, on={i == slot}) failed ({ret})",
                    flush=True,
                )

    def heartbeat(self) -> None:
        pass  # Wiimote is stateful — motor stays on until explicitly stopped

    def stop(self) -> None:
        self.set_rumble(0, 0)

    def __del__(self) -> None:
        lib = _get_libxwiimote()
        if lib is not None and self._iface is not None:
            lib.xwii_iface_unref(self._iface)
            self._iface = None
