#!/usr/bin/env python3
"""Device debug TUI: live last-input display + per-axis min/max with bar chart.

Usage:
    python scripts/show_axis_range.py              # shows device selection menu
    python scripts/show_axis_range.py /dev/input/eventN   # skips menu
"""

import sys
import select
import termios
import tty
import time
from pathlib import Path

import evdev
from evdev import ecodes


_BORING_NAMES = {"hdmi", "jack", "alsa", "speake", "microphon"}


def _has_game_device() -> bool:
    """Return True if any non-audio/HDMI input device is present."""
    for path in evdev.list_devices():
        try:
            d = evdev.InputDevice(path)
            low = d.name.lower()
            if not any(b in low for b in _BORING_NAMES):
                return True
        except Exception:
            pass
    return False


def _pick_device() -> evdev.InputDevice:
    paths = evdev.list_devices()
    if not paths:
        print("No input devices found.")
        sys.exit(1)
    devs = []
    for path in paths:
        try:
            devs.append(evdev.InputDevice(path))
        except Exception:
            pass
    if not devs:
        print("No accessible input devices.")
        sys.exit(1)
    print("Available input devices:")
    for i, d in enumerate(devs):
        print(f"  [{i}] {d.path:<24} {d.name}")
    print()
    while True:
        try:
            raw = input("Select device number: ").strip()
            idx = int(raw)
            if 0 <= idx < len(devs):
                return devs[idx]
        except (ValueError, EOFError):
            pass
        print(f"  Enter a number 0–{len(devs) - 1}")


def _ago(t: float) -> str:
    s = time.monotonic() - t
    if s < 2:
        return "just now"
    return f"{int(s)}s ago"


def _label(ev_type: int, code: int) -> str:
    name = ecodes.bytype.get(ev_type, {}).get(code, str(code))
    tname = {ecodes.EV_KEY: "EV_KEY", ecodes.EV_ABS: "EV_ABS"}.get(
        ev_type, f"EV_{ev_type}"
    )
    return f"{tname} {name} ({code})"


def main() -> None:
    if len(sys.argv) >= 2:
        try:
            dev = evdev.InputDevice(sys.argv[1])
        except Exception as e:
            print(f"Cannot open {sys.argv[1]}: {e}")
            sys.exit(1)
    else:
        if not _has_game_device():
            try:
                import sys as _sys

                _sys.path.insert(0, str(Path(__file__).parent.parent))
                from cursed_controls.bluetooth import auto_connect_wiimote

                auto_connect_wiimote()
                print()
            except Exception:
                pass
        dev = _pick_device()

    caps = dev.capabilities()
    abs_axes = caps.get(ecodes.EV_ABS, [])

    observed: dict[int, tuple[int, int]] = {}  # code → (min, max)
    current: dict[int, int] = {}  # code → current value
    abs_names: dict[int, str] = {}

    for code, info in abs_axes:
        observed[code] = (info.value, info.value)
        current[code] = info.value
        abs_names[code] = ecodes.ABS.get(code, f"ABS_{code}")

    last_button: tuple[int, int, float] | None = None  # (code, value, mono_time)
    last_axis: tuple[int, int, float] | None = None  # (code, value, mono_time)

    BAR_W = 26
    N_AXES = len(observed)
    # Fixed lines: header, sep, last_button, last_axis, blank, axes_header = 6
    # Fixed lines below axes: blank, keys = 2
    FIXED_ABOVE = 6
    FIXED_BELOW = 2
    TOTAL = FIXED_ABOVE + N_AXES + FIXED_BELOW

    SEP = "─" * 62

    def render() -> None:
        sys.stdout.write(f"\033[{TOTAL}A")  # move cursor up

        sys.stdout.write(f"\033[2K  Device: {dev.name}  ({dev.path})\n")
        sys.stdout.write(f"\033[2K  {SEP}\n")

        if last_button:
            code, value, t = last_button
            name = ecodes.KEY.get(code, ecodes.BTN.get(code, str(code)))
            sys.stdout.write(
                f"\033[2K  Last button: {name} ({code})  value={value}  {_ago(t)}\n"
            )
        else:
            sys.stdout.write(f"\033[2K  Last button: (none yet)\n")

        if last_axis:
            code, value, t = last_axis
            name = ecodes.ABS.get(code, str(code))
            sys.stdout.write(
                f"\033[2K  Last axis:   {name} ({code})  value={value:6d}  {_ago(t)}\n"
            )
        else:
            sys.stdout.write(f"\033[2K  Last axis:   (none yet)\n")

        sys.stdout.write(f"\033[2K\n")
        sys.stdout.write(f"\033[2K  Axes — push to extremes:\n")

        for code in sorted(observed):
            lo, hi = observed[code]
            cur = current.get(code, lo)
            name = abs_names.get(code, f"ABS_{code}")
            try:
                info = dev.absinfo(code)
                span = info.max - info.min or 1
                lo_pos = max(0, min(BAR_W - 1, int((lo - info.min) / span * BAR_W)))
                cur_pos = max(0, min(BAR_W - 1, int((cur - info.min) / span * BAR_W)))
                hi_pos = max(0, min(BAR_W - 1, int((hi - info.min) / span * BAR_W)))
                bar = ["░"] * BAR_W
                for i in range(lo_pos, hi_pos + 1):
                    bar[i] = "█"
                bar[cur_pos] = "│"
                bar_str = "".join(bar)
                label = f"{name}({code})"
                sys.stdout.write(
                    f"\033[2K  {label:<18}  cur={cur:6d}  min={lo:6d}  max={hi:6d}"
                    f"  [{bar_str}]\n"
                )
            except Exception:
                label = f"{name}({code})"
                sys.stdout.write(
                    f"\033[2K  {label:<18}  cur={cur:6d}  min={lo:6d}  max={hi:6d}\n"
                )

        sys.stdout.write(f"\033[2K\n")
        sys.stdout.write(f"\033[2K  [r] reset min/max    [q] quit\n")
        sys.stdout.flush()

    # Reserve space on screen
    sys.stdout.write("\n" * TOTAL)
    render()

    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(
            sys.stdin.fileno()
        )  # single-keypress without Enter; keeps output \n→\r\n

        while True:
            r, _, _ = select.select([dev.fd, sys.stdin.fileno()], [], [], 0.1)

            if sys.stdin.fileno() in r:
                ch = sys.stdin.read(1)
                if ch in ("q", "Q", "\x03", "\x04"):  # q, Q, Ctrl-C, Ctrl-D
                    break
                if ch in ("r", "R"):
                    for code in list(observed):
                        v = current.get(code, 0)
                        observed[code] = (v, v)

            if dev.fd in r:
                try:
                    for event in dev.read():
                        if event.type == ecodes.EV_ABS and event.code in observed:
                            lo, hi = observed[event.code]
                            observed[event.code] = (
                                min(lo, event.value),
                                max(hi, event.value),
                            )
                            current[event.code] = event.value
                            last_axis = (event.code, event.value, time.monotonic())
                        elif event.type == ecodes.EV_KEY and event.value in (0, 1):
                            last_button = (event.code, event.value, time.monotonic())
                except BlockingIOError:
                    pass

            render()

    except OSError:
        pass
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        print("\nDone.")


if __name__ == "__main__":
    main()
