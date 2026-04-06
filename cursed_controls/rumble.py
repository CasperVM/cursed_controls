"""Force-feedback (rumble) forwarding to evdev devices.

Uses the Linux EVIOCSFF ioctl to upload a FF_RUMBLE effect and the
EV_FF event type to play/stop it. Works on any device that reports
EV_FF / FF_RUMBLE in its capabilities (Wiimote, Xbox controller, etc.).
"""

from __future__ import annotations

import array
import ctypes
import fcntl

import evdev


# ---------------------------------------------------------------------------
# ff_effect struct, matches <linux/input.h> on the host architecture.
# ctypes computes sizeof() correctly for 32-bit ARM (Pi) and x86-64.
# ---------------------------------------------------------------------------


class _FfRumble(ctypes.Structure):
    _fields_ = [
        ("strong_magnitude", ctypes.c_uint16),
        ("weak_magnitude", ctypes.c_uint16),
    ]


class _FfUnion(ctypes.Union):
    # The union in ff_effect holds the largest member (ff_periodic_effect).
    # We only use the rumble member; pad to 60 bytes to be safe on both
    # 32-bit ARM (sizeof ~= 48 total) and x86-64 (sizeof ~= 72 total).
    _fields_ = [
        ("rumble", _FfRumble),
        ("_pad", ctypes.c_uint8 * 60),
    ]


class _FfEffect(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint16),
        ("id", ctypes.c_int16),
        ("direction", ctypes.c_uint16),
        ("trigger", ctypes.c_uint16 * 2),  # [button, interval]
        ("replay", ctypes.c_uint16 * 2),  # [length_ms, delay_ms]
        ("u", _FfUnion),
    ]


def _eviocsff() -> int:
    """Compute EVIOCSFF ioctl number for the current architecture."""
    size = ctypes.sizeof(_FfEffect)
    return 0x40000000 | (size << 16) | (0x45 << 8) | 0x80  # _IOW('E', 0x80, size)


def _upload_ff_rumble(
    fd: int, effect_id: int, strong: int, weak: int, duration_ms: int = 60_000
) -> int:
    """Upload (or update) a FF_RUMBLE effect. Returns the kernel-assigned effect id."""
    eff = _FfEffect()
    eff.type = 0x50  # FF_RUMBLE
    eff.id = effect_id  # -1 → kernel allocates a new slot
    eff.replay[0] = duration_ms
    eff.replay[1] = 0  # no delay
    eff.u.rumble.strong_magnitude = strong
    eff.u.rumble.weak_magnitude = weak

    buf = array.array("b", bytes(eff))
    fcntl.ioctl(fd, _eviocsff(), buf)
    return _FfEffect.from_buffer(buf).id


# ---------------------------------------------------------------------------
# ForceFeedback, high-level per-device rumble driver
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
            playing = left > 0 or right > 0
            self._device.write(evdev.ecodes.EV_FF, self._effect_id, 1 if playing else 0)
        except OSError:
            pass  # device may have disconnected

    def stop(self) -> None:
        self.set_rumble(0, 0)
