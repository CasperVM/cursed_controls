from __future__ import annotations

import os
import select
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
        self._grabbed = False

    def _try_grab(self) -> None:
        try:
            self._device.grab()
            self._grabbed = True
        except IOError:
            self._grabbed = False  # another process holds it; proceed without

    def _ungrab(self) -> None:
        if self._grabbed:
            try:
                self._device.ungrab()
            except Exception:
                pass
            self._grabbed = False

    def calibrate_axis(self, code: int, duration_s: float = 4.0) -> tuple[int, int]:
        """Watch axis `code` and return the (min, max) values actually observed.

        Falls back to absinfo declared range if no events arrive or the device
        doesn't move far enough to exceed the inverted sentinels.
        """
        try:
            info = self._device.absinfo(code)
            # Start inverted so any real reading beats the sentinels
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
        self.axis_drift: dict[int, float] = {}  # observed spread during baseline
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
            # For noisy axes, require movement well beyond the observed baseline drift
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

        # fallback: generic axis→axis
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


def _print_surface_menu(already_mapped: set[Surface]) -> None:
    buttons = [s for s in Surface if s.is_button]
    axes = [s for s in Surface if s.is_axis]
    print(
        "  Buttons:",
        "  ".join(f"[*]{s.value}" if s in already_mapped else s.value for s in buttons),
    )
    print(
        "  Axes:   ",
        "  ".join(f"[*]{s.value}" if s in already_mapped else s.value for s in axes),
    )
    print("  [*] = already mapped this session")


def _pick_surface(already_mapped: set[Surface]) -> Surface | None:
    _print_surface_menu(already_mapped)
    while True:
        raw = input("  Surface (name or prefix, Enter to skip): ").strip().upper()
        if not raw:
            return None
        if raw in Surface.__members__:
            return Surface[raw]
        matches = [s for s in Surface if s.value.upper().startswith(raw)]
        if len(matches) == 1:
            return matches[0]
        if matches:
            print("  Did you mean: " + "  ".join(m.value for m in matches))
        else:
            print(f"  Unknown: {raw!r}")


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
                    print("  Re-mapping a profile replaces it; new profiles are appended.")
            except Exception as e:
                print(f"Warning: could not load existing config ({e}), starting fresh.")

    def run(self) -> None:
        print("cursed-controls map, interactive config builder")
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

    def _session(self) -> None:
        devices = self._step_select_devices()
        if not devices:
            print("No devices selected. Exiting.")
            return

        for info, ev_dev in devices:
            profile_id = self._ask_profile_id(info)
            mappings = self._step_map_device(info, ev_dev)
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
                        "Add your user to the 'input' group."
                    )
                except Exception as e:
                    print(f"  Cannot open {info.path}: {e}")
            except (ValueError, IndexError):
                print(f"  Invalid index: {token!r}")

        return selected

    def _ask_profile_id(self, info: DiscoveredDevice) -> str:
        default = (info.identifier or info.name or "device").replace(" ", "-")[:20]
        raw = input(f"Profile ID [{default}]: ").strip()
        return raw or default

    def _step_map_device(
        self, info: DiscoveredDevice, ev_dev: evdev.InputDevice
    ) -> list[dict]:
        detector = InputDetector(ev_dev)
        mappings: list[dict] = []
        mapped_sources: set[tuple[int, int]] = set()

        print()
        print(f"Mapping: {info.name}  [{info.path}]")
        print("Type 'done' to finish, press Enter to skip a cycle.")
        print()

        while True:
            prompt = input("Press/move input to map (or 'done'): ").strip().lower()
            if prompt == "done":
                break

            print("  Sampling baseline...", end="", flush=True)
            baseline = detector.sample_baseline(0.3)
            noisy = [_code_name(ecodes.EV_ABS, c) for c in detector.noisy_axes]
            if noisy:
                print(f" (high-threshold axes: {', '.join(noisy)})", end="")
            print()

            print("  Listening... (3s)", end="", flush=True)
            candidate = detector.listen(baseline, 3.0)
            print()

            if candidate is None:
                print("  No input detected.")
                again = input("  Try again? (Y/n): ").strip().lower()
                if again != "n":
                    continue
                else:
                    break

            print(f"  Detected: {_describe_candidate(candidate)}")

            src_key = (candidate.ev_type, candidate.ev_code)
            if src_key in mapped_sources:
                print(
                    f"  Note: {_code_name(candidate.ev_type, candidate.ev_code)} "
                    "is already mapped in this profile."
                )

            surface = _pick_surface(self._already_mapped)
            if surface is None:
                print("  Skipped.")
                continue

            calibrated_range = None
            if (
                candidate.ev_type == ecodes.EV_ABS
                and candidate.abs_info is not None
                and (candidate.abs_info.max - candidate.abs_info.min) > 3
                and surface in (_JOYSTICK_SURFACES | _TRIGGER_SURFACES)
            ):
                print("  Wiggle the axis to its extremes, then press Enter...")
                input()
                print("  Calibrating...", end="", flush=True)
                calibrated_range = detector.calibrate_axis(candidate.ev_code, duration_s=0.3)
                print(f" observed range: {calibrated_range[0]}..{calibrated_range[1]}")

            mapping = SmartDefaults.infer(candidate, surface, calibrated_range)

            # offer invert for axes that moved in the negative direction
            if (
                candidate.ev_type == ecodes.EV_ABS
                and candidate.abs_info is not None
                and candidate.value
                < (candidate.abs_info.min + candidate.abs_info.max) / 2
            ):
                ans = input("  Axis moved negative, invert? (y/N): ").strip().lower()
                if ans == "y":
                    mapping["invert"] = True

            print(f"  → {surface.value}  [{mapping['kind']}]")
            mappings.append(mapping)
            mapped_sources.add(src_key)
            self._already_mapped.add(surface)

        return mappings

    def _step_review(self) -> None:
        print()
        print("─" * 60)
        all_mappings: list[
            tuple[int, int, dict]
        ] = []  # (profile_idx, mapping_idx, dict)
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

        raw = input("Remove a mapping by number (or Enter to skip): ").strip()
        if raw.isdigit():
            idx = int(raw)
            if 0 <= idx < len(all_mappings):
                pi, mi, m = all_mappings[idx]
                self.profiles[pi]["mappings"].pop(mi)
                print(f"  Removed mapping [{idx}]")

    def _save(self) -> None:
        # Overlay this session's profiles onto existing ones (keyed by id)
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
            print("Change runtime.output_mode to 'gadget' when ready to run on hardware.")
