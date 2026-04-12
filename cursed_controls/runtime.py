from __future__ import annotations

from dataclasses import dataclass, field
import queue
import selectors
import threading
import time
from typing import Callable, Iterable

import evdev

from cursed_controls.bluetooth import (
    connect_device,
    connect_wiimote,
    is_device_connected,
    reconnect_bluetooth,
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
from cursed_controls.rumble import ForceFeedback, WiimoteFeedback
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
    slot: int = 0
    state: XboxControllerState = field(default_factory=XboxControllerState)
    rumble_test_until: float = 0.0  # monotonic deadline — skip auto-stop until then

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

    def apply(
        self,
        rule: MappingRule,
        event: evdev.InputEvent,
        state: XboxControllerState | None = None,
    ) -> bool:
        """Apply a single mapping rule to an input event."""
        s = state if state is not None else self.state
        transform = rule.transform
        if transform.kind is TransformKind.BUTTON:
            pressed = event.value >= transform.threshold
            if rule.target.is_button:
                return s.set_button(rule.target, pressed)

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
            return s.set_axis(rule.target, on_value if pressed else off_value)

        if transform.kind is TransformKind.HAT:
            return self._apply_hat(rule, event, s)

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
            return s.set_axis(rule.target, scaled)
        return s.set_button(rule.target, scaled >= transform.threshold)

    def _apply_hat(
        self,
        rule: MappingRule,
        event: evdev.InputEvent,
        state: XboxControllerState | None = None,
    ) -> bool:
        s = state if state is not None else self.state
        # Resolve active value: explicit on_value overrides the direction default
        if rule.transform.on_value is not None:
            active_value = rule.transform.on_value
        else:
            direction = _hat_target_direction(rule.target)
            if direction is None:
                return False
            active_value = direction[1]
        if rule.transform.invert:
            active_value = -active_value
        return s.set_button(rule.target, event.value == active_value)

    def process_event(
        self,
        profile: DeviceProfile,
        event: evdev.InputEvent,
        state: XboxControllerState | None = None,
    ) -> bool:
        """Process an input event against a device profile. Return True if state changed."""
        changed = False
        for rule in profile.mappings:
            if rule.source_type == event.type and rule.source_code == event.code:
                changed = self.apply(rule, event, state) or changed
        return changed


_RECONNECT_INTERVAL_S: float = (
    10.0  # minimum seconds between reconnect attempts per profile
)


@dataclass
class _RumbleState:
    current_rumble: tuple[int, int] = (0, 0)
    last_packet: float = 0.0
    last_heartbeat: float = 0.0
    stop_pending: float = 0.0  # monotonic time of last (0,0), 0 = none
    activate_times: list[float] = field(default_factory=list)


class Runtime:
    """Main event loop: reads input devices, maps to Xbox state, sends to sink."""

    def __init__(
        self,
        config: AppConfig,
        sink: OutputSink,
        on_event: Callable[[dict], None] | None = None,
    ):
        self.config = config
        self.sink = sink
        self.mapper = Mapper(config)
        self.selector = selectors.DefaultSelector()
        self.bound_by_fd: dict[int, BoundDevice] = {}
        self.pending_profiles: list[DeviceProfile] = []
        # Queue used by the background rescan thread to post PlannedBinding results
        # to the main event loop without blocking it.
        self._bind_queue: queue.Queue[PlannedBinding] = queue.Queue()
        # MAC address discovered/used at startup for each profile, keyed by profile.id.
        # Persisted so the reconnect path can reconnect without re-scanning.
        self._connected_macs: dict[str, str] = {}
        # Timestamp of last reconnect attempt per profile, to throttle retries.
        self._last_reconnect: dict[str, float] = {}
        # Profiles currently being reconnected in a background thread.
        self._reconnecting: set[str] = set()
        self._on_event: Callable[[dict], None] = on_event or (lambda e: None)
        self._stop_event: threading.Event = threading.Event()
        # Per-slot rumble state (keyed by slot index)
        self._slot_rumble: dict[int, _RumbleState] = {}
        self._suppressed_reconnect_macs: set[str] = set()

    def stop(self) -> None:
        """Signal the run() loop to exit. Safe to call from any thread."""
        self._stop_event.set()

    def suppress_reconnect(self, mac: str) -> None:
        """Prevent auto-reconnect for a MAC (e.g. user-initiated disconnect)."""
        self._suppressed_reconnect_macs.add(mac.upper())

    def _fire_event(self, event: dict) -> None:
        try:
            self._on_event(event)
        except Exception as exc:
            print(f"[runtime] on_event callback raised: {exc!r}", flush=True)

    def plan_bindings(
        self, devices: Iterable[DiscoveredDevice] | None = None
    ) -> list[PlannedBinding]:
        planner = BindingPlanner(self.config.devices)
        return planner.plan(list_devices() if devices is None else devices)

    def open_bindings(self, planned: Iterable[PlannedBinding]) -> list[BoundDevice]:
        bound = []
        for item in planned:
            dev = evdev.InputDevice(item.info.path)
            if item.profile.connection.type == ConnectionType.WIIMOTE:
                ff: ForceFeedback | WiimoteFeedback = WiimoteFeedback(dev)
            else:
                ff = ForceFeedback(dev)
            bd = BoundDevice(
                item.profile,
                item.info,
                dev,
                ff if ff.supported else None,
                slot=item.profile.slot,
                state=XboxControllerState(),
            )
            if isinstance(bd.ff, WiimoteFeedback):
                bd.ff.set_player_led(bd.slot)
            bound.append(bd)
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
            self._fire_event(
                {"type": "device_disconnected", "profile_id": bound.profile.id}
            )
            return False

        for event in events:
            if event.type == evdev.ecodes.EV_SYN:
                continue
            changed = (
                self.mapper.process_event(bound.profile, event, bound.state) or changed
            )
        return changed

    def _already_in_evdev(self, profile: DeviceProfile) -> bool:
        """Return True if a device matching this profile is already in /dev/input/."""
        available = list_devices()
        return any(_matches(profile, d) for d in available)

    def _pre_connect(self) -> None:
        for profile in self.config.devices:
            if self._stop_event.is_set():
                return
            conn = profile.connection
            if conn.type == ConnectionType.WIIMOTE:
                if self._already_in_evdev(profile):
                    print(f"[{profile.id}] Wiimote already connected, skipping scan")
                    # Persist any configured MAC so reconnect works even when we skip scan
                    if conn.mac:
                        self._connected_macs[profile.id] = conn.mac
                    continue
                print(f"[{profile.id}] Waiting for Wiimote (press 1+2 or Sync)...")
                mac = scan_for_wiimote(conn.timeout_s, conn.mac)
                if mac:
                    # Persist the MAC first so reconnect loop can use it
                    self._connected_macs[profile.id] = mac
                    # If this is a newly discovered MAC (not in config), save it
                    # so the next service start can reconnect without scanning.
                    if mac != conn.mac:
                        conn.mac = mac  # update live config
                        self._fire_event(
                            {
                                "type": "wiimote_mac_discovered",
                                "profile_id": profile.id,
                                "mac": mac,
                            }
                        )
                    if is_device_connected(mac):
                        # Already BT-connected — trust+connect (no scan needed) and wait for evdev.
                        from cursed_controls.bluetooth import _run_bluetoothctl

                        _run_bluetoothctl("trust", mac, timeout=5.0)
                        _run_bluetoothctl("connect", mac, timeout=12.0)
                        if profile.match.name:
                            wait_for_evdev(profile.match.name, timeout=10.0)
                    else:
                        # Wiimote is off or not connectable right now.
                        # Skip blocking here — reconnect loop will handle it when it wakes.
                        print(
                            f"[{profile.id}] Wiimote not BT-connected, will reconnect when available"
                        )
                else:
                    print(f"[{profile.id}] Wiimote not found, will retry")
            elif conn.type == ConnectionType.BLUETOOTH:
                if self._already_in_evdev(profile):
                    print(f"[{profile.id}] already connected, skipping")
                    if conn.mac:
                        self._connected_macs[profile.id] = conn.mac
                    continue
                print(f"[{profile.id}] Connecting {conn.mac}...")
                if conn.mac:
                    connect_device(conn.mac, conn.timeout_s)
                    self._connected_macs[profile.id] = conn.mac
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
            self._sync_rumble_to_new(bound)
            claimed.add(matches[0].path)
            print(f"[{profile.id}] bound to {matches[0].path}")
            self._fire_event(
                {
                    "type": "device_bound",
                    "profile_id": profile.id,
                    "path": matches[0].path,
                }
            )
        self.pending_profiles = still_pending

    def _try_reconnect_bt(self, profile: DeviceProfile) -> None:
        """Attempt to reconnect a disconnected BT/Wiimote profile.

        Only fires if we have a known MAC and the throttle interval has passed.
        After a successful reconnect, waits for the evdev node to appear so
        the normal _try_bind_pending path can pick it up on the next rescan.
        """
        mac = self._connected_macs.get(profile.id) or profile.connection.mac
        if not mac:
            return
        if mac.upper() in self._suppressed_reconnect_macs:
            return

        now = time.monotonic()
        if now - self._last_reconnect.get(profile.id, 0.0) < _RECONNECT_INTERVAL_S:
            return
        if profile.id in self._reconnecting:
            return  # already reconnecting in background
        self._last_reconnect[profile.id] = now

        self._reconnecting.add(profile.id)
        is_wiimote = profile.connection.type == ConnectionType.WIIMOTE
        match_name = profile.match.name

        def _do_reconnect() -> None:
            try:
                # is_device_connected runs here (off main thread) — was 113ms on Pi Zero
                if is_device_connected(mac):
                    return
                print(
                    f"[{profile.id}] BT device {mac} not connected, attempting reconnect..."
                )
                if reconnect_bluetooth(
                    mac, is_wiimote, timeout=5.0, max_retries=3, backoff=1.0
                ):
                    print(
                        f"[{profile.id}] Reconnected {mac}, waiting for evdev node..."
                    )
                    if match_name:
                        wait_for_evdev(match_name, timeout=10.0)
                else:
                    print(f"[{profile.id}] Reconnect failed, will retry later")
            finally:
                self._reconnecting.discard(profile.id)

        threading.Thread(target=_do_reconnect, daemon=True).start()

    def _rescan_thread_body(self) -> None:
        """Background thread: does the slow list_devices() scan off the main event loop.

        Posts PlannedBinding results to _bind_queue for the main thread to open.
        Also triggers BT reconnect threads (is_device_connected runs inside those).
        """
        while not self._stop_event.is_set():
            interval = self.config.runtime.rescan_interval_ms / 1000.0
            self._stop_event.wait(timeout=interval)
            if self._stop_event.is_set():
                break
            if not self.pending_profiles:
                continue

            pending = list(self.pending_profiles)  # snapshot

            for profile in pending:
                if profile.connection.type in (
                    ConnectionType.BLUETOOTH,
                    ConnectionType.WIIMOTE,
                ):
                    self._try_reconnect_bt(profile)

            # list_devices() is the slow call (~1300 ms on Pi Zero) — runs here only
            claimed = set(self._claimed_paths())
            try:
                available = list_devices()
            except Exception as exc:
                print(f"[rescan] list_devices failed: {exc!r}", flush=True)
                continue

            for profile in pending:
                matches = [
                    d
                    for d in available
                    if _matches(profile, d) and d.path not in claimed
                ]
                if not matches:
                    continue
                if len(matches) > 1:
                    parents = [d for d in matches if d.is_composite_parent]
                    if len(parents) != 1:
                        continue
                    matches = parents
                self._bind_queue.put(PlannedBinding(profile=profile, info=matches[0]))
                claimed.add(matches[0].path)

    def _sync_rumble_to_new(self, bound: list[BoundDevice]) -> None:
        """If rumble is currently active on a slot, push it to freshly bound devices immediately.

        Without this, the new ForceFeedback instance has effect_id=-1 and
        heartbeat() silently does nothing until the next set_rumble() call.
        """
        for b in bound:
            if b.ff is None or not b.profile.rumble:
                continue
            rs = self._slot_rumble.get(b.slot)
            if rs and rs.current_rumble != (0, 0):
                left, right = rs.current_rumble
                b.ff.set_rumble(left, right)

    def _drain_bind_queue(self) -> None:
        """Drain PlannedBinding results posted by the background rescan thread.

        This is the only rescan-related call on the main event loop — it's O(1)
        when the queue is empty (just a non-blocking queue check).
        """
        while True:
            try:
                planned = self._bind_queue.get_nowait()
            except queue.Empty:
                break
            if planned.profile not in self.pending_profiles:
                continue  # already bound or removed
            if planned.info.path in self._claimed_paths():
                continue  # device claimed by another profile
            bound = self.open_bindings([planned])
            self.register_bound_devices(bound)
            self._sync_rumble_to_new(bound)
            self.pending_profiles.remove(planned.profile)
            print(f"[{planned.profile.id}] bound to {planned.info.path}")
            self._fire_event(
                {
                    "type": "device_bound",
                    "profile_id": planned.profile.id,
                    "path": planned.info.path,
                }
            )

    def run(self) -> None:
        self._pre_connect()
        if self._stop_event.is_set():
            return
        self.pending_profiles = list(self.config.devices)
        self._try_bind_pending()  # initial bind at startup (one-time, on this thread)
        self.sink.open()

        rescan_thread = threading.Thread(
            target=self._rescan_thread_body, daemon=True, name="rescan"
        )
        rescan_thread.start()

        try:
            while not self._stop_event.is_set():
                self._drain_bind_queue()  # fast: O(1) queue check when empty
                if self.drain_ready(timeout=0.001):  # 1 ms — reduced from 10 ms
                    # Merge all devices on the same slot: OR buttons, MAX axes.
                    slot_states: dict[int, XboxControllerState] = {}
                    for bd in self.bound_by_fd.values():
                        s = bd.state
                        if bd.slot not in slot_states:
                            slot_states[bd.slot] = XboxControllerState(
                                a=s.a, b=s.b, x=s.x, y=s.y,
                                lb=s.lb, rb=s.rb, l3=s.l3, r3=s.r3,
                                start=s.start, options=s.options, xbox=s.xbox,
                                dpad_up=s.dpad_up, dpad_down=s.dpad_down,
                                dpad_left=s.dpad_left, dpad_right=s.dpad_right,
                                left_trigger=s.left_trigger, right_trigger=s.right_trigger,
                                left_joystick_x=s.left_joystick_x,
                                left_joystick_y=s.left_joystick_y,
                                right_joystick_x=s.right_joystick_x,
                                right_joystick_y=s.right_joystick_y,
                            )
                        else:
                            m = slot_states[bd.slot]
                            m.a = m.a or s.a
                            m.b = m.b or s.b
                            m.x = m.x or s.x
                            m.y = m.y or s.y
                            m.lb = m.lb or s.lb
                            m.rb = m.rb or s.rb
                            m.l3 = m.l3 or s.l3
                            m.r3 = m.r3 or s.r3
                            m.start = m.start or s.start
                            m.options = m.options or s.options
                            m.xbox = m.xbox or s.xbox
                            m.dpad_up = m.dpad_up or s.dpad_up
                            m.dpad_down = m.dpad_down or s.dpad_down
                            m.dpad_left = m.dpad_left or s.dpad_left
                            m.dpad_right = m.dpad_right or s.dpad_right
                            m.left_trigger = max(m.left_trigger, s.left_trigger)
                            m.right_trigger = max(m.right_trigger, s.right_trigger)
                            m.left_joystick_x = max(m.left_joystick_x, s.left_joystick_x, key=abs)
                            m.left_joystick_y = max(m.left_joystick_y, s.left_joystick_y, key=abs)
                            m.right_joystick_x = max(m.right_joystick_x, s.right_joystick_x, key=abs)
                            m.right_joystick_y = max(m.right_joystick_y, s.right_joystick_y, key=abs)
                    for slot, merged in slot_states.items():
                        self.sink.send(merged, slot=slot)
                self._dispatch_rumble()
        finally:
            self._stop_all_rumble()
            for item in list(self.bound_by_fd.values()):
                self.unregister_bound_device(item)
            self.sink.close()

    def _dispatch_rumble(self) -> None:
        if not self.config.runtime.rumble:
            return
        now = time.monotonic()
        active_slots = {bd.slot for bd in self.bound_by_fd.values()}
        for slot in active_slots:
            if slot not in self._slot_rumble:
                self._slot_rumble[slot] = _RumbleState()
            self._dispatch_slot_rumble(slot, now)

    def _dispatch_slot_rumble(self, slot: int, now: float) -> None:
        rs = self._slot_rumble[slot]
        rt = self.config.runtime
        devices = [
            b for b in self.bound_by_fd.values() if b.slot == slot and b.profile.rumble
        ]
        result = self.sink.poll_rumble(slot=slot)

        if result is not None:
            left, right = result
            rs.last_packet = now
            print(f"[rumble:{slot}] {now:.3f} packet ({left},{right})", flush=True)

            if left == 0 and right == 0:
                # Don't stop immediately — xpad wireless auto-sends (0,0) ~300ms
                # after every ON packet as a keepalive cycle. Debounce so a follow-up
                # ON packet cancels the stop and motors run continuously.
                if rs.current_rumble != (0, 0):
                    rs.stop_pending = now
                return

            # Non-zero packet.
            rs.stop_pending = 0.0

            if rs.current_rumble != (0, 0):
                # Already active — update immediately (no gate needed).
                if (left, right) != rs.current_rumble:
                    rs.current_rumble = (left, right)
                    rs.last_heartbeat = now
                    for b in devices:
                        if b.ff is not None:
                            b.ff.set_rumble(left, right)
                return

            # Currently stopped — require N packets within window before activating.
            # Blocks isolated xpad retransmissions (seconds apart) while allowing
            # sustained game rumble (16 ms apart) and Steam ping (~670 ms apart).
            rs.activate_times.append(now)
            rs.activate_times = [
                t for t in rs.activate_times if now - t < rt.rumble_activate_window_s
            ]
            print(
                f"[rumble:{slot}] {now:.3f} activate gate ({left},{right}) "
                f"[{len(rs.activate_times)}/{rt.rumble_activate_count}]",
                flush=True,
            )
            if len(rs.activate_times) < rt.rumble_activate_count:
                return

            rs.activate_times = []
            rs.current_rumble = (left, right)
            rs.last_heartbeat = now
            for b in devices:
                if b.ff is not None:
                    b.ff.set_rumble(left, right)
            return

        if rs.current_rumble == (0, 0):
            return

        # Debounced stop: (0,0) was received but we're waiting to see if ON follows.
        if rs.stop_pending:
            if now - rs.stop_pending > rt.rumble_stop_debounce_s:
                print(
                    f"[rumble:{slot}] {now:.3f} debounce expired — stopping", flush=True
                )
                rs.current_rumble = (0, 0)
                rs.stop_pending = 0.0
                rs.activate_times = []
                for b in devices:
                    if b.ff is not None and now >= b.rumble_test_until:
                        b.ff.stop()
                return
            # Still debouncing — keep heartbeating so the effect doesn't expire
        elif now - rs.last_packet > rt.rumble_timeout_s:
            # No packet at all for too long — stop as fallback.
            print(f"[rumble:{slot}] {now:.3f} timeout — stopping", flush=True)
            rs.current_rumble = (0, 0)
            rs.stop_pending = 0.0
            rs.activate_times = []
            for b in devices:
                if b.ff is not None and now >= b.rumble_test_until:
                    b.ff.stop()
            return

        # Heartbeat: re-send EV_FF play periodically so Nintendo controllers
        # keep rumbling (hid-nintendo stops after ~100 ms without a refresh).
        if now - rs.last_heartbeat > rt.rumble_heartbeat_s:
            rs.last_heartbeat = now
            for b in devices:
                if b.ff is not None:
                    b.ff.heartbeat()

    def _stop_all_rumble(self) -> None:
        for b in self.bound_by_fd.values():
            if b.ff is not None and b.profile.rumble:
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
