"""Tests for SimulateRuntime — no real hardware required."""

import pytest
from evdev import ecodes

from cursed_controls.config import (
    AppConfig,
    DeviceMatch,
    DeviceProfile,
    MappingRule,
    RuntimeConfig,
    Transform,
    TransformKind,
)
from cursed_controls.output import FakeSink
from cursed_controls.simulate import SimulateRuntime, _format_state, _resolve_code
from cursed_controls.xbox import Surface, XboxControllerState


def make_config():
    return AppConfig(
        runtime=RuntimeConfig(),
        devices=[
            DeviceProfile(
                id="wiimote",
                match=DeviceMatch(name="Nintendo Wii Remote"),
                mappings=[
                    MappingRule(
                        source_type=ecodes.EV_KEY,
                        source_code=ecodes.BTN_A,
                        target=Surface.A,
                        transform=Transform(kind=TransformKind.BUTTON),
                    ),
                    MappingRule(
                        source_type=ecodes.EV_ABS,
                        source_code=ecodes.ABS_HAT0X,
                        target=Surface.LEFT_JOYSTICK_X,
                        transform=Transform(
                            kind=TransformKind.AXIS,
                            source_min=-120,
                            source_max=120,
                            target_min=-32767,
                            target_max=32767,
                        ),
                    ),
                ],
            )
        ],
    )


def test_inject_button_press_and_release():
    sink = FakeSink()
    sim = SimulateRuntime(make_config(), sink)
    sink.open()

    changed = sim.inject("wiimote", ecodes.EV_KEY, ecodes.BTN_A, 1)
    assert changed is True
    assert sim.mapper.state.a is True
    assert len(sink.packets) == 1

    changed = sim.inject("wiimote", ecodes.EV_KEY, ecodes.BTN_A, 0)
    assert changed is True
    assert sim.mapper.state.a is False
    assert len(sink.packets) == 2


def test_inject_no_change_does_not_send():
    sink = FakeSink()
    sim = SimulateRuntime(make_config(), sink)
    sink.open()

    # inject event that matches no mapping
    changed = sim.inject("wiimote", ecodes.EV_KEY, ecodes.BTN_B, 1)
    assert changed is False
    assert len(sink.packets) == 0


def test_inject_axis():
    sink = FakeSink()
    sim = SimulateRuntime(make_config(), sink)
    sink.open()

    sim.inject("wiimote", ecodes.EV_ABS, ecodes.ABS_HAT0X, 60)
    assert sim.mapper.state.left_joystick_x > 0


def test_inject_unknown_profile_raises():
    sim = SimulateRuntime(make_config(), FakeSink())
    with pytest.raises(KeyError):
        sim.inject("nunchuk", ecodes.EV_KEY, ecodes.BTN_A, 1)


def test_resolve_code_by_name():
    assert _resolve_code("BTN_A") == ecodes.BTN_A
    assert _resolve_code("ABS_X") == ecodes.ABS_X


def test_resolve_code_by_integer():
    assert _resolve_code("304") == 304


def test_resolve_code_unknown_raises():
    with pytest.raises(ValueError):
        _resolve_code("NOT_A_CODE")


def test_format_state_no_input():
    state = XboxControllerState()
    result = _format_state(state)
    assert "buttons=-" in result


def test_format_state_with_button():
    state = XboxControllerState()
    state.a = True
    state.left_trigger = 200
    result = _format_state(state)
    assert "A" in result
    assert "LT=200" in result


def test_repl_quit():
    sim = SimulateRuntime(make_config(), FakeSink())
    assert sim._handle_line("quit") is False
    assert sim._handle_line("exit") is False
    assert sim._handle_line("q") is False


def test_repl_press_command():
    sink = FakeSink()
    sink.open()
    sim = SimulateRuntime(make_config(), sink)

    sim._handle_line("press wiimote BTN_A")
    assert sim.mapper.state.a is True

    sim._handle_line("release wiimote BTN_A")
    assert sim.mapper.state.a is False


def test_repl_axis_command():
    sink = FakeSink()
    sink.open()
    sim = SimulateRuntime(make_config(), sink)

    sim._handle_line("axis wiimote ABS_HAT0X 120")
    assert sim.mapper.state.left_joystick_x == 32767


def test_repl_unknown_command_is_tolerated():
    sim = SimulateRuntime(make_config(), FakeSink())
    assert sim._handle_line("florp") is True  # doesn't crash or quit
