#!/usr/bin/env python3
"""Live per-axis min/max monitor. Updates in-place, no scroll spam.

Usage:
    python scripts/show_axis_range.py /dev/input/event5
"""
import sys
import select
import time
import evdev
from evdev import ecodes

def main():
    if len(sys.argv) < 2:
        print("Usage: show_axis_range.py /dev/input/eventN")
        sys.exit(1)

    dev = evdev.InputDevice(sys.argv[1])
    print(f"Monitoring: {dev.name}  ({dev.path})")
    print("Push axes to their extremes. Ctrl-C to quit.\n")

    # Seed from absinfo
    caps = dev.capabilities()
    abs_axes = caps.get(ecodes.EV_ABS, [])
    observed: dict[int, tuple[int, int]] = {}
    names: dict[int, str] = {}

    for code, info in abs_axes:
        observed[code] = (info.value, info.value)
        name = ecodes.ABS.get(code, f"ABS_{code}")
        names[code] = name

    def render():
        # Move cursor up by number of axes, redraw each line
        lines = len(observed)
        sys.stdout.write(f"\033[{lines}A")
        for code in sorted(observed):
            lo, hi = observed[code]
            name = names.get(code, f"ABS_{code}")
            bar_width = 30
            try:
                info = dev.absinfo(code)
                span = info.max - info.min or 1
                lo_pos = int((lo - info.min) / span * bar_width)
                hi_pos = int((hi - info.min) / span * bar_width)
                bar = [' '] * bar_width
                for i in range(lo_pos, hi_pos + 1):
                    bar[i] = '█'
                bar_str = ''.join(bar)
                sys.stdout.write(
                    f"  {name:<20s}  min={lo:6d}  max={hi:6d}  [{bar_str}]\n"
                )
            except Exception:
                sys.stdout.write(
                    f"  {name:<20s}  min={lo:6d}  max={hi:6d}\n"
                )
        sys.stdout.flush()

    # Print initial blank lines to reserve space
    for _ in observed:
        print()

    render()

    try:
        while True:
            r, _, _ = select.select([dev.fd], [], [], 0.1)
            if not r:
                continue
            try:
                for event in dev.read():
                    if event.type == ecodes.EV_ABS and event.code in observed:
                        lo, hi = observed[event.code]
                        observed[event.code] = (min(lo, event.value), max(hi, event.value))
            except BlockingIOError:
                pass
            render()
    except KeyboardInterrupt:
        print("\nDone.")

if __name__ == "__main__":
    main()
