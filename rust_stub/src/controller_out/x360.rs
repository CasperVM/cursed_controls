use crate::{
    controller_abs::{
        Axis, BitPackedButton, BitPackedButtons, Gamepad, GamepadAxis, GamepadButton, JoystickState,
    },
    AxisNew, JoystickStateNew,
};
use std::{u8, vec};

pub struct XboxButtonState {
    pub a: BitPackedButton,
    pub b: BitPackedButton,
    pub x: BitPackedButton,
    pub y: BitPackedButton,
    pub lb: BitPackedButton,
    pub rb: BitPackedButton,
    pub l3: BitPackedButton,
    pub r3: BitPackedButton,
    pub start: BitPackedButton,
    pub options: BitPackedButton,
    pub dpad_up: BitPackedButton,
    pub dpad_down: BitPackedButton,
    pub dpad_left: BitPackedButton,
    pub dpad_right: BitPackedButton,
    pub xbox: BitPackedButton,
}

impl XboxButtonState {
    pub fn new() -> XboxButtonState {
        XboxButtonState {
            a: BitPackedButton::new("A".to_string(), 0x04),
            b: BitPackedButton::new("B".to_string(), 0x05),
            x: BitPackedButton::new("X".to_string(), 0x06),
            y: BitPackedButton::new("Y".to_string(), 0x07),
            lb: BitPackedButton::new("LB".to_string(), 0x00),
            rb: BitPackedButton::new("RB".to_string(), 0x01),
            // Joystick buttons
            l3: BitPackedButton::new("L3".to_string(), 0x06),
            r3: BitPackedButton::new("R3".to_string(), 0x07),

            start: BitPackedButton::new("START".to_string(), 0x04),
            options: BitPackedButton::new("OPTIONS".to_string(), 0x05),
            xbox: BitPackedButton::new("XBOX".to_string(), 0x02),

            // Dpad
            dpad_up: BitPackedButton::new("DPAD_UP".to_string(), 0x00),
            dpad_down: BitPackedButton::new("DPAD_DOWN".to_string(), 0x01),
            dpad_left: BitPackedButton::new("DPAD_LEFT".to_string(), 0x02),
            dpad_right: BitPackedButton::new("DPAD_RIGHT".to_string(), 0x03),
        }
    }

    pub fn get_control_byte_2(&self) -> u8 {
        BitPackedButtons {
            buttons: vec![
                self.dpad_up.clone(),
                self.dpad_down.clone(),
                self.dpad_left.clone(),
                self.dpad_right.clone(),
                self.start.clone(),
                self.options.clone(),
                self.l3.clone(),
                self.r3.clone(),
            ],
        }
        .to_bytes_repr()
    }

    pub fn get_control_byte_3(&self) -> u8 {
        BitPackedButtons {
            buttons: vec![
                self.lb.clone(),
                self.rb.clone(),
                self.xbox.clone(),
                self.a.clone(),
                self.b.clone(),
                self.x.clone(),
                self.y.clone(),
            ],
        }
        .to_bytes_repr()
    }
}

pub struct XboxControllerState {
    pub buttons: XboxButtonState,
    pub left_trigger: Axis,
    pub right_trigger: Axis,
    pub left_joystick: JoystickState,  // byte 6 - 9
    pub right_joystick: JoystickState, // byte 10 - 13
}

impl XboxControllerState {
    pub fn new() -> XboxControllerState {
        XboxControllerState {
            buttons: XboxButtonState::new(),
            left_trigger: AxisNew!(u8::MIN),
            right_trigger: AxisNew!(u8::MIN),
            left_joystick: JoystickStateNew!(i16, 0),
            right_joystick: JoystickStateNew!(i16, 0),
        }
    }

    pub fn update_from_gamepad(&mut self, gamepad: &Gamepad) {
        for (button, button_state) in &gamepad.buttons {
            let val = button_state.to_owned();
            match button {
                GamepadButton::North => self.buttons.y.value = val,
                GamepadButton::East => self.buttons.b.value = val,
                GamepadButton::South => self.buttons.a.value = val,
                GamepadButton::West => self.buttons.x.value = val,
                GamepadButton::LeftShoulderButton => self.buttons.lb.value = val,
                GamepadButton::RightShoulderButton => self.buttons.rb.value = val,
                GamepadButton::LeftThumb => self.buttons.l3.value = val,
                GamepadButton::RightThumb => self.buttons.r3.value = val,
                GamepadButton::Start => self.buttons.start.value = val,
                GamepadButton::Select => self.buttons.options.value = val,
                GamepadButton::Mode => self.buttons.xbox.value = val,
                GamepadButton::DPadUp => self.buttons.dpad_up.value = val,
                GamepadButton::DPadDown => self.buttons.dpad_down.value = val,
                GamepadButton::DPadLeft => self.buttons.dpad_left.value = val,
                GamepadButton::DPadRight => self.buttons.dpad_right.value = val,
            }
        }
        for (gamepad_axis, axis) in &gamepad.axes {
            match gamepad_axis {
                GamepadAxis::LeftJoystickX => {
                    self.left_joystick.x.value = axis.convert_into(false);
                }
                GamepadAxis::LeftJoystickY => {
                    self.left_joystick.y.value = axis.convert_into(false);
                }
                GamepadAxis::RightJoystickX => {
                    self.right_joystick.x.value = axis.convert_into(false);
                }
                GamepadAxis::RightJoystickY => {
                    self.right_joystick.y.value = axis.convert_into(false);
                }
                GamepadAxis::LeftTrigger => {
                    self.left_trigger.value = axis.convert_into(false);
                }
                GamepadAxis::RightTrigger => {
                    self.right_trigger.value = axis.convert_into(false);
                }
            }
        }
    }

    pub fn to_packet(&self) -> [u8; 20] {
        let mut packet = [0u8; 20];
        packet[0] = 0x00; // Report ID (0x00)
        packet[1] = 0x14; // Length (0x14)
        packet[2] = self.buttons.get_control_byte_2();
        packet[3] = self.buttons.get_control_byte_3();
        packet[4] = self.left_trigger.convert_into(false);
        packet[5] = self.right_trigger.convert_into(false);
        packet[6..8].copy_from_slice(
            &self
                .left_joystick
                .x
                .convert_into::<i16, _>(false)
                .to_le_bytes(),
        );
        packet[8..10].copy_from_slice(
            &self
                .left_joystick
                .y
                .convert_into::<i16, _>(false)
                .to_le_bytes(),
        );
        packet[10..12].copy_from_slice(
            &self
                .right_joystick
                .x
                .convert_into::<i16, _>(false)
                .to_le_bytes(),
        );
        packet[12..14].copy_from_slice(
            &self
                .right_joystick
                .y
                .convert_into::<i16, _>(false)
                .to_le_bytes(),
        );
        packet
    }
}
