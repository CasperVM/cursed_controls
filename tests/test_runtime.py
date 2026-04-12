"""Tests for the Mapper and Runtime."""

from types import SimpleNamespace

import evdev
import pytest
from evdev import ecodes

from cursed_controls.config import (
    AppConfig,
    ConnectionConfig,
    ConnectionType,
    DeviceMatch,
    DeviceProfile,
    MappingRule,
    RuntimeConfig,
    Transform,
    TransformKind,
)
from cursed_controls.discovery import DiscoveredDevice
from cursed_controls.output import FakeSink
from cursed_controls.runtime import (
    BindingError,
    BindingPlanner,
    BoundDevice,
    Mapper,
    PlannedBinding,
    Runtime,
    _RECONNECT_INTERVAL_S,
    _scale,
)
from cursed_controls.xbox import Surface


class FakeInputDevice:
    def __init__(self, fd: int, batches=None, error: Exception | None = None):
        self.fd = fd
        self._batches = list(batches or [])
        self._error = error
        self.closed = False

    def read(self):
        if self._error is not None:
            raise self._error
        if self._batches:
            return self._batches.pop(0)
        raise BlockingIOError()

    def close(self):
        self.closed = True


class FakeSelector:
    def __init__(self):
        self.registered = {}
        self.ready = []

    def register(self, fd, events, data):
        self.registered[fd] = data

    def unregister(self, fd):
        self.registered.pop(fd, None)

    def select(self, timeout=None):
        ready = self.ready
        self.ready = []
        return [(SimpleNamespace(data=item), 1) for item in ready]


def make_config(*, mappings=None, match=None):
    return AppConfig(
        runtime=RuntimeConfig(),
        devices=[
            DeviceProfile(
                id="test",
                match=match or DeviceMatch(name="test-controller"),
                mappings=mappings
                or [
                    MappingRule(
                        source_type=ecodes.EV_KEY,
                        source_code=ecodes.BTN_A,
                        target=Surface.A,
                        transform=Transform(kind=TransformKind.BUTTON),
                    )
                ],
            )
        ],
    )


def make_discovered(path: str, *, name="test-controller", uniq="", phys=""):
    return DiscoveredDevice(
        path=path,
        name=name,
        uniq=uniq,
        phys=phys,
        parent_uhid="parent-1",
        is_composite=True,
        is_composite_parent=False,
    )


def test_scale_basic():
    result = _scale(50, 0, 100, 0, 255)
    assert result == 127 or result == 128


def test_scale_negative():
    result = _scale(0, -32768, 32767, 0, 255)
    assert 100 < result < 150


def test_binding_planner_binds_unique_match():
    config = make_config()
    planner = BindingPlanner(config.devices)

    planned = planner.plan([make_discovered("/dev/input/event1")])

    assert len(planned) == 1
    assert planned[0].info.path == "/dev/input/event1"


def test_binding_planner_rejects_missing_match():
    config = make_config(match=DeviceMatch(name="missing"))
    planner = BindingPlanner(config.devices)

    with pytest.raises(BindingError) as exc:
        planner.plan([make_discovered("/dev/input/event1")])

    assert "no matching device" in str(exc.value)
    assert "test" in str(exc.value)


def test_binding_planner_rejects_ambiguous_match_with_diagnostics():
    config = make_config()
    planner = BindingPlanner(config.devices)

    with pytest.raises(BindingError) as exc:
        planner.plan(
            [
                make_discovered("/dev/input/event1", uniq="alpha"),
                make_discovered("/dev/input/event2", uniq="beta"),
            ]
        )

    message = str(exc.value)
    assert "multiple matching devices" in message
    assert "/dev/input/event1" in message
    assert "parent_uhid='parent-1'" in message


def test_binding_planner_rejects_duplicate_claims():
    shared = make_discovered("/dev/input/event1")
    profiles = [
        DeviceProfile(id="one", match=DeviceMatch(name="test-controller"), mappings=[]),
        DeviceProfile(
            id="two", match=DeviceMatch(name="test-controller", uniq=""), mappings=[]
        ),
    ]
    planner = BindingPlanner(profiles)

    with pytest.raises(BindingError) as exc:
        planner.plan([shared])

    assert "already claimed by profile one" in str(exc.value)


def test_mapper_button_to_button():
    config = make_config()
    mapper = Mapper(config)
    rule = config.devices[0].mappings[0]

    event = evdev.InputEvent(
        sec=0, usec=0, type=ecodes.EV_KEY, code=ecodes.BTN_A, value=1
    )
    assert mapper.apply(rule, event) is True
    assert mapper.state.a is True

    event = evdev.InputEvent(
        sec=0, usec=0, type=ecodes.EV_KEY, code=ecodes.BTN_A, value=0
    )
    assert mapper.apply(rule, event) is True
    assert mapper.state.a is False


def test_mapper_button_to_axis():
    config = make_config(
        mappings=[
            MappingRule(
                source_type=ecodes.EV_KEY,
                source_code=ecodes.BTN_B,
                target=Surface.LEFT_TRIGGER,
                transform=Transform(
                    kind=TransformKind.BUTTON, on_value=255, off_value=0
                ),
            )
        ]
    )
    mapper = Mapper(config)
    rule = config.devices[0].mappings[0]

    event = evdev.InputEvent(
        sec=0, usec=0, type=ecodes.EV_KEY, code=ecodes.BTN_B, value=1
    )
    mapper.apply(rule, event)
    assert mapper.state.left_trigger == 255

    event = evdev.InputEvent(
        sec=0, usec=0, type=ecodes.EV_KEY, code=ecodes.BTN_B, value=0
    )
    mapper.apply(rule, event)
    assert mapper.state.left_trigger == 0


def test_mapper_axis_scaling():
    config = make_config(
        mappings=[
            MappingRule(
                source_type=ecodes.EV_ABS,
                source_code=ecodes.ABS_X,
                target=Surface.LEFT_JOYSTICK_X,
                transform=Transform(
                    kind=TransformKind.AXIS,
                    source_min=-32768,
                    source_max=32767,
                    target_min=-32767,
                    target_max=32767,
                ),
            )
        ]
    )
    mapper = Mapper(config)
    rule = config.devices[0].mappings[0]

    event = evdev.InputEvent(
        sec=0, usec=0, type=ecodes.EV_ABS, code=ecodes.ABS_X, value=0
    )
    mapper.apply(rule, event)
    assert abs(mapper.state.left_joystick_x) < 100


def test_mapper_with_deadzone():
    config = make_config(
        mappings=[
            MappingRule(
                source_type=ecodes.EV_ABS,
                source_code=ecodes.ABS_X,
                target=Surface.LEFT_JOYSTICK_X,
                transform=Transform(
                    kind=TransformKind.AXIS,
                    deadzone=0.2,
                    source_min=-32768,
                    source_max=32767,
                    target_min=-32767,
                    target_max=32767,
                ),
            )
        ]
    )
    mapper = Mapper(config)
    rule = config.devices[0].mappings[0]

    event = evdev.InputEvent(
        sec=0, usec=0, type=ecodes.EV_ABS, code=ecodes.ABS_X, value=1000
    )
    mapper.apply(rule, event)
    assert mapper.state.left_joystick_x == 0


def test_mapper_hat_direction_and_release():
    config = make_config(
        mappings=[
            MappingRule(
                source_type=ecodes.EV_ABS,
                source_code=ecodes.ABS_HAT0X,
                target=Surface.DPAD_LEFT,
                transform=Transform(kind=TransformKind.HAT),
            ),
            MappingRule(
                source_type=ecodes.EV_ABS,
                source_code=ecodes.ABS_HAT0X,
                target=Surface.DPAD_RIGHT,
                transform=Transform(kind=TransformKind.HAT),
            ),
        ]
    )
    mapper = Mapper(config)
    profile = config.devices[0]

    left = evdev.InputEvent(
        sec=0, usec=0, type=ecodes.EV_ABS, code=ecodes.ABS_HAT0X, value=-1
    )
    assert mapper.process_event(profile, left) is True
    assert mapper.state.dpad_left is True
    assert mapper.state.dpad_right is False

    neutral = evdev.InputEvent(
        sec=0, usec=0, type=ecodes.EV_ABS, code=ecodes.ABS_HAT0X, value=0
    )
    assert mapper.process_event(profile, neutral) is True
    assert mapper.state.dpad_left is False
    assert mapper.state.dpad_right is False

    right = evdev.InputEvent(
        sec=0, usec=0, type=ecodes.EV_ABS, code=ecodes.ABS_HAT0X, value=1
    )
    assert mapper.process_event(profile, right) is True
    assert mapper.state.dpad_left is False
    assert mapper.state.dpad_right is True


def test_runtime_drain_ready_processes_full_batch_once():
    config = make_config()
    sink = FakeSink()
    runtime = Runtime(config, sink)
    runtime.selector = FakeSelector()

    events = [
        evdev.InputEvent(sec=0, usec=0, type=ecodes.EV_KEY, code=ecodes.BTN_A, value=1),
        evdev.InputEvent(sec=0, usec=0, type=ecodes.EV_SYN, code=0, value=0),
        evdev.InputEvent(sec=0, usec=0, type=ecodes.EV_KEY, code=ecodes.BTN_A, value=0),
    ]
    bound = BoundDevice(
        profile=config.devices[0],
        info=make_discovered("/dev/input/event1"),
        device=FakeInputDevice(fd=11, batches=[events]),
    )

    runtime.register_bound_devices([bound])
    runtime.selector.ready = [bound]
    changed = runtime.drain_ready(0)

    assert changed is True
    assert runtime.mapper.state.a is False

    sink.open()
    if changed:
        runtime.sink.send(runtime.mapper.state)
    assert len(sink.packets) == 1


def test_runtime_disconnect_unregisters_device():
    config = make_config()
    runtime = Runtime(config, FakeSink())
    runtime.selector = FakeSelector()

    bound = BoundDevice(
        profile=config.devices[0],
        info=make_discovered("/dev/input/event1"),
        device=FakeInputDevice(fd=12, error=OSError("gone")),
    )

    runtime.register_bound_devices([bound])
    runtime.selector.ready = [bound]

    assert runtime.drain_ready(0) is False
    assert 12 not in runtime.bound_by_fd
    assert bound.device.closed is True


def test_runtime_disconnect_requeues_profile():
    config = make_config()
    runtime = Runtime(config, FakeSink())
    runtime.selector = FakeSelector()

    bound = BoundDevice(
        profile=config.devices[0],
        info=make_discovered("/dev/input/event1"),
        device=FakeInputDevice(fd=12, error=OSError("gone")),
    )

    runtime.register_bound_devices([bound])
    runtime.selector.ready = [bound]
    runtime.drain_ready(0)

    assert config.devices[0] in runtime.pending_profiles


def test_try_bind_pending_binds_when_device_appears():
    from unittest.mock import patch

    config = make_config()
    runtime = Runtime(config, FakeSink())
    runtime.selector = FakeSelector()
    runtime.pending_profiles = list(config.devices)

    discovered = make_discovered("/dev/input/event5")

    fake_dev = FakeInputDevice(fd=20)

    with (
        patch("cursed_controls.runtime.list_devices", return_value=[discovered]),
        patch("cursed_controls.runtime.evdev.InputDevice", return_value=fake_dev),
        patch("cursed_controls.runtime.ForceFeedback") as mock_ff,
    ):
        mock_ff.return_value.supported = False
        runtime._try_bind_pending()

    assert runtime.pending_profiles == []
    assert 20 in runtime.bound_by_fd


def test_try_bind_pending_leaves_unmatched_profiles():
    from unittest.mock import patch

    config = make_config()
    runtime = Runtime(config, FakeSink())
    runtime.selector = FakeSelector()
    runtime.pending_profiles = list(config.devices)

    # Return a device that doesn't match "test-controller"
    non_matching = make_discovered("/dev/input/event5", name="some-other-device")

    with patch("cursed_controls.runtime.list_devices", return_value=[non_matching]):
        runtime._try_bind_pending()

    assert len(runtime.pending_profiles) == 1


def test_pre_connect_skips_evdev_profiles():
    """_pre_connect should not call any BT functions for evdev-type profiles."""
    from unittest.mock import patch

    config = make_config()
    runtime = Runtime(config, FakeSink())

    with (
        patch("cursed_controls.runtime.scan_for_wiimote") as mock_scan,
        patch("cursed_controls.runtime.connect_device") as mock_connect,
        patch("cursed_controls.runtime.wait_for_evdev") as mock_wait,
    ):
        runtime._pre_connect()

    mock_scan.assert_not_called()
    mock_connect.assert_not_called()
    mock_wait.assert_not_called()


def test_pre_connect_wiimote_profile_scans_and_connects():
    # _pre_connect scans for the Wiimote MAC; if the device isn't already
    # BT-connected it defers to the reconnect loop rather than blocking.
    from unittest.mock import patch

    profile = DeviceProfile(
        id="wiimote",
        match=DeviceMatch(name="Nintendo Wii Remote"),
        connection=ConnectionConfig(type=ConnectionType.WIIMOTE, timeout_s=10.0),
    )
    config = AppConfig(runtime=RuntimeConfig(), devices=[profile])
    runtime = Runtime(config, FakeSink())

    with (
        patch(
            "cursed_controls.runtime.scan_for_wiimote",
            return_value="AA:BB:CC:DD:EE:FF",
        ) as mock_scan,
        patch("cursed_controls.runtime.is_device_connected", return_value=False),
        patch("cursed_controls.runtime.connect_wiimote") as mock_connect,
        patch("cursed_controls.runtime.wait_for_evdev") as mock_wait,
    ):
        runtime._pre_connect()

    mock_scan.assert_called_once_with(10.0, None)
    # Not yet BT-connected → deferred to reconnect loop, no connect/wait calls
    mock_connect.assert_not_called()
    mock_wait.assert_not_called()


def test_pre_connect_persists_mac_for_wiimote():
    """After a successful Wiimote connect, the MAC is stored for later reconnect."""
    from unittest.mock import patch

    profile = DeviceProfile(
        id="wiimote",
        match=DeviceMatch(name="Nintendo Wii Remote"),
        connection=ConnectionConfig(type=ConnectionType.WIIMOTE, timeout_s=10.0),
    )
    config = AppConfig(runtime=RuntimeConfig(), devices=[profile])
    runtime = Runtime(config, FakeSink())

    with (
        patch(
            "cursed_controls.runtime.scan_for_wiimote",
            return_value="AA:BB:CC:DD:EE:FF",
        ),
        patch("cursed_controls.runtime.connect_wiimote"),
        patch("cursed_controls.runtime.wait_for_evdev"),
        patch("cursed_controls.runtime.list_devices", return_value=[]),
    ):
        runtime._pre_connect()

    assert runtime._connected_macs.get("wiimote") == "AA:BB:CC:DD:EE:FF"


def test_pre_connect_persists_mac_for_bluetooth():
    """After a BLUETOOTH connect, the configured MAC is stored."""
    from unittest.mock import patch

    profile = DeviceProfile(
        id="pad",
        match=DeviceMatch(name="GamePad"),
        connection=ConnectionConfig(
            type=ConnectionType.BLUETOOTH, mac="11:22:33:44:55:66", timeout_s=10.0
        ),
    )
    config = AppConfig(runtime=RuntimeConfig(), devices=[profile])
    runtime = Runtime(config, FakeSink())

    with (
        patch("cursed_controls.runtime.connect_device"),
        patch("cursed_controls.runtime.wait_for_evdev"),
        patch("cursed_controls.runtime.list_devices", return_value=[]),
    ):
        runtime._pre_connect()

    assert runtime._connected_macs.get("pad") == "11:22:33:44:55:66"


def test_try_reconnect_bt_skips_when_no_mac():
    """No reconnect attempt if no MAC is known."""
    from unittest.mock import patch

    profile = DeviceProfile(
        id="wiimote",
        match=DeviceMatch(name="Nintendo Wii Remote"),
        connection=ConnectionConfig(type=ConnectionType.WIIMOTE),
    )
    config = AppConfig(runtime=RuntimeConfig(), devices=[profile])
    runtime = Runtime(config, FakeSink())

    with patch("cursed_controls.runtime.reconnect_bluetooth") as mock_reconnect:
        runtime._try_reconnect_bt(profile)

    mock_reconnect.assert_not_called()


def test_try_reconnect_bt_skips_when_throttled():
    """No reconnect attempt if the throttle interval hasn't elapsed."""
    from unittest.mock import patch
    import time

    profile = DeviceProfile(
        id="wiimote",
        match=DeviceMatch(name="Nintendo Wii Remote"),
        connection=ConnectionConfig(type=ConnectionType.WIIMOTE),
    )
    config = AppConfig(runtime=RuntimeConfig(), devices=[profile])
    runtime = Runtime(config, FakeSink())
    runtime._connected_macs["wiimote"] = "AA:BB:CC:DD:EE:FF"
    # Pretend we just tried
    runtime._last_reconnect["wiimote"] = time.monotonic()

    with patch("cursed_controls.runtime.reconnect_bluetooth") as mock_reconnect:
        runtime._try_reconnect_bt(profile)

    mock_reconnect.assert_not_called()


def test_try_reconnect_bt_skips_when_already_connected():
    """No reconnect if bluetoothctl already reports the device as connected."""
    from unittest.mock import patch

    profile = DeviceProfile(
        id="wiimote",
        match=DeviceMatch(name="Nintendo Wii Remote"),
        connection=ConnectionConfig(type=ConnectionType.WIIMOTE),
    )
    config = AppConfig(runtime=RuntimeConfig(), devices=[profile])
    runtime = Runtime(config, FakeSink())
    runtime._connected_macs["wiimote"] = "AA:BB:CC:DD:EE:FF"

    with (
        patch("cursed_controls.runtime.is_device_connected", return_value=True),
        patch("cursed_controls.runtime.reconnect_bluetooth") as mock_reconnect,
    ):
        runtime._try_reconnect_bt(profile)

    mock_reconnect.assert_not_called()


def test_try_reconnect_bt_calls_reconnect_and_waits_for_evdev():
    """When disconnected, calls reconnect_bluetooth then waits for evdev node."""
    from unittest.mock import patch

    profile = DeviceProfile(
        id="wiimote",
        match=DeviceMatch(name="Nintendo Wii Remote"),
        connection=ConnectionConfig(type=ConnectionType.WIIMOTE),
    )
    config = AppConfig(runtime=RuntimeConfig(), devices=[profile])
    runtime = Runtime(config, FakeSink())
    runtime._connected_macs["wiimote"] = "AA:BB:CC:DD:EE:FF"

    with (
        patch("cursed_controls.runtime.is_device_connected", return_value=False),
        patch(
            "cursed_controls.runtime.reconnect_bluetooth", return_value=True
        ) as mock_reconnect,
        patch("cursed_controls.runtime.wait_for_evdev") as mock_wait,
    ):
        runtime._try_reconnect_bt(profile)
        # reconnect runs in a daemon thread — wait for it to finish
        deadline = time.monotonic() + 2.0
        while profile.id in runtime._reconnecting and time.monotonic() < deadline:
            time.sleep(0.01)

    mock_reconnect.assert_called_once_with(
        "AA:BB:CC:DD:EE:FF", True, timeout=5.0, max_retries=3, backoff=1.0
    )
    mock_wait.assert_called_once_with("Nintendo Wii Remote", timeout=10.0)


def test_rescan_calls_reconnect_for_bt_profiles():
    """_rescan_thread_body triggers _try_reconnect_bt for BT/Wiimote pending profiles."""
    from unittest.mock import patch

    profile = DeviceProfile(
        id="wiimote",
        match=DeviceMatch(name="Nintendo Wii Remote"),
        connection=ConnectionConfig(type=ConnectionType.WIIMOTE),
    )
    config = AppConfig(runtime=RuntimeConfig(rescan_interval_ms=0), devices=[profile])
    runtime = Runtime(config, FakeSink())
    runtime.pending_profiles = [profile]
    runtime._connected_macs["wiimote"] = "AA:BB:CC:DD:EE:FF"

    reconnect_calls = []

    def fake_reconnect(p):
        reconnect_calls.append(p)
        runtime._stop_event.set()  # stop after first reconnect call

    with (
        patch.object(runtime, "_try_reconnect_bt", side_effect=fake_reconnect),
        patch("cursed_controls.runtime.list_devices", return_value=[]),
    ):
        runtime._rescan_thread_body()

    assert reconnect_calls == [profile]


import threading, time


def test_runtime_stop_exits_run_loop():
    from cursed_controls.config import AppConfig, RuntimeConfig
    from cursed_controls.output import FakeSink
    from cursed_controls.runtime import Runtime

    config = AppConfig(runtime=RuntimeConfig(rescan_interval_ms=100), devices=[])
    sink = FakeSink()
    rt = Runtime(config, sink)
    thread = threading.Thread(target=rt.run, daemon=True)
    thread.start()
    time.sleep(0.05)
    rt.stop()
    thread.join(timeout=2.0)
    assert not thread.is_alive(), "Runtime did not stop within timeout"


def test_runtime_on_event_fires():
    from cursed_controls.config import AppConfig, RuntimeConfig
    from cursed_controls.output import FakeSink
    from cursed_controls.runtime import Runtime

    events = []
    config = AppConfig(runtime=RuntimeConfig(rescan_interval_ms=100), devices=[])
    rt = Runtime(config, FakeSink(), on_event=events.append)
    rt._fire_event({"type": "test"})
    assert events == [{"type": "test"}]


def test_runtime_on_event_called_on_bind():
    """Verify _try_bind_pending fires device_bound via the on_event callback."""
    from cursed_controls.config import (
        AppConfig,
        ConnectionConfig,
        DeviceMatch,
        DeviceProfile,
        RuntimeConfig,
    )
    from cursed_controls.discovery import DiscoveredDevice
    from cursed_controls.output import FakeSink
    from cursed_controls.runtime import Runtime

    events = []
    config = AppConfig(
        runtime=RuntimeConfig(rescan_interval_ms=100),
        devices=[
            DeviceProfile(id="pad", match=DeviceMatch(name="TestPad")),
        ],
    )
    rt = Runtime(config, FakeSink(), on_event=events.append)

    discovered = [
        DiscoveredDevice(
            path="/dev/input/event0",
            name="TestPad",
            uniq="",
            phys="",
            parent_uhid=None,
            is_composite=False,
            is_composite_parent=True,
        )
    ]

    # Patch open_bindings to avoid actually opening /dev/input/event0
    from unittest.mock import patch, MagicMock

    fake_bound = MagicMock()
    fake_bound.fd = 99
    fake_bound.profile = config.devices[0]
    fake_bound.info = discovered[0]

    with (
        patch.object(rt, "open_bindings", return_value=[fake_bound]),
        patch.object(rt, "register_bound_devices"),
    ):
        rt.pending_profiles = list(config.devices)
        rt._try_bind_pending.__func__  # confirm it's there
        # Patch list_devices to return our discovered device
        with patch("cursed_controls.runtime.list_devices", return_value=discovered):
            rt._try_bind_pending()

    assert any(
        e.get("type") == "device_bound" and e.get("profile_id") == "pad" for e in events
    ), f"Expected device_bound event, got: {events}"
