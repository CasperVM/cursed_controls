#!/usr/bin/env python3
# Minimal working example to turn on LED4 using libxwiimote via ctypes.
# Run as root or with appropriate device permissions.

import ctypes
from ctypes.util import find_library
from pathlib import Path
import subprocess
import re
import os
import errno
import sys


# ----------------- helpers -----------------
def errno_str(code):
    return f"{code} ({errno.errorcode.get(abs(code),'?')}): {os.strerror(abs(code))}"


def find_hid_syspath_from_event(event_node):
    """
    Given /dev/input/eventN, return the HID sysfs path that xwii_iface_new expects.
    Strategy:
      1) Run `udevadm info -a -n /dev/input/eventN` and pick the 'looking at device' block
         where SUBSYSTEM=="hid".
      2) Fallback: resolve /sys/class/input/eventN/device -> realpath and find a
         /sys/bus/hid/devices/* path that is an ancestor.
    Returns absolute sysfs path (string), e.g. "/sys/bus/hid/devices/0005:057E:0306.0001"
    """
    event_node = str(event_node)
    # Try udevadm -a -n
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
                # cur_path is the sysfs path printed for that block
                return cur_path
    except FileNotFoundError:
        # udevadm not present; continue to fallback
        pass
    except subprocess.CalledProcessError:
        pass

    # Fallback: check which /sys/bus/hid/devices/* is an ancestor of the input device's sysfs path.
    event_sys = Path("/sys/class/input") / Path(event_node).name / "device"
    if not event_sys.exists():
        raise FileNotFoundError(f"sysfs path for {event_node} not found: {event_sys}")

    event_real = os.path.realpath(str(event_sys))
    hid_base = "/sys/bus/hid/devices"
    if os.path.isdir(hid_base):
        for entry in os.listdir(hid_base):
            hid_path = os.path.realpath(os.path.join(hid_base, entry))
            # if event device is inside this hid device subtree, that's our hid device
            try:
                # normalize trailing slashes
                if os.path.commonpath([event_real, hid_path]) == hid_path:
                    return hid_path
            except ValueError:
                # unrelated paths on different mounts
                continue

    raise RuntimeError(
        "Could not resolve HID sysfs path from event node; try `udevadm` manually."
    )


# ----------------- ctypes bindings -----------------
libname = find_library("xwiimote")
if not libname:
    raise RuntimeError(
        "libxwiimote not found via find_library('xwiimote'). Install libxwiimote / dev package."
    )

lib = ctypes.CDLL(libname)


class XwiiIface(ctypes.Structure):
    pass


# signatures (from your bindgen / header)
lib.xwii_iface_new.restype = ctypes.c_int
lib.xwii_iface_new.argtypes = [
    ctypes.POINTER(ctypes.POINTER(XwiiIface)),
    ctypes.c_char_p,
]

lib.xwii_iface_open.restype = ctypes.c_int
lib.xwii_iface_open.argtypes = [ctypes.POINTER(XwiiIface), ctypes.c_uint]

lib.xwii_iface_set_led.restype = ctypes.c_int
lib.xwii_iface_set_led.argtypes = [
    ctypes.POINTER(XwiiIface),
    ctypes.c_uint,
    ctypes.c_bool,
]

lib.xwii_iface_get_led.restype = ctypes.c_int
lib.xwii_iface_get_led.argtypes = [
    ctypes.POINTER(XwiiIface),
    ctypes.c_uint,
    ctypes.POINTER(ctypes.c_bool),
]

lib.xwii_iface_unref.restype = None
lib.xwii_iface_unref.argtypes = [ctypes.POINTER(XwiiIface)]

# constants (use values from your bindgen)
XWII_IFACE_CORE = 1
XWII_IFACE_WRITABLE = 65536  # IMPORTANT: correct value from bindgen
XWII_LED4 = 4


# ----------------- main -----------------
def main(event_node="/dev/input/event4"):
    print("resolve HID sysfs path from", event_node)
    try:
        hid_syspath = find_hid_syspath_from_event(event_node)
    except Exception as e:
        print("ERROR resolving HID sysfs path:", e)
        print("Try: udevadm info -a -n", event_node)
        sys.exit(1)

    print("HID sysfs path:", hid_syspath)
    # xwii expects the HID root node path (example: /sys/bus/hid/devices/0005:057E:0306.0001)
    # Accept either /sys/bus/hid/devices/... or a /sys/devices/... path; the library will resolve symlinks.

    dev_pp = ctypes.POINTER(XwiiIface)()
    ret = lib.xwii_iface_new(ctypes.byref(dev_pp), hid_syspath.encode())
    if ret != 0:
        print("xwii_iface_new failed:", errno_str(ret))
        # Common actions:
        print(
            " - Ensure the device is a recognized Wii Remote (name should be 'Nintendo Wii Remote' or similar)."
        )
        print(
            " - Ensure hid-wiimote kernel module is loaded (lsmod | grep hid_wiimote)."
        )
        print(" - Try `xwiishow` or `xwiishow -v` to see detected devices.")
        sys.exit(1)

    iface = dev_pp
    try:
        ret = lib.xwii_iface_open(iface, XWII_IFACE_CORE | XWII_IFACE_WRITABLE)
        if ret != 0:
            print("xwii_iface_open(CORE|WRITABLE) failed:", errno_str(ret))
            # If ENODEV here, CORE is missing or device not bound; see notes below.
            sys.exit(1)

        ret = lib.xwii_iface_set_led(iface, XWII_LED4, True)
        if ret != 0:
            print("xwii_iface_set_led failed:", errno_str(ret))
            sys.exit(1)

        # Read back state
        state = ctypes.c_bool(False)
        ret = lib.xwii_iface_get_led(iface, XWII_LED4, ctypes.byref(state))
        if ret != 0:
            print("xwii_iface_get_led failed:", errno_str(ret))
        else:
            print("LED4 state (read back):", bool(state.value))

        print("Done — LED4 should now be ON if the hardware supports it.")
    finally:
        # Drop ref
        lib.xwii_iface_unref(iface)


if __name__ == "__main__":
    # optionally take event node from argv
    node = sys.argv[1] if len(sys.argv) > 1 else "/dev/input/event4"
    main(node)
