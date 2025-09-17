#!/usr/bin/env python3
import ctypes, sys, os, errno, subprocess, re, time
from ctypes.util import find_library
from pathlib import Path


# ----------------- helpers -----------------
def errno_str(code):
    return f"{code} ({errno.errorcode.get(abs(code),'?')}): {os.strerror(abs(code))}"


def find_hid_syspath_from_event(event_node):
    event_node = str(event_node)
    try:
        out = subprocess.check_output(
            ["udevadm", "info", "-a", "-n", event_node], text=True
        )
        cur_path = None
        for line in out.splitlines():
            m = re.match(r"^\s*looking at device '([^']+)'", line)
            if m:
                cur_path = m.group(1)
            if 'SUBSYSTEM=="hid"' in line:
                return cur_path
    except Exception:
        pass
    event_sys = Path("/sys/class/input") / Path(event_node).name / "device"
    event_real = os.path.realpath(str(event_sys))
    hid_base = "/sys/bus/hid/devices"
    for entry in os.listdir(hid_base):
        hid_path = os.path.realpath(os.path.join(hid_base, entry))
        try:
            if os.path.commonpath([event_real, hid_path]) == hid_path:
                return hid_path
        except ValueError:
            continue
    raise RuntimeError("Could not resolve HID sysfs path")


# ----------------- ctypes bindings -----------------
libname = find_library("xwiimote")
if not libname:
    raise RuntimeError("libxwiimote not found")

lib = ctypes.CDLL(libname)


class XwiiIface(ctypes.Structure):
    pass


lib.xwii_iface_new.restype = ctypes.c_int
lib.xwii_iface_new.argtypes = [
    ctypes.POINTER(ctypes.POINTER(XwiiIface)),
    ctypes.c_char_p,
]

lib.xwii_iface_open.restype = ctypes.c_int
lib.xwii_iface_open.argtypes = [ctypes.POINTER(XwiiIface), ctypes.c_uint]

lib.xwii_iface_unref.argtypes = [ctypes.POINTER(XwiiIface)]

lib.xwii_iface_rumble.restype = ctypes.c_int
lib.xwii_iface_rumble.argtypes = [ctypes.POINTER(XwiiIface), ctypes.c_bool]

XWII_IFACE_CORE = 1
XWII_IFACE_WRITABLE = 65536


# ----------------- rumble control -----------------
class WiimoteRumble:
    def __init__(self, iface, ramp_time=0.8):
        self.iface = iface
        self.current_strength = 0  # 0–255
        self.ramp_time = ramp_time

    def rumble_on(self):
        start = time.perf_counter()
        ret = lib.xwii_iface_rumble(self.iface, True)
        end = time.perf_counter()
        if ret != 0:
            raise OSError(ret, errno_str(ret))
        return end - start

    def rumble_off(self):
        start = time.perf_counter()
        ret = lib.xwii_iface_rumble(self.iface, False)
        end = time.perf_counter()
        if ret != 0:
            raise OSError(ret, errno_str(ret))
        return end - start

    def set_strength(self, target_strength, duration=10.0, pwm_hz=100):
        """Ramp to target strength [0–255], then hold it for duration seconds."""
        target_strength = max(0, min(255, int(target_strength)))
        start_strength = self.current_strength

        # Phase 1: ramp over ramp_time
        ramp_end = time.perf_counter() + self.ramp_time
        while time.perf_counter() < ramp_end:
            frac = 1.0 - (ramp_end - time.perf_counter()) / self.ramp_time
            strength = int(start_strength + (target_strength - start_strength) * frac)
            self._pwm_cycle(strength, 1.0 / pwm_hz)
        self.current_strength = target_strength

        # Phase 2: hold for duration
        hold_end = time.perf_counter() + duration
        while time.perf_counter() < hold_end:
            self._pwm_cycle(self.current_strength, 1.0 / pwm_hz)

        if self.current_strength == 0:
            lib.xwii_iface_rumble(self.iface, False)

    def _pwm_cycle(self, strength, period):
        """One PWM cycle at given strength [0–255]."""
        duty = strength / 255.0
        if duty > 0:
            lib.xwii_iface_rumble(self.iface, True)
            time.sleep(period * duty)
        if duty < 1.0:
            lib.xwii_iface_rumble(self.iface, False)
            time.sleep(period * (1.0 - duty))


# ----------------- main -----------------
def main(event_node="/dev/input/event4"):
    hid_syspath = find_hid_syspath_from_event(event_node)
    dev_pp = ctypes.POINTER(XwiiIface)()
    ret = lib.xwii_iface_new(ctypes.byref(dev_pp), hid_syspath.encode())
    if ret != 0:
        print("xwii_iface_new failed:", errno_str(ret))
        sys.exit(1)
    iface = dev_pp

    try:
        ret = lib.xwii_iface_open(iface, XWII_IFACE_CORE | XWII_IFACE_WRITABLE)
        if ret != 0:
            print("xwii_iface_open failed:", errno_str(ret))
            sys.exit(1)

        rum = WiimoteRumble(iface, ramp_time=0.8)

        print("Measuring rumble ON...")
        t_on = rum.rumble_on()
        print(f"Rumble ON API call took {t_on*1000:.3f} ms")
        time.sleep(1)

        print("Measuring rumble OFF...")
        t_off = rum.rumble_off()
        print(f"Rumble OFF API call took {t_off*1000:.3f} ms")
        time.sleep(1)

        input("Press Enter to start 10s strength demo with ramp smoothing...")

        print("Running at 25% strength for 10s")
        rum.set_strength(64, duration=10.0)

        print("Running at 100% strength for 10s")
        rum.set_strength(255, duration=10.0)

        print("Running at 50% strength for 10s")
        rum.set_strength(128, duration=10.0)

        print("Stopping rumble...")
        rum.set_strength(0, duration=2.0)

    finally:
        lib.xwii_iface_unref(iface)


if __name__ == "__main__":
    node = sys.argv[1] if len(sys.argv) > 1 else "/dev/input/event4"
    main(node)
