"""Tests for SmartDefaults and helper logic — no hardware required."""

import pytest
from evdev import ecodes

from cursed_controls.mapper_tui import (
    CandidateEvent,
    SmartDefaults,
    _code_name,
    _describe_candidate,
    _pick_surface,
    _type_name,
)
from cursed_controls.xbox import Surface


def _abs_info(min_val, max_val, flat=4, fuzz=2):
    """Create a minimal evdev.AbsInfo-like object."""

    class FakeAbsInfo:
        def __init__(self, mn, mx, fl, fz):
            self.min = mn
            self.max = mx
            self.flat = fl
            self.fuzz = fz

    return FakeAbsInfo(min_val, max_val, flat, fuzz)


def btn(code, value=1):
    return CandidateEvent(ecodes.EV_KEY, code, value, 1.0, None)


def axis(code, value, min_val=-120, max_val=120, flat=4):
    return CandidateEvent(
        ecodes.EV_ABS, code, value, 0.8, _abs_info(min_val, max_val, flat)
    )


def hat(code, value=1):
    # hat axes have span ≤ 3
    return CandidateEvent(ecodes.EV_ABS, code, value, 0.9, _abs_info(-1, 1, 0))


# ---------------------------------------------------------------------------
# button → button
# ---------------------------------------------------------------------------


def test_button_to_button():
    m = SmartDefaults.infer(btn(ecodes.BTN_A), Surface.A)
    assert m["kind"] == "button"
    assert m["source_type"] == ecodes.EV_KEY
    assert m["source_code"] == ecodes.BTN_A
    assert m["target"] == "A"
    assert "on_value" not in m


# ---------------------------------------------------------------------------
# button → axis
# ---------------------------------------------------------------------------


def test_button_to_trigger():
    m = SmartDefaults.infer(btn(ecodes.BTN_Z), Surface.LEFT_TRIGGER)
    assert m["kind"] == "button"
    assert m["on_value"] == 255
    assert m["off_value"] == 0


def test_button_to_joystick():
    m = SmartDefaults.infer(btn(ecodes.BTN_Z), Surface.LEFT_JOYSTICK_X)
    assert m["kind"] == "button"
    assert m["on_value"] == 32767
    assert m["off_value"] == 0


# ---------------------------------------------------------------------------
# hat → dpad
# ---------------------------------------------------------------------------


def test_hat_to_dpad():
    m = SmartDefaults.infer(hat(ecodes.ABS_HAT0X), Surface.DPAD_LEFT)
    assert m["kind"] == "hat"
    assert "source_min" not in m


def test_hat_to_button_non_dpad():
    m = SmartDefaults.infer(hat(ecodes.ABS_HAT0X), Surface.A)
    assert m["kind"] == "button"
    assert m["threshold"] == 1


# ---------------------------------------------------------------------------
# axis → trigger
# ---------------------------------------------------------------------------


def test_axis_to_trigger():
    m = SmartDefaults.infer(
        axis(ecodes.ABS_BRAKE, 800, min_val=0, max_val=1023, flat=63),
        Surface.LEFT_TRIGGER,
    )
    assert m["kind"] == "axis"
    assert m["source_min"] == 0
    assert m["source_max"] == 1023
    assert m["target_min"] == 0
    assert m["target_max"] == 255
    assert m["deadzone"] == pytest.approx(63 / 1023, abs=0.001)


# ---------------------------------------------------------------------------
# axis → joystick
# ---------------------------------------------------------------------------


def test_axis_to_joystick():
    m = SmartDefaults.infer(
        axis(ecodes.ABS_X, 60, min_val=-120, max_val=120, flat=4),
        Surface.LEFT_JOYSTICK_X,
    )
    assert m["kind"] == "axis"
    assert m["source_min"] == -120
    assert m["source_max"] == 120
    assert m["target_min"] == -32767
    assert m["target_max"] == 32767
    assert m["deadzone"] == pytest.approx(4 / 240, abs=0.001)


# ---------------------------------------------------------------------------
# axis → button (threshold inferred)
# ---------------------------------------------------------------------------


def test_axis_to_button_positive_range():
    m = SmartDefaults.infer(axis(ecodes.ABS_X, 800, min_val=0, max_val=1023), Surface.A)
    assert m["kind"] == "button"
    assert m["threshold"] == 511  # 1023 // 2


def test_axis_to_button_signed_range():
    m = SmartDefaults.infer(
        axis(ecodes.ABS_X, 100, min_val=-120, max_val=120), Surface.B
    )
    assert m["kind"] == "button"
    assert m["threshold"] == 1  # min < 0 → fallback threshold


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_code_name_known():
    assert "BTN_A" in _code_name(ecodes.EV_KEY, ecodes.BTN_A)


def test_code_name_unknown():
    result = _code_name(ecodes.EV_KEY, 9999)
    assert "9999" in result


def test_type_name():
    assert _type_name(ecodes.EV_KEY) == "EV_KEY"
    assert _type_name(ecodes.EV_ABS) == "EV_ABS"
    assert "99" in _type_name(99)


def test_describe_candidate_button():
    c = btn(ecodes.BTN_A)
    desc = _describe_candidate(c)
    assert "EV_KEY" in desc
    assert "button" in desc


def test_describe_candidate_axis():
    c = axis(ecodes.ABS_X, 60)
    desc = _describe_candidate(c)
    assert "EV_ABS" in desc
