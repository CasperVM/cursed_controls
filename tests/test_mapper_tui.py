"""Tests for SmartDefaults and helper logic — no hardware required."""

import pytest
import yaml
from evdev import ecodes

from cursed_controls.mapper_tui import (
    CandidateEvent,
    MapperTUI,
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


# ---------------------------------------------------------------------------
# calibration — SmartDefaults.infer with calibrated_range
# ---------------------------------------------------------------------------


def test_smart_defaults_uses_calibrated_range_joystick():
    c = axis(ecodes.ABS_X, 90, min_val=-120, max_val=120, flat=4)
    m = SmartDefaults.infer(c, Surface.LEFT_JOYSTICK_X, calibrated_range=(-100, 98))
    assert m["source_min"] == -100
    assert m["source_max"] == 98
    # deadzone still from absinfo.flat, not calibrated range
    assert m["deadzone"] == pytest.approx(4 / 240, abs=0.001)


def test_smart_defaults_uses_calibrated_range_trigger():
    c = axis(ecodes.ABS_BRAKE, 800, min_val=0, max_val=1023, flat=10)
    m = SmartDefaults.infer(c, Surface.LEFT_TRIGGER, calibrated_range=(5, 990))
    assert m["source_min"] == 5
    assert m["source_max"] == 990
    assert m["target_min"] == 0
    assert m["target_max"] == 255


def test_smart_defaults_falls_back_to_absinfo_when_no_calibration():
    c = axis(ecodes.ABS_X, 90, min_val=-120, max_val=120)
    m = SmartDefaults.infer(c, Surface.LEFT_JOYSTICK_X)
    assert m["source_min"] == -120
    assert m["source_max"] == 120


# ---------------------------------------------------------------------------
# MapperTUI — load existing config + merge
# ---------------------------------------------------------------------------


def test_mapper_tui_starts_fresh_when_no_file(tmp_path):
    tui = MapperTUI(str(tmp_path / "new.yaml"))
    assert tui._existing_devices == {}
    assert tui._existing_runtime == {"output_mode": "stdout"}


def test_mapper_tui_loads_existing_runtime(tmp_path):
    existing = tmp_path / "mapping.yaml"
    existing.write_text(yaml.dump({
        "runtime": {"output_mode": "gadget", "rumble": True, "interfaces": 1},
        "devices": [],
    }))
    tui = MapperTUI(str(existing))
    assert tui._existing_runtime["output_mode"] == "gadget"
    assert tui._existing_runtime["rumble"] is True


def test_mapper_tui_merge_preserves_existing_profiles(tmp_path):
    existing = tmp_path / "mapping.yaml"
    existing.write_text(yaml.dump({
        "runtime": {"output_mode": "gadget", "rumble": True},
        "devices": [
            {"id": "wiimote", "match": {"name": "Nintendo Wii Remote"}, "mappings": []},
        ],
    }))
    tui = MapperTUI(str(existing))
    tui.profiles = [{"id": "nunchuk", "match": {"name": "Nunchuk"}, "mappings": []}]
    tui._save()

    result = yaml.safe_load(existing.read_text())
    ids = [d["id"] for d in result["devices"]]
    assert "wiimote" in ids
    assert "nunchuk" in ids
    assert result["runtime"]["output_mode"] == "gadget"
    assert result["runtime"]["rumble"] is True


def test_mapper_tui_merge_replaces_existing_profile(tmp_path):
    existing = tmp_path / "mapping.yaml"
    existing.write_text(yaml.dump({
        "runtime": {"output_mode": "gadget"},
        "devices": [
            {"id": "wiimote", "match": {"name": "Old Name"}, "mappings": [{"a": 1}]},
        ],
    }))
    tui = MapperTUI(str(existing))
    tui.profiles = [{"id": "wiimote", "match": {"name": "New Name"}, "mappings": [{"a": 2}]}]
    tui._save()

    result = yaml.safe_load(existing.read_text())
    devices = {d["id"]: d for d in result["devices"]}
    assert len(devices) == 1
    assert devices["wiimote"]["match"]["name"] == "New Name"
    assert devices["wiimote"]["mappings"] == [{"a": 2}]


def test_mapper_tui_save_fresh_config(tmp_path):
    path = tmp_path / "new.yaml"
    tui = MapperTUI(str(path))
    tui.profiles = [{"id": "pad", "match": {"name": "Gamepad"}, "mappings": []}]
    tui._save()

    result = yaml.safe_load(path.read_text())
    assert result["devices"][0]["id"] == "pad"
    assert result["runtime"]["output_mode"] == "stdout"
