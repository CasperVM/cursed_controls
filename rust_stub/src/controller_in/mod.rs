use std::time::Duration;

use futures::TryStreamExt;
use futures_util::StreamExt;
use num_traits::ToPrimitive;
use xwiimote::{
    events::{Event, KeyState},
    Address, Channels, Device, Monitor,
};

use crate::controller_abs::{
    Axis, ControllerInput, ControllerMapping, Gamepad, GamepadAxis, GamepadButton, OutputMapping,
};
use futures::executor::block_on;
use gilrs::{
    Axis as GilAxis, Button as GilButton, Event as GilEvent, Gamepad as GilGamepad,
    GamepadId as GilGamepadId, Gilrs,
};

use gilrs::ev::state::AxisData as GilAxisData;
use gilrs::ev::Code as GilCode;

// TODO: use actix?

struct XWiiEvent(Event);

impl XWiiEvent {
    // Constructor to wrap an Event into MyEvent
    fn new(event: xwiimote::events::Event) -> Self {
        XWiiEvent(event)
    }
}

impl PartialEq for XWiiEvent {
    fn eq(&self, other: &Self) -> bool {
        match (&self.0, &other.0) {
            (Event::Key(key1, _), Event::Key(key2, _)) => {
                std::mem::discriminant(key1) == std::mem::discriminant(key2)
            }
            (Event::NunchukKey(key1, _), Event::NunchukKey(key2, _)) => {
                std::mem::discriminant(key1) == std::mem::discriminant(key2)
            }
            (Event::NunchukMove { .. }, Event::NunchukMove { .. }) => true,
            // FIXME: Add others...
            _ => false,
        }
    }
}

pub struct XWiiInput {
    device: Device,
    gamepad: Gamepad,
    channels: Channels,
    mappings: Vec<ControllerMapping<Event>>,
    nunchuck_x_min: i32,
    nunchuck_x_max: i32,
    nunchuck_y_min: i32,
    nunchuck_y_max: i32,
    deadzone_percentage: f64,
}

impl XWiiInput {
    pub fn new(address: &Address) -> XWiiInput {
        XWiiInput {
            device: Device::connect(address).unwrap(),
            gamepad: Gamepad::new(),
            // TODO: Make this into a ::new arg.
            channels: Channels::CORE | Channels::NUNCHUK,
            mappings: vec![],
            nunchuck_x_min: 0,
            nunchuck_x_max: 0,
            nunchuck_y_min: 0,
            nunchuck_y_max: 0,
            deadzone_percentage: 0.05, // 5%
        }
    }

    pub fn map_event(&mut self, event: Event, to_mapping: OutputMapping) {
        self.mappings.push(ControllerMapping {
            input: event,
            output: to_mapping.clone(),
        });
    }

    fn map_event_to_gamepad(&mut self, event: Event) {
        macro_rules! button_to_gamepad {
            ($self:expr, $controller_mapping_output:expr, $key_state:expr) => {
                let button_down = !matches!($key_state, KeyState::Up);
                match ($controller_mapping_output) {
                    OutputMapping::Axis(gamepad_axis) => {
                        let output_axis = $self.gamepad.get_axis_ref(gamepad_axis.to_owned());
                        let output_value;
                        if button_down {
                            output_value = output_axis.get_max().clone();
                        } else {
                            output_value = output_axis.get_min().clone();
                        };
                        output_axis.value = output_value;
                    }
                    OutputMapping::Button(gamepad_button) => {
                        self.gamepad
                            .set_button(gamepad_button.to_owned(), button_down);
                    }
                }
            };
        }

        for controller_mapping in &self.mappings {
            if XWiiEvent::new(controller_mapping.input) != XWiiEvent::new(event) {
                continue;
            }
            // If we have found our input key, we still need to do some basic matching to ensure correct mapping.
            // E.g. button -> Axis is a little weird.
            match event {
                Event::Key(_key, key_state) => {
                    button_to_gamepad!(self, &controller_mapping.output, key_state);
                }
                Event::NunchukKey(_key, key_state) => {
                    button_to_gamepad!(self, &controller_mapping.output, key_state);
                }
                Event::NunchukMove {
                    x,
                    y,
                    x_acceleration: _,
                    y_acceleration: _,
                } => {
                    // println!("nunchuck X {}", x);
                    // println!("nunchuck Y {}", y);

                    if x < self.nunchuck_x_min {
                        self.nunchuck_x_min = x;
                    }
                    if x > self.nunchuck_x_max {
                        self.nunchuck_x_max = x;
                    }

                    if y < self.nunchuck_y_min {
                        self.nunchuck_y_min = y;
                    }
                    if y > self.nunchuck_y_max {
                        self.nunchuck_y_max = y;
                    }

                    let mut nunchuck_x = Axis::new(x, self.nunchuck_x_min, self.nunchuck_x_max);
                    // println!("nunchuck X {}", nunchuck_x.get_normalized_value());
                    let mut nunchuck_y = Axis::new(y, self.nunchuck_y_min, self.nunchuck_y_max);
                    // println!("nunchuck Y {}", nunchuck_y.get_normalized_value());

                    let deadzone_range_x = (self.deadzone_percentage
                        * (self.nunchuck_x_min - self.nunchuck_x_max)
                            .abs()
                            .to_f64()
                            .unwrap())
                    .to_i32()
                    .unwrap();
                    let deadzone_range_y = (self.deadzone_percentage
                        * (self.nunchuck_y_min - self.nunchuck_y_max)
                            .abs()
                            .to_f64()
                            .unwrap())
                    .to_i32()
                    .unwrap();

                    nunchuck_x.set_deadzones(nunchuck_x.make_deadzone(
                        vec![-deadzone_range_x..deadzone_range_x].to_owned(),
                        self.nunchuck_x_min,
                        self.nunchuck_x_max,
                    ));
                    nunchuck_y.set_deadzones(nunchuck_y.make_deadzone(
                        vec![-deadzone_range_y..deadzone_range_y].to_owned(),
                        self.nunchuck_y_min,
                        self.nunchuck_y_max,
                    ));

                    match &controller_mapping.output {
                        OutputMapping::Axis(gamepad_axis) => {
                            let output_axis = self.gamepad.get_axis_ref(gamepad_axis.to_owned());
                            match gamepad_axis {
                                GamepadAxis::LeftJoystickX | GamepadAxis::RightJoystickX => {
                                    output_axis.value = nunchuck_x.convert_into(true)
                                }
                                GamepadAxis::LeftJoystickY | GamepadAxis::RightJoystickY => {
                                    output_axis.value = nunchuck_y.convert_into(true)
                                }
                                _ => {
                                    // Triggers?... could maybe?
                                }
                            }
                        }
                        OutputMapping::Button(_gamepad_button) => {
                            // not sure yet...
                        }
                    }
                }

                _ => {}
            }
        }
    }
}

impl ControllerInput for XWiiInput {
    type ControllerType = XWiiInput;

    fn to_gamepad<'a>(&'a mut self) -> &'a Gamepad {
        return &self.gamepad;
    }

    fn discover_all() -> Vec<Self::ControllerType> {
        let monitor = Monitor::enumerate().unwrap();

        let addresses: Vec<_> = block_on(async { monitor.collect().await });

        let mut inps: Vec<Self::ControllerType> = vec![];
        for address in addresses {
            inps.push(Self::ControllerType::new(&address.unwrap()));
        }

        return inps;
    }

    fn prep_for_input_events(&mut self) {
        // TODO: better decice handling with disconnects etc.
        self.device
            .open(Channels::from_bits(self.channels.bits()).unwrap(), true)
            .unwrap();
        println!("XWiiInput connected: {}", self.device.kind().unwrap());
    }

    async fn get_next_inputs(&mut self) -> Result<bool, &'static str> {
        let maybe_event = {
            let event_stream = &mut self.device.events().unwrap();
            tokio::select! {
                res = event_stream.try_next() => match res {
                    Ok(event) => event,
                    Err(_) => return Err("Error reading events.")
                },
                // TODO: Make this a setting somehow?
                _ = tokio::time::sleep(Duration::from_millis(5)) => {
                    return Ok(false);
                },
            }
        };

        let (event, _time) = match maybe_event {
            Some(event) => event,
            None => {
                return Ok(false);
            }
        };

        self.map_event_to_gamepad(event);
        return Ok(true);
    }
}

pub struct GilRsInput {
    gamepad: Gamepad,
    gil_rs: Gilrs,
    gil_rs_device_id: GilGamepadId,
    deadzone_percentage: f64,
}

impl GilRsInput {
    pub fn new(gil_rs: Gilrs, gil_rs_device_id: GilGamepadId) -> GilRsInput {
        GilRsInput {
            gamepad: Gamepad::new(),
            gil_rs,
            gil_rs_device_id,
            deadzone_percentage: 0.05, // 5%
        }
    }

    fn get_gilrs_gamepad(&self) -> GilGamepad {
        self.gil_rs.gamepad(self.gil_rs_device_id)
    }

    fn map_gilrs_to_gamepad(&mut self) {
        let buttons = [
            GilButton::South,
            GilButton::East,
            GilButton::North,
            GilButton::West,
            // GilButton::C,
            // GilButton::Z,
            GilButton::LeftTrigger,
            // GilButton::LeftTrigger2,
            GilButton::RightTrigger,
            // GilButton::RightTrigger2,
            GilButton::Select,
            GilButton::Start,
            GilButton::Mode,
            GilButton::LeftThumb,
            GilButton::RightThumb,
            GilButton::DPadUp,
            GilButton::DPadDown,
            GilButton::DPadLeft,
            GilButton::DPadRight,
        ];
        // We also NEED to consume events here, otherwise data is not filled properly on the gamepad
        while let Some(GilEvent { id, event, time }) = self.gil_rs.next_event() {
            // FIXME: gamepad state seems inconsistent?/mappings might be weird...
            println!("{:?} New event from {}: {:?}", time, id, event);
        }

        for button in buttons.iter() {
            let gilrs_gamepad = self.get_gilrs_gamepad();

            let is_pressed = gilrs_gamepad.is_pressed(button.clone());

            // Button to button
            match button {
                GilButton::South => self.gamepad.set_button(GamepadButton::South, is_pressed),
                GilButton::East => self.gamepad.set_button(GamepadButton::East, is_pressed),
                GilButton::North => self.gamepad.set_button(GamepadButton::North, is_pressed),
                GilButton::West => self.gamepad.set_button(GamepadButton::West, is_pressed),
                GilButton::LeftTrigger => self
                    .gamepad
                    .set_button(GamepadButton::LeftShoulderButton, is_pressed),
                GilButton::RightTrigger => self
                    .gamepad
                    .set_button(GamepadButton::RightShoulderButton, is_pressed),
                GilButton::Select => self.gamepad.set_button(GamepadButton::Select, is_pressed),
                GilButton::Start => self.gamepad.set_button(GamepadButton::Start, is_pressed),
                GilButton::Mode => self.gamepad.set_button(GamepadButton::Mode, is_pressed),
                GilButton::LeftThumb => self
                    .gamepad
                    .set_button(GamepadButton::LeftThumb, is_pressed),
                GilButton::RightThumb => self
                    .gamepad
                    .set_button(GamepadButton::RightThumb, is_pressed),
                GilButton::DPadUp => self.gamepad.set_button(GamepadButton::DPadUp, is_pressed),
                GilButton::DPadDown => self.gamepad.set_button(GamepadButton::DPadDown, is_pressed),
                GilButton::DPadLeft => self.gamepad.set_button(GamepadButton::DPadLeft, is_pressed),
                GilButton::DPadRight => self
                    .gamepad
                    .set_button(GamepadButton::DPadRight, is_pressed),
                _ => (),
            };
        }
        // Axis to axis
        let axes = [
            GilAxis::LeftStickX,
            GilAxis::LeftStickY,
            GilAxis::RightStickX,
            GilAxis::RightStickY,
            GilAxis::RightZ,
            GilAxis::LeftZ,
        ];

        let mut current_state: Vec<(GilCode, GilAxisData)> = vec![];
        {
            for (code, axis) in self.get_gilrs_gamepad().state().axes() {
                current_state.push((code.clone(), axis.clone()));
            }
        }

        // Axis mapping is pretty weird...
        for (code, axis) in current_state {
            let in_axis = Axis::new(axis.value(), -1.0, 1.0);
            let mut known_axis = false;
            for ax in axes {
                if (self.get_gilrs_gamepad().axis_code(ax)) != Some(code) {
                    break;
                }

                match ax {
                    GilAxis::LeftStickX => {
                        known_axis = true;
                        self.gamepad.get_axis_ref(GamepadAxis::LeftJoystickX).value =
                            in_axis.convert_into(false);
                    }
                    GilAxis::LeftStickY => {
                        known_axis = true;
                        self.gamepad.get_axis_ref(GamepadAxis::LeftJoystickY).value =
                            in_axis.convert_into(false);
                    }
                    GilAxis::RightStickX => {
                        self.gamepad.get_axis_ref(GamepadAxis::RightJoystickX).value =
                            in_axis.convert_into(false);
                    }
                    GilAxis::RightStickY => {
                        self.gamepad.get_axis_ref(GamepadAxis::RightJoystickY).value =
                            in_axis.convert_into(false);
                    }
                    GilAxis::LeftZ => {
                        self.gamepad.get_axis_ref(GamepadAxis::RightJoystickX).value =
                            in_axis.convert_into(false);
                    }
                    GilAxis::RightZ => {
                        self.gamepad.get_axis_ref(GamepadAxis::RightJoystickY).value =
                            in_axis.invert().convert_into(false);
                    }

                    _ => {}
                }
            }
            if !known_axis {
                match format!("{}", code).as_str() {
                    // Right trigger
                    "ABS(9)" => {
                        self.gamepad.get_axis_ref(GamepadAxis::RightTrigger).value =
                            in_axis.convert_into(false);
                    }
                    // Left trigger
                    "ABS(10)" => {
                        self.gamepad.get_axis_ref(GamepadAxis::LeftTrigger).value =
                            in_axis.convert_into(false);
                    }
                    // Left stick
                    "ABS(0)" => {
                        self.gamepad.get_axis_ref(GamepadAxis::LeftJoystickX).value =
                            in_axis.convert_into(false);
                    }
                    "ABS(1)" => {
                        self.gamepad.get_axis_ref(GamepadAxis::LeftJoystickY).value =
                            in_axis.convert_into(false);
                    }
                    // Right stick
                    "ABS(2)" => {
                        self.gamepad.get_axis_ref(GamepadAxis::RightJoystickX).value =
                            in_axis.convert_into(false);
                    }
                    "ABS(5)" => {
                        // For some reason this is inverted..
                        self.gamepad.get_axis_ref(GamepadAxis::RightJoystickY).value =
                            in_axis.invert().convert_into(false);
                    }
                    _ => {
                        // FIXME: turned off for spam, some axes seem duplicated?...
                        println!("Unknown axis!: {}/{}", code, axis.value());
                    }
                }
            }
        }
    }
}

impl ControllerInput for GilRsInput {
    type ControllerType = GilRsInput;

    fn to_gamepad<'b>(&'b mut self) -> &'b Gamepad {
        return &self.gamepad;
    }

    fn discover_all() -> Vec<Self::ControllerType> {
        let gilrs = Gilrs::new().unwrap();

        let mut inps: Vec<Self::ControllerType> = vec![];

        macro_rules! ignore_controller {
            ($gamepad:expr, $s:expr) => {
                if $gamepad.name().contains($s) | $gamepad.os_name().contains($s) {
                    continue;
                }
            }
        }

        for (_id, gamepad) in gilrs.gamepads() {
            let gilrs_current_gamepad = Gilrs::new().unwrap();
            
            // e.g. Nintendo Wii Remote Nunchuk
            ignore_controller!(gamepad, "Wii");
            ignore_controller!(gamepad, "Nunchuk");
            

            inps.push(Self::ControllerType::new(
                gilrs_current_gamepad,
                gamepad.id(),
            ));
            println!(
                "Detected!: {}/{}/{}",
                gamepad.id(),
                gamepad.name(),
                gamepad.os_name()
            );
        }

        return inps;
    }

    fn prep_for_input_events(&mut self) {
        println!("GilRsInput connected: {}", self.get_gilrs_gamepad().name());
    }

    async fn get_next_inputs(&mut self) -> Result<bool, &'static str> {
        self.map_gilrs_to_gamepad();
        return Ok(true);
    }
}
