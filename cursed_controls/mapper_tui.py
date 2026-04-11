from __future__ import annotations

import os
import select
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import evdev
import yaml
from evdev import ecodes

from cursed_controls.config import AppConfig
from cursed_controls.discovery import DiscoveredDevice, list_devices
from cursed_controls.xbox import AXIS_SURFACES, Surface

_TRIGGER_SURFACES = {Surface.LEFT_TRIGGER, Surface.RIGHT_TRIGGER}
_JOYSTICK_SURFACES = {
    Surface.LEFT_JOYSTICK_X,
    Surface.LEFT_JOYSTICK_Y,
    Surface.RIGHT_JOYSTICK_X,
    Surface.RIGHT_JOYSTICK_Y,
}
_DPAD_SURFACES = {
    Surface.DPAD_UP,
    Surface.DPAD_DOWN,
    Surface.DPAD_LEFT,
    Surface.DPAD_RIGHT,
}

# Ordered list for the numbered surface picker menu
_SURFACE_MENU_ORDER: list[Surface] = [
    Surface.A,
    Surface.B,
    Surface.X,
    Surface.Y,
    Surface.BUMPER_L,
    Surface.BUMPER_R,
    Surface.STICK_L,
    Surface.STICK_R,
    Surface.START,
    Surface.OPTIONS,
    Surface.XBOX,
    Surface.DPAD_UP,
    Surface.DPAD_DOWN,
    Surface.DPAD_LEFT,
    Surface.DPAD_RIGHT,
    Surface.LEFT_JOYSTICK_X,
    Surface.LEFT_JOYSTICK_Y,
    Surface.RIGHT_JOYSTICK_X,
    Surface.RIGHT_JOYSTICK_Y,
    Surface.LEFT_TRIGGER,
    Surface.RIGHT_TRIGGER,
]


def _code_name(ev_type: int, code: int) -> str:
    return ecodes.bytype.get(ev_type, {}).get(code, str(code))


def _type_name(ev_type: int) -> str:
    return {ecodes.EV_KEY: "EV_KEY", ecodes.EV_ABS: "EV_ABS"}.get(ev_type, str(ev_type))


# ---------------------------------------------------------------------------
# CandidateEvent
# ---------------------------------------------------------------------------


@dataclass
class CandidateEvent:
    ev_type: int
    ev_code: int
    value: int
    confidence: float  # 1.0 = button press (certain); <1.0 = axis delta
    abs_info: evdev.AbsInfo | None  # filled for EV_ABS


# ---------------------------------------------------------------------------
# InputDetector
# ---------------------------------------------------------------------------


class InputDetector:
    """Wraps a single evdev device. Samples baseline noise, then listens for input."""

    def __init__(self, device: evdev.InputDevice) -> None:
        self._device = device
        self.noisy_axes: set[int] = set()
        self.axis_drift: dict[int, float] = {}
        self._grabbed = False

    def _try_grab(self) -> None:
        try:
            self._device.grab()
            self._grabbed = True
        except IOError:
            self._grabbed = False

    def _ungrab(self) -> None:
        if self._grabbed:
            try:
                self._device.ungrab()
            except Exception:
                pass
            self._grabbed = False

    def calibrate_axis(self, code: int, duration_s: float = 4.0) -> tuple[int, int]:
        """Watch axis `code` and return the (min, max) values actually observed.

        Falls back to absinfo declared range if no events arrive.
        """
        try:
            info = self._device.absinfo(code)
            obs_min, obs_max = info.max, info.min
        except Exception:
            obs_min, obs_max = 0, 0

        deadline = time.monotonic() + duration_s
        self._try_grab()
        try:
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                r, _, _ = select.select([self._device.fd], [], [], min(remaining, 0.1))
                if not r:
                    continue
                try:
                    for event in self._device.read():
                        if event.type == ecodes.EV_ABS and event.code == code:
                            obs_min = min(obs_min, event.value)
                            obs_max = max(obs_max, event.value)
                except BlockingIOError:
                    pass
        except OSError:
            pass
        finally:
            self._ungrab()

        if obs_min >= obs_max:
            try:
                info = self._device.absinfo(code)
                return info.min, info.max
            except Exception:
                return 0, 0
        return obs_min, obs_max

    def sample_baseline(self, duration_s: float = 0.3) -> dict[int, float]:
        """
        Read EV_ABS events for `duration_s` seconds to establish baseline.
        Axes that move more than max(flat*2, span*5%) are marked noisy.
        Returns {code: mean_value}.
        """
        self._try_grab()
        samples: dict[int, list[int]] = defaultdict(list)
        deadline = time.monotonic() + duration_s

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                r, _, _ = select.select([self._device.fd], [], [], remaining)
                if not r:
                    break
                try:
                    for event in self._device.read():
                        if event.type == ecodes.EV_ABS:
                            samples[event.code].append(event.value)
                except BlockingIOError:
                    pass
        except OSError:
            pass

        self.noisy_axes = set()
        self.axis_drift = {}
        baseline: dict[int, float] = {}

        for code, vals in samples.items():
            try:
                abs_info = self._device.absinfo(code)
                span = abs_info.max - abs_info.min
                spread = max(vals) - min(vals)
                noise_threshold = max(abs_info.flat * 2, span * 0.05) if span > 0 else 1
                if spread > noise_threshold:
                    self.noisy_axes.add(code)
                    self.axis_drift[code] = spread
                baseline[code] = sum(vals) / len(vals)
            except Exception:
                pass

        return baseline

    def detect_and_calibrate(
        self, baseline: dict[int, float], duration_s: float = 6.0
    ) -> tuple[CandidateEvent | None, tuple[int, int] | None]:
        """
        Combined detection + range calibration in one gesture.

        User presses a button or moves an axis. Returns:
          - (candidate, None)           for buttons (instant return)
          - (candidate, (lo, hi))       for axes (range recorded during window)
          - (None, None)                if nothing detected
        """
        obs_range: dict[int, tuple[int, int]] = {}
        best: CandidateEvent | None = None
        early: CandidateEvent | None = None
        deadline = time.monotonic() + duration_s

        self._try_grab()
        try:
            while time.monotonic() < deadline and early is None:
                remaining = deadline - time.monotonic()
                sys.stdout.write(f"\r  Listening... {remaining:.0f}s  ")
                sys.stdout.flush()
                r, _, _ = select.select([self._device.fd], [], [], min(remaining, 0.1))
                if not r:
                    continue
                try:
                    for event in self._device.read():
                        if event.type == ecodes.EV_ABS:
                            lo, hi = obs_range.get(
                                event.code, (event.value, event.value)
                            )
                            obs_range[event.code] = (
                                min(lo, event.value),
                                max(hi, event.value),
                            )
                        candidate = self._score(event, baseline)
                        if candidate is None:
                            continue
                        if candidate.confidence >= 1.0:
                            early = candidate
                            break
                        if best is None or candidate.confidence > best.confidence:
                            best = candidate
                except BlockingIOError:
                    pass
        except OSError:
            print("\n  [device disconnected]")
        finally:
            self._ungrab()
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

        if early is not None:
            return early, None

        calibrated = None
        if (
            best is not None
            and best.ev_type == ecodes.EV_ABS
            and best.ev_code in obs_range
        ):
            lo, hi = obs_range[best.ev_code]
            if hi > lo:
                calibrated = (lo, hi)
        return best, calibrated

    def listen(
        self, baseline: dict[int, float], duration_s: float = 3.0
    ) -> CandidateEvent | None:
        """
        Watch for intentional input for up to `duration_s` seconds.
        Returns the highest-confidence CandidateEvent, or None.
        Buttons (EV_KEY value=1) return immediately (confidence=1.0).
        Noisy axes require larger movement to register (beyond their baseline drift).
        """
        best: CandidateEvent | None = None
        deadline = time.monotonic() + duration_s

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                r, _, _ = select.select([self._device.fd], [], [], remaining)
                if not r:
                    break
                try:
                    for event in self._device.read():
                        candidate = self._score(event, baseline)
                        if candidate is None:
                            continue
                        if candidate.confidence >= 1.0:
                            return candidate
                        if best is None or candidate.confidence > best.confidence:
                            best = candidate
                except BlockingIOError:
                    pass
        except OSError:
            print("  [device disconnected during listen]")
        finally:
            self._ungrab()

        return best

    def _score(
        self, event: evdev.InputEvent, baseline: dict[int, float]
    ) -> CandidateEvent | None:
        if event.type == ecodes.EV_KEY and event.value == 1:
            return CandidateEvent(ecodes.EV_KEY, event.code, 1, 1.0, None)

        if event.type == ecodes.EV_ABS:
            try:
                abs_info = self._device.absinfo(event.code)
            except Exception:
                return None
            span = abs_info.max - abs_info.min
            if span <= 0:
                return None
            midpoint = baseline.get(event.code, (abs_info.min + abs_info.max) / 2)
            delta = abs(event.value - midpoint)
            if event.code in self.noisy_axes:
                drift = self.axis_drift.get(event.code, span * 0.05)
                threshold = max(drift * 2, span * 0.25)
            else:
                threshold = max(abs_info.flat * 3, span * 0.15)
            if delta >= threshold:
                confidence = min(delta / (span / 2), 1.0)
                return CandidateEvent(
                    ecodes.EV_ABS, event.code, event.value, confidence, abs_info
                )

        return None


# ---------------------------------------------------------------------------
# SmartDefaults
# ---------------------------------------------------------------------------


class SmartDefaults:
    """Infers transform fields from a detected event and a target Surface."""

    @staticmethod
    def infer(
        candidate: CandidateEvent,
        target: Surface,
        calibrated_range: tuple[int, int] | None = None,
    ) -> dict:
        base: dict = {
            "source_type": candidate.ev_type,
            "source_code": candidate.ev_code,
            "target": target.value,
        }

        if candidate.ev_type == ecodes.EV_KEY:
            if target.is_button:
                return {**base, "kind": "button"}
            on_value = 255 if target in _TRIGGER_SURFACES else 32767
            return {**base, "kind": "button", "on_value": on_value, "off_value": 0}

        # EV_ABS
        abs_info = candidate.abs_info
        if abs_info is None:
            return {**base, "kind": "button"}

        span = abs_info.max - abs_info.min

        if span <= 3:
            if target in _DPAD_SURFACES:
                return {**base, "kind": "hat"}
            return {**base, "kind": "button", "threshold": 1}

        deadzone = round(abs_info.flat / span, 3) if span > 0 else 0.0
        src_min = calibrated_range[0] if calibrated_range else abs_info.min
        src_max = calibrated_range[1] if calibrated_range else abs_info.max

        if target in _TRIGGER_SURFACES:
            return {
                **base,
                "kind": "axis",
                "source_min": src_min,
                "source_max": src_max,
                "target_min": 0,
                "target_max": 255,
                "deadzone": deadzone,
            }

        if target in _JOYSTICK_SURFACES:
            return {
                **base,
                "kind": "axis",
                "source_min": src_min,
                "source_max": src_max,
                "target_min": -32767,
                "target_max": 32767,
                "deadzone": deadzone,
            }

        if target.is_button:
            threshold = abs_info.max // 2 if abs_info.min >= 0 else 1
            return {**base, "kind": "button", "threshold": threshold}

        return {
            **base,
            "kind": "axis",
            "source_min": abs_info.min,
            "source_max": abs_info.max,
            "target_min": -32767,
            "target_max": 32767,
            "deadzone": deadzone,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pick_surface(already_mapped: set[Surface]) -> Surface | None:
    """Numbered surface picker menu grouped by buttons / axes."""
    buttons = [s for s in _SURFACE_MENU_ORDER if s.is_button]
    axes = [s for s in _SURFACE_MENU_ORDER if s.is_axis]

    def _fmt(s: Surface, idx: int) -> str:
        marker = "[*]" if s in already_mapped else "   "
        return f"{marker}[{idx:2d}] {s.value}"

    print("  Map to Xbox surface:")
    print("    Buttons:")
    btn_cols = 4
    for row_start in range(0, len(buttons), btn_cols):
        row = buttons[row_start : row_start + btn_cols]
        print("      " + "  ".join(_fmt(s, _SURFACE_MENU_ORDER.index(s)) for s in row))
    print("    Axes:")
    for s in axes:
        print(f"      {_fmt(s, _SURFACE_MENU_ORDER.index(s))}")
    print("    [*] = already mapped this session")

    while True:
        raw = input("  Surface number (or name prefix, Enter to skip): ").strip()
        if not raw:
            return None
        # numeric
        if raw.isdigit():
            idx = int(raw)
            if 0 <= idx < len(_SURFACE_MENU_ORDER):
                return _SURFACE_MENU_ORDER[idx]
            print(f"  Out of range: {idx}")
            continue
        # name prefix fallback
        upper = raw.upper()
        if upper in Surface.__members__:
            return Surface[upper]
        matches = [s for s in Surface if s.value.upper().startswith(upper)]
        if len(matches) == 1:
            return matches[0]
        if matches:
            print("  Did you mean: " + "  ".join(m.value for m in matches))
        else:
            print(f"  Unknown: {raw!r}")


def _print_status_table(profile_id: str, mappings: list[dict]) -> None:
    if not mappings:
        print(f"  (no mappings yet for [{profile_id}])")
        return
    print(f"  Mapped so far [{profile_id}]:")
    for m in mappings:
        tgt = m["target"]
        src_type = _type_name(m["source_type"])
        src_code = _code_name(m["source_type"], m["source_code"])
        kind = m["kind"]
        extras: list[str] = []
        if "source_min" in m:
            extras.append(f"src:{m['source_min']}..{m['source_max']}")
        if "deadzone" in m and m["deadzone"]:
            extras.append(f"dz={m['deadzone']:.2f}")
        if "on_value" in m:
            extras.append(f"on={m['on_value']} off={m.get('off_value', 0)}")
        if m.get("invert"):
            extras.append("↕inv")
        extra_str = "  " + "  ".join(extras) if extras else ""
        print(f"    {tgt:<22} {src_type} {src_code:<16} [{kind}]{extra_str}")


def _describe_candidate(c: CandidateEvent) -> str:
    name = _code_name(c.ev_type, c.ev_code)
    typ = _type_name(c.ev_type)
    if c.ev_type == ecodes.EV_KEY:
        return f"{typ} {c.ev_code} ({name})  [button]"
    abs_info = c.abs_info
    rng = f"range {abs_info.min}..{abs_info.max}" if abs_info else ""
    return f"{typ} {c.ev_code} ({name})  {rng}  [confidence: {c.confidence:.0%}]"


# ---------------------------------------------------------------------------
# MapperTUI
# ---------------------------------------------------------------------------


class MapperTUI:
    """Interactive session: select devices → detect inputs → assign surfaces → save YAML."""

    def __init__(self, output_path: str) -> None:
        self.output_path = output_path
        self.profiles: list[dict] = []
        self._already_mapped: set[Surface] = set()
        self._existing_runtime: dict = {"output_mode": "stdout"}
        self._existing_devices: dict[str, dict] = {}

        if Path(output_path).exists():
            try:
                raw = yaml.safe_load(Path(output_path).read_text()) or {}
                self._existing_runtime = raw.get("runtime", self._existing_runtime)
                existing_devices = raw.get("devices", [])
                self._existing_devices = {
                    d["id"]: d for d in existing_devices if "id" in d
                }
                print(f"Loaded existing config: {output_path}")
                if existing_devices:
                    ids = ", ".join(d.get("id", "?") for d in existing_devices)
                    print(f"  {len(existing_devices)} existing profile(s): {ids}")
                    print(
                        "  Re-mapping a profile replaces it; new profiles are appended."
                    )
            except Exception as e:
                print(f"Warning: could not load existing config ({e}), starting fresh.")

    def run(self) -> None:
        print("cursed-controls map — interactive config builder")
        print(f"Output: {self.output_path}")
        print()
        try:
            self._session()
        except KeyboardInterrupt:
            print()
            if self.profiles and any(p.get("mappings") for p in self.profiles):
                ans = input("Save partial config? (y/N): ").strip().lower()
                if ans == "y":
                    self._save()
            else:
                print("Nothing to save.")

    def _pre_connect(self) -> None:
        """Connect devices from the existing config, or scan for a Wiimote if no config."""
        from cursed_controls.bluetooth import (
            auto_connect_wiimote,
            connect_device,
            connect_wiimote,
            scan_for_wiimote,
            wait_for_evdev,
        )

        if not self._existing_devices:
            auto_connect_wiimote()
            return

        handled = False
        for device in self._existing_devices.values():
            conn = device.get("connection", {})
            conn_type = conn.get("type", "evdev")
            name = device.get("match", {}).get("name")

            if conn_type == "wiimote":
                handled = True
                if name and any(d.name == name for d in list_devices()):
                    print(f"  [{device['id']}] already connected")
                    continue
                print(f"  [{device['id']}] Scanning for Wiimote (press 1+2 or Sync)...")
                mac = scan_for_wiimote(conn.get("timeout_s", 60))
                if mac:
                    connect_wiimote(mac, timeout=10.0)
                    if name:
                        wait_for_evdev(name, timeout=10.0)
                else:
                    print(f"  [{device['id']}] not found, continuing")

            elif conn_type == "bluetooth":
                handled = True
                if name and any(d.name == name for d in list_devices()):
                    print(f"  [{device['id']}] already connected")
                    continue
                mac = conn.get("mac")
                if mac:
                    print(f"  [{device['id']}] Connecting {mac}...")
                    connect_device(mac, conn.get("timeout_s", 30))
                    if name:
                        wait_for_evdev(name, timeout=10.0)

        if not handled:
            auto_connect_wiimote()

    def _session(self) -> None:
        self._pre_connect()
        print()
        devices = self._step_select_devices()
        if not devices:
            print("No devices selected. Exiting.")
            return

        for info, ev_dev in devices:
            profile_id = self._ask_profile_id(info)
            mappings = self._step_map_device(info, ev_dev, profile_id)
            if mappings:
                match_key = "uniq" if info.uniq else "name" if info.name else "phys"
                match_val = info.uniq or info.name or info.phys
                self.profiles.append(
                    {
                        "id": profile_id,
                        "match": {match_key: match_val},
                        "mappings": mappings,
                    }
                )

        if not any(p.get("mappings") for p in self.profiles):
            print("No mappings recorded. Not saving.")
            return

        self._step_review()
        self._save()

    def _step_select_devices(self) -> list[tuple[DiscoveredDevice, evdev.InputDevice]]:
        all_devices = list_devices()
        if not all_devices:
            print("No input devices found.")
            return []

        print("Available input devices:")
        for i, d in enumerate(all_devices):
            print(f"  [{i}] {d.path:<22} {d.name}")
        print()

        raw = input("Select device numbers (comma-separated): ").strip()
        selected = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                idx = int(token)
                info = all_devices[idx]
                try:
                    ev_dev = evdev.InputDevice(info.path)
                    selected.append((info, ev_dev))
                except PermissionError:
                    print(
                        f"  Cannot open {info.path}: permission denied. "
                        "Run with sudo or add your user to the 'input' group."
                    )
                except Exception as e:
                    print(f"  Cannot open {info.path}: {e}")
            except (ValueError, IndexError):
                print(f"  Invalid index: {token!r}")

        return selected

    def _ask_profile_id(self, info: DiscoveredDevice) -> str:
        default = info.name.replace(" ", "-") if info.name else "device"
        print()
        print(f"  Profile ID: a short name for this device in the config file.")
        print(f"  It appears in logs and is used to match/update existing profiles.")
        print(f'  Examples: "wiimote", "nunchuk", "my-gamepad"')
        raw = input(f"  Profile ID [{default}]: ").strip()
        return raw or default

    def _step_map_device(
        self, info: DiscoveredDevice, ev_dev: evdev.InputDevice, profile_id: str
    ) -> list[dict]:
        detector = InputDetector(ev_dev)
        mappings: list[dict] = []
        mapped_sources: set[tuple[int, int]] = set()

        print()
        print(f"Mapping: {info.name}  [{info.path}]")
        print()
        print("  Press a button or move an axis on the controller to detect it,")
        print("  then choose which Xbox button/axis it maps to.")
        print()

        while True:
            print("  ─────────────────────────────────────────────────")
            prompt = (
                input("  [Enter] detect next   [d] done   [u] undo last\n  > ")
                .strip()
                .lower()
            )

            if prompt == "d":
                break

            if prompt == "u":
                if mappings:
                    removed = mappings.pop()
                    tgt = removed.get("target", "?")
                    try:
                        self._already_mapped.discard(Surface(tgt))
                    except ValueError:
                        pass
                    print(f"  Undone: {tgt}")
                else:
                    print("  Nothing to undo.")
                print()
                _print_status_table(profile_id, mappings)
                print()
                continue

            # detect
            print("  Sampling baseline...", end="", flush=True)
            baseline = detector.sample_baseline(0.3)
            if detector.noisy_axes:
                noisy_names = [
                    _code_name(ecodes.EV_ABS, c) for c in detector.noisy_axes
                ]
                print(
                    f"\n  ⚠  Drifty axes detected ({', '.join(noisy_names)})"
                    " — push firmly and hold to the extreme"
                )
            else:
                print()

            candidate, calibrated_range = detector.detect_and_calibrate(
                baseline, duration_s=6.0
            )

            if candidate is None:
                print("  No input detected.")
                again = input("  Try again? (Y/n): ").strip().lower()
                if again != "n":
                    continue
                break

            print(f"  Detected: {_describe_candidate(candidate)}")
            if calibrated_range:
                print(
                    f"  Calibrated range: {calibrated_range[0]}..{calibrated_range[1]}"
                )

            src_key = (candidate.ev_type, candidate.ev_code)
            if src_key in mapped_sources:
                print(
                    f"  Note: {_code_name(candidate.ev_type, candidate.ev_code)} "
                    "is already mapped in this profile."
                )

            print()
            surface = _pick_surface(self._already_mapped)
            if surface is None:
                print("  Skipped.")
                print()
                continue

            mapping = SmartDefaults.infer(candidate, surface, calibrated_range)

            # offer invert for axes that moved in the negative direction
            if (
                candidate.ev_type == ecodes.EV_ABS
                and candidate.abs_info is not None
                and candidate.value
                < (candidate.abs_info.min + candidate.abs_info.max) / 2
                and surface in _JOYSTICK_SURFACES
            ):
                ans = (
                    input("  Axis moved in the negative direction — invert? (y/N): ")
                    .strip()
                    .lower()
                )
                if ans == "y":
                    mapping["invert"] = True

            print(f"  → {surface.value}  [{mapping['kind']}]")
            mappings.append(mapping)
            mapped_sources.add(src_key)
            self._already_mapped.add(surface)

            print()
            _print_status_table(profile_id, mappings)
            print()

        return mappings

    def _step_review(self) -> None:
        print()
        print("─" * 60)
        all_mappings: list[tuple[int, int, dict]] = []
        for pi, profile in enumerate(self.profiles):
            print(f"Profile [{profile['id']}]  match: {profile['match']}")
            for mi, m in enumerate(profile.get("mappings", [])):
                label = f"  [{len(all_mappings)}] "
                src = f"{_type_name(m['source_type'])} {_code_name(m['source_type'], m['source_code'])}"
                tgt = m["target"]
                kind = m["kind"]
                extra = ""
                if "source_min" in m:
                    extra = f"  src:{m['source_min']}..{m['source_max']}"
                print(f"{label}{src:<28} → {tgt:<22} [{kind}]{extra}")
                all_mappings.append((pi, mi, m))
        print()

        raw = input("Remove a mapping by number (or Enter to save): ").strip()
        if raw.isdigit():
            idx = int(raw)
            if 0 <= idx < len(all_mappings):
                pi, mi, m = all_mappings[idx]
                self.profiles[pi]["mappings"].pop(mi)
                print(f"  Removed mapping [{idx}]")

    def _save(self) -> None:
        merged = dict(self._existing_devices)
        for profile in self.profiles:
            merged[profile["id"]] = profile

        data = {
            "runtime": self._existing_runtime,
            "devices": list(merged.values()),
        }
        text = yaml.dump(
            data, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
        with open(self.output_path, "w") as f:
            f.write(text)
        print(f"\nSaved to {self.output_path}")
        if self._existing_runtime.get("output_mode") == "stdout":
            print(
                "Change runtime.output_mode to 'gadget' when ready to run on hardware."
            )
