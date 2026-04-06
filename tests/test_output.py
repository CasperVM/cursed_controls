"""Tests for output sinks."""

import pytest
from cursed_controls.xbox import XboxControllerState, Surface
from cursed_controls.output import FakeSink, StdoutSink


def test_fake_sink_basic():
    sink = FakeSink()
    sink.open()

    state = XboxControllerState()
    state.set_button(Surface.A, True)
    sink.send(state)
    assert len(sink.packets) == 1

    state.set_button(Surface.B, True)
    sink.send(state)
    assert len(sink.packets) == 2

    sink.close()


def test_fake_sink_closed_raises():
    sink = FakeSink()
    state = XboxControllerState()
    with pytest.raises(RuntimeError, match="not open"):
        sink.send(state)


def test_fake_sink_clear():
    sink = FakeSink()
    sink.open()
    state = XboxControllerState()
    sink.send(state)
    sink.send(state)
    assert len(sink.packets) == 2
    sink.clear()
    assert len(sink.packets) == 0


def test_fake_sink_poll_rumble():
    sink = FakeSink()
    sink.open()
    assert sink.poll_rumble(0) is None
    sink.queue_rumble(0, 128, 200)
    result = sink.poll_rumble(0)
    assert result == (128, 200)
    assert sink.poll_rumble(0) is None  # consumed


def test_fake_sink_poll_led():
    sink = FakeSink()
    sink.open()
    assert sink.poll_led(0) is None
    sink.queue_led(0, 6)  # P1On
    assert sink.poll_led(0) == 6
    assert sink.poll_led(0) is None  # consumed


def test_fake_sink_rumble_and_led_independent():
    sink = FakeSink()
    sink.open()
    sink.queue_rumble(0, 255, 100)
    sink.queue_led(0, 2)
    assert sink.poll_rumble(0) == (255, 100)
    assert sink.poll_led(0) == 2


def test_fake_sink_slot_isolation():
    sink = FakeSink()
    sink.open()
    sink.queue_rumble(1, 50, 60)
    assert sink.poll_rumble(0) is None
    assert sink.poll_rumble(1) == (50, 60)


def test_stdout_sink_no_error(capsys):
    sink = StdoutSink()
    sink.open()
    state = XboxControllerState()
    state.set_button(Surface.A, True)
    sink.send(state)
    sink.close()
    captured = capsys.readouterr()
    assert "slot" in captured.out


def test_base_sink_poll_returns_none():
    """StdoutSink inherits default poll methods that always return None."""
    sink = StdoutSink()
    assert sink.poll_rumble(0) is None
    assert sink.poll_led(0) is None
