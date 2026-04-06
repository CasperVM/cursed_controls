from __future__ import annotations

from dataclasses import dataclass
import selectors
import time
from typing import Iterable

import evdev

from cursed_controls.bluetooth import (
    connect_device,
    connect_wiimote,
    scan_for_wiimote,
    wait_for_evdev,
)
from cursed_controls.config import (
    AppConfig,
    ConnectionType,
    DeviceProfile,
    MappingRule,
    TransformKind,
)
from cursed_controls.discovery import DiscoveredDevice, list_devices
from cursed_controls.output import OutputSink
from cursed_controls.rumble import ForceFeedback
from cursed_controls.xbox import Surface, XboxControllerState


@dataclass(frozen=True)
class BindingIssue:
    profile_id: str
    reason: str
    candidates: tuple[DiscoveredDevice, ...] = ()


class BindingError(RuntimeError):
    def __init__(self, issues: Iterable[BindingIssue]):
        self.issues = list(issues)
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        lines = ["device binding failed"]
        for issue in self.issues:
            lines.append(f"- {issue.profile_id}: {issue.reason}")
            for candidate in issue.candidates:
                lines.append(
                    "  * "
                    f"{candidate.path} name={candidate.name!r} uniq={candidate.uniq!r} "
                    f"phys={candidate.phys!r} parent_uhid={candidate.parent_uhid!r} "
                    f"composite={candidate.is_composite} parent={candidate.is_composite_parent}"
                )
        return "\n".join(lines)


@dataclass
class PlannedBinding:
    profile: DeviceProfile
    info: DiscoveredDevice


@dataclass
class BoundDevice:
    profile: DeviceProfile
    info: DiscoveredDevice
    device: evdev.InputDevice
    ff: ForceFeedback | None = None

    @property
    def fd(self) -> int:
        return self.device.fd


class BindingPlanner:
    def __init__(self, profiles: Iterable[DeviceProfile]):
        self.profiles = list(profiles)

    def plan(self, devices: Iterable[DiscoveredDevice]) -> list[PlannedBinding]:
        available = list(devices)
        issues: list[BindingIssue] = []
        planned: list[PlannedBinding] = []
        claimed_paths: dict[str, str] = {}

        for profile in self.profiles:
            matches = [device for device in available if _matches(profile, device)]
            if not matches:
                issues.append(BindingIssue(profile.id, "no matching device"))
                continue
            if len(matches) > 1:
                issues.append(
                    BindingIssue(
                        profile.id, "multiple matching devices", tuple(matches)
                    )
                )
                continue

            match = matches[0]
            previous = claimed_paths.get(match.path)
            if previous is not None:
                issues.append(
                    BindingIssue(
                        profile.id,
                        f"device {match.path} already claimed by profile {previous}",
                        (match,),
                    )
                )
                continue

            claimed_paths[match.path] = profile.id
            planned.append(PlannedBinding(profile=profile, info=match))

        if issues:
            raise BindingError(issues)
        return planned


class Mapper:
    """Maps input events to Xbox controller state."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.state = XboxControllerState()

    def apply(self, rule: MappingRule, event: evdev.InputEvent) -> bool:
        """Apply a single mapping rule to an input event."""
        transform = rule.transform
        if transform.kind is TransformKind.BUTTON:
            pressed = event.value >= transform.threshold
            if rule.target.is_button:
                return self.state.set_button(rule.target, pressed)

            on_value = (
                transform.on_value
                if transform.on_value is not None
                else (
                    255
                    if rule.target in {Surface.LEFT_TRIGGER, Surface.RIGHT_TRIGGER}
                    else 32767
                )
            )
            off_value = transform.off_value if transform.off_value is not None else 0
            return self.state.set_axis(rule.target, on_value if pressed else off_value)

        if transform.kind is TransformKind.HAT:
            return self._apply_hat(rule, event)

        value = int(event.value)
        src_min = transform.source_min if transform.source_min is not None else -32768
        src_max = transform.source_max if transform.source_max is not None else 32767
        tgt_min = (
            transform.target_min
            if transform.target_min is not None
            else (
                0
                if rule.target in {Surface.LEFT_TRIGGER, Surface.RIGHT_TRIGGER}
                else -32767
            )
        )
        tgt_max = (
            transform.target_max
            if transform.target_max is not None
            else (
                255
                if rule.target in {Surface.LEFT_TRIGGER, Surface.RIGHT_TRIGGER}
                else 32767
            )
        )
        if (
            transform.deadzone
            and abs(value) < abs(src_max - src_min) * transform.deadzone / 2
        ):
            value = 0
        scaled = _scale(value, src_min, src_max, tgt_min, tgt_max)
        if transform.invert:
            scaled = tgt_min + tgt_max - scaled
        if rule.target.is_axis:
            return self.state.set_axis(rule.target, scaled)
        return self.state.set_button(rule.target, scaled >= transform.threshold)

    def _apply_hat(self, rule: MappingRule, event: evdev.InputEvent) -> bool:
        direction = _hat_target_direction(rule.target)
        if direction is None:
            return False

        axis_code, active_value = direction
        if event.type != evdev.ecodes.EV_ABS or event.code != axis_code:
            return False
        return self.state.set_button(rule.target, event.value == active_value)

    def process_event(self, profile: DeviceProfile, event: evdev.InputEvent) -> bool:
        """Process an input event against a device profile. Return True if state changed."""
        changed = False
        for rule in profile.mappings:
            if rule.source_type == event.type and rule.source_code == event.code:
                changed = self.apply(rule, event) or changed
        return changed


class Runtime:
    """Main event loop: reads input devices, maps to Xbox state, sends to sink."""

    def __init__(self, config: AppConfig, sink: OutputSink):
        self.config = config
        self.sink = sink
        self.mapper = Mapper(config)
        self.selector = selectors.DefaultSelector()
        self.bound_by_fd: dict[int, BoundDevice] = {}
        self.pending_profiles: list[DeviceProfile] = []
        self._last_rescan: float = 0.0

    def plan_bindings(
        self, devices: Iterable[DiscoveredDevice] | None = None
    ) -> list[PlannedBinding]:
        planner = BindingPlanner(self.config.devices)
        return planner.plan(list_devices() if devices is None else devices)

    def open_bindings(self, planned: Iterable[PlannedBinding]) -> list[BoundDevice]:
        bound = []
        for item in planned:
            dev = evdev.InputDevice(item.info.path)
            ff = ForceFeedback(dev)
            bound.append(
                BoundDevice(item.profile, item.info, dev, ff if ff.supported else None)
            )
        return bound

    def register_bound_devices(self, bound: Iterable[BoundDevice]) -> None:
        for item in bound:
            self.selector.register(item.fd, selectors.EVENT_READ, item)
            self.bound_by_fd[item.fd] = item

    def unregister_bound_device(self, bound: BoundDevice) -> None:
        fd = bound.fd
        if fd in self.bound_by_fd:
            self.bound_by_fd.pop(fd, None)
            try:
                self.selector.unregister(fd)
            except Exception:
                pass
        bound.device.close()

    def drain_ready(self, timeout: float | None = None) -> bool:
        changed = False
        for key, _mask in self.selector.select(timeout):
            bound = key.data
            changed = self._drain_device(bound) or changed
        return changed

    def _drain_device(self, bound: BoundDevice) -> bool:
        changed = False
        try:
            events = list(bound.device.read())
        except BlockingIOError:
            return False
        except OSError:
            self.unregister_bound_device(bound)
            self.pending_profiles.append(bound.profile)
            print(f"[{bound.profile.id}] disconnected, will retry")
            return False

        for event in events:
            if event.type == evdev.ecodes.EV_SYN:
                continue
            changed = self.mapper.process_event(bound.profile, event) or changed
        return changed

    def _already_in_evdev(self, profile: DeviceProfile) -> bool:
        """Return True if a device matching this profile is already in /dev/input/."""
        available = list_devices()
        return any(_matches(profile, d) for d in available)

    def _pre_connect(self) -> None:
        for profile in self.config.devices:
            conn = profile.connection
            if conn.type == ConnectionType.WIIMOTE:
                if self._already_in_evdev(profile):
                    print(f"[{profile.id}] Wiimote already connected, skipping scan")
                    continue
                print(f"[{profile.id}] Waiting for Wiimote (press 1+2 or Sync)...")
                mac = scan_for_wiimote(conn.timeout_s, conn.mac)
                if mac:
                    connect_wiimote(mac, timeout=10.0)
                    if profile.match.name:
                        wait_for_evdev(profile.match.name, timeout=10.0)
                else:
                    print(f"[{profile.id}] Wiimote not found, will retry")
            elif conn.type == ConnectionType.BLUETOOTH:
                if self._already_in_evdev(profile):
                    print(f"[{profile.id}] already connected, skipping")
                    continue
                print(f"[{profile.id}] Connecting {conn.mac}...")
                if conn.mac:
                    connect_device(conn.mac, conn.timeout_s)
                if profile.match.name:
                    wait_for_evdev(profile.match.name, timeout=10.0)
            # evdev: nothing to do, rescan loop will find it

    def _claimed_paths(self) -> set[str]:
        return {b.info.path for b in self.bound_by_fd.values()}

    def _try_bind_pending(self) -> None:
        available = list_devices()
        claimed = self._claimed_paths()
        still_pending = []
        for profile in self.pending_profiles:
            matches = [
                d for d in available if _matches(profile, d) and d.path not in claimed
            ]
            if not matches:
                still_pending.append(profile)
                continue
            if len(matches) > 1:
                # Composite devices (e.g. Wiimote) create multiple nodes with the
                # same name. Prefer the composite parent; skip if ambiguous.
                parents = [d for d in matches if d.is_composite_parent]
                if len(parents) == 1:
                    matches = parents
                else:
                    still_pending.append(profile)
                    continue
            planned = PlannedBinding(profile=profile, info=matches[0])
            bound = self.open_bindings([planned])
            self.register_bound_devices(bound)
            claimed.add(matches[0].path)
            print(f"[{profile.id}] bound to {matches[0].path}")
        self.pending_profiles = still_pending

    def _rescan_if_due(self) -> None:
        if not self.pending_profiles:
            return
        interval = self.config.runtime.rescan_interval_ms / 1000.0
        if time.monotonic() - self._last_rescan >= interval:
            self._try_bind_pending()
            self._last_rescan = time.monotonic()

    def run(self) -> None:
        self._pre_connect()
        self.pending_profiles = list(self.config.devices)
        self._try_bind_pending()
        self.sink.open()
        try:
            while True:
                if self.drain_ready(timeout=0.01):
                    self.sink.send(self.mapper.state)
                self._dispatch_rumble()
                self._rescan_if_due()
        finally:
            self._stop_all_rumble()
            for item in list(self.bound_by_fd.values()):
                self.unregister_bound_device(item)
            self.sink.close()

    def _dispatch_rumble(self) -> None:
        if not self.config.runtime.rumble:
            return
        result = self.sink.poll_rumble(slot=0)
        if result is None:
            return
        left, right = result
        for b in self.bound_by_fd.values():
            if b.ff is not None:
                b.ff.set_rumble(left, right)

    def _stop_all_rumble(self) -> None:
        for b in self.bound_by_fd.values():
            if b.ff is not None:
                b.ff.stop()


def _matches(profile: DeviceProfile, device: DiscoveredDevice) -> bool:
    match = profile.match
    return all(
        [
            match.name is None or match.name == device.name,
            match.uniq is None or match.uniq == device.uniq,
            match.phys is None or match.phys == device.phys,
        ]
    )


def _hat_target_direction(target: Surface) -> tuple[int, int] | None:
    mapping = {
        Surface.DPAD_LEFT: (evdev.ecodes.ABS_HAT0X, -1),
        Surface.DPAD_RIGHT: (evdev.ecodes.ABS_HAT0X, 1),
        Surface.DPAD_UP: (evdev.ecodes.ABS_HAT0Y, -1),
        Surface.DPAD_DOWN: (evdev.ecodes.ABS_HAT0Y, 1),
    }
    return mapping.get(target)


def _scale(value: int, src_min: int, src_max: int, tgt_min: int, tgt_max: int) -> int:
    """Scale a value from source range to target range."""
    if src_max == src_min:
        return tgt_min
    ratio = (value - src_min) / (src_max - src_min)
    scaled = tgt_min + ratio * (tgt_max - tgt_min)
    return int(max(min(scaled, max(tgt_min, tgt_max)), min(tgt_min, tgt_max)))
