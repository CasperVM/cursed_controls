"""Tests for Xbox controller state and packet generation."""

import pytest
from cursed_controls.xbox import XboxControllerState, Surface


def test_xbox_state_initialization():
    """Test that a new controller state is all zeroes/false."""
    state = XboxControllerState()
    assert state.a is False
    assert state.b is False
    assert state.x is False
    assert state.y is False
    assert state.lb is False
    assert state.rb is False
    assert state.left_trigger == 0
    assert state.right_trigger == 0
    assert state.left_joystick_x == 0
    assert state.left_joystick_y == 0


def test_xbox_packet_structure():
    """Test that packet structure is correct (20 bytes, report ID, length)."""
    state = XboxControllerState()
    packet = state.to_packet()
    assert len(packet) == 20
    assert packet[0] == 0x00  # Report ID
    assert packet[1] == 0x14  # Length (20)


def test_xbox_set_button():
    """Test setting button states."""
    state = XboxControllerState()
    state.set_button(Surface.A, True)
    assert state.a is True
    state.set_button(Surface.A, False)
    assert state.a is False


def test_xbox_set_axis():
    """Test setting axis values with clamping."""
    state = XboxControllerState()

    # Test trigger clamping (0-255)
    state.set_axis(Surface.LEFT_TRIGGER, 500)
    assert state.left_trigger == 255
    state.set_axis(Surface.LEFT_TRIGGER, -10)
    assert state.left_trigger == 0

    # Test joystick clamping (-32767 to 32767)
    state.set_axis(Surface.LEFT_JOYSTICK_X, 50000)
    assert state.left_joystick_x == 32767
    state.set_axis(Surface.LEFT_JOYSTICK_X, -50000)
    assert state.left_joystick_x == -32767


def test_xbox_packet_with_buttons():
    """Test that button presses change packet output."""
    state1 = XboxControllerState()
    packet1 = state1.to_packet()

    state2 = XboxControllerState()
    state2.set_button(Surface.A, True)
    packet2 = state2.to_packet()

    assert packet1 != packet2, "Pressing A should change the packet"


def test_xbox_packet_with_triggers():
    """Test that triggers are encoded correctly."""
    state = XboxControllerState()
    state.set_axis(Surface.LEFT_TRIGGER, 128)
    state.set_axis(Surface.RIGHT_TRIGGER, 255)

    packet = state.to_packet()
    assert packet[4] == 128
    assert packet[5] == 255


def test_xbox_packet_with_joysticks():
    """Test that joystick values are little-endian signed 16-bit."""
    state = XboxControllerState()
    state.set_axis(Surface.LEFT_JOYSTICK_X, 256)
    state.set_axis(Surface.LEFT_JOYSTICK_Y, -256)

    packet = state.to_packet()
    # bytes 6-8: left_joystick_x (little-endian i16)
    # bytes 8-10: left_joystick_y (little-endian i16)
    assert packet[6:8] == (256).to_bytes(2, "little", signed=True)
    assert packet[8:10] == (-256).to_bytes(2, "little", signed=True)
