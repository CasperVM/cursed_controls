use std::{
    cell::Ref,
    time::{Duration, SystemTime},
    vec,
};

use futures::TryStreamExt;
use futures_util::StreamExt;
use num_traits::ToPrimitive;
use xwiimote::{
    events::{Event as WiiEvent, KeyState},
    Address, Channels, Device, Monitor,
};

use crate::controller_abs::{
    Axis, ControllerInput, ControllerMapping, Gamepad, GamepadAxis, GamepadButton, OutputMapping,
};
use futures::executor::block_on;
use gilrs::{
    Axis as GilAxis, Button as GilButton, Event as GilEvent, EventType as GilEventType,
    Gamepad as GilGamepad, GamepadId as GilGamepadId, Gilrs,
};

use gilrs::ev::state::AxisData as GilAxisData;
use gilrs::ev::Code as GilCode;
use std::cell::RefCell;
use std::collections::{HashMap, VecDeque};
use std::rc::Rc;

// TODO: use actix?

struct XWiiEvent(WiiEvent);

impl XWiiEvent {
    // Constructor to wrap an Event into MyEvent
    fn new(event: WiiEvent) -> Self {
        XWiiEvent(event)
    }
}

impl PartialEq for XWiiEvent {
    fn eq(&self, other: &Self) -> bool {
        match (&self.0, &other.0) {
            (WiiEvent::Key(key1, _), WiiEvent::Key(key2, _)) => {
                std::mem::discriminant(key1) == std::mem::discriminant(key2)
            }
            (WiiEvent::NunchukKey(key1, _), WiiEvent::NunchukKey(key2, _)) => {
                std::mem::discriminant(key1) == std::mem::discriminant(key2)
            }
            (WiiEvent::NunchukMove { .. }, WiiEvent::NunchukMove { .. }) => true,
            // FIXME: Add others...
            _ => false,
        }
    }
}

pub struct XWiiInput {
    device: Device,
    gamepad: Gamepad,
    channels: Channels,
    mappings: Vec<ControllerMapping<WiiEvent>>,
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

    pub fn map_event(&mut self, event: WiiEvent, to_mapping: OutputMapping) {
        self.mappings.push(ControllerMapping {
            input: event,
            output: to_mapping.clone(),
        });
    }

    fn map_event_to_gamepad(&mut self, event: WiiEvent) {
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
                WiiEvent::Key(_key, key_state) => {
                    button_to_gamepad!(self, &controller_mapping.output, key_state);
                }
                WiiEvent::NunchukKey(_key, key_state) => {
                    button_to_gamepad!(self, &controller_mapping.output, key_state);
                }
                WiiEvent::NunchukMove {
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

    pub fn get_device(&self) -> &Device {
        &self.device
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

    pub fn discover_all() -> Box<dyn Iterator<Item = Self>> {
        let monitor = Monitor::enumerate().unwrap();

        let addresses: Vec<_> = block_on(async { monitor.collect().await });

        let mut inps: Vec<Self> = vec![];
        for address in addresses {
            inps.push(Self::new(&address.unwrap()));
        }

        Box::new(inps.into_iter())
    }
}

impl ControllerInput for XWiiInput {
    type ControllerType = XWiiInput;

    fn to_gamepad<'a>(&'a mut self) -> &'a Gamepad {
        return &self.gamepad;
    }

    fn prep_for_input_events(&mut self) {
        // TODO: better decice handling with disconnects etc.
        self.device
            .open(Channels::from_bits(self.channels.bits()).unwrap(), true)
            .unwrap();
        println!("XWiiInput connected: {}", self.device.kind().unwrap());
    }
}

// --- GILRS ---
pub struct GilRsHandler {
    pub gilrs: Gilrs,
    event_queue: HashMap<u8, VecDeque<(SystemTime, GilEventType)>>,
}

impl GilRsHandler {
    pub fn new() -> Self {
        Self {
            gilrs: Gilrs::new().unwrap(),
            event_queue: HashMap::new(),
        }
    }

    pub fn process_events(&mut self) {
        while let Some(GilEvent { id, event, time }) = self.gilrs.next_event() {
            println!("{:?} New event from {:?}: {:?}", time, id, event);

            // Format `GamepadId` as a string and then parse it into a `usize`
            let gamepad_id_str = id.to_string();
            let gamepad_id: u8 = gamepad_id_str.parse().unwrap();

            // Insert the event into the queue for this gamepad ID
            let queue = self
                .event_queue
                .entry(gamepad_id)
                .or_insert_with(VecDeque::new);

            // Add the event and time to the queue
            queue.push_back((time, event));
        }
    }

    pub fn dequeue_event_queue(&mut self, id: GilGamepadId) -> Vec<(SystemTime, GilEventType)> {
        let gamepad_id_str = id.to_string();
        let gamepad_id: u8 = gamepad_id_str.parse().unwrap();

        if let Some(queue) = self.event_queue.get_mut(&gamepad_id) {
            let events: Vec<(SystemTime, GilEventType)> = queue.drain(..).collect();
            events
        } else {
            Vec::new() // Return an empty Vec if no events exist for the given ID
        }
    }

    pub fn discover_all(
        &self,
        self_ref: Rc<RefCell<GilRsHandler>>,
    ) -> Box<dyn Iterator<Item = GilRsInput>> {
        let mut inps = Vec::new();

        macro_rules! ignore_controller {
            ($gamepad:expr, $s:expr) => {
                if $gamepad.name().contains($s) | $gamepad.os_name().contains($s) {
                    continue;
                }
            };
        }

        for (_id, gamepad) in self.gilrs.gamepads() {
            // e.g. Nintendo Wii Remote Nunchuk
            ignore_controller!(gamepad, "Wii");
            ignore_controller!(gamepad, "Nunchuk");

            inps.push(GilRsInput::new(Rc::clone(&self_ref), gamepad.id()));
            // println!(
            //     "Detected!: {}/{}/{}",
            //     gamepad.id(),
            //     gamepad.name(),
            //     gamepad.os_name()
            // );
        }

        Box::new(inps.into_iter())
    }
}

#[derive(Copy, Clone, Debug)]
pub enum GilInputs {
    Axis((GilAxis, GilCode)),
    Button((GilButton, GilCode)),
}

pub struct GilRsInput {
    gilrs_handler: Rc<RefCell<GilRsHandler>>,
    gamepad: Gamepad,
    pub id: GilGamepadId,
    mappings: Vec<ControllerMapping<GilInputs>>,
    deadzone_percentage: f64,
}

impl GilRsInput {
    pub fn new(gilrs_handler: Rc<RefCell<GilRsHandler>>, id: GilGamepadId) -> GilRsInput {
        GilRsInput {
            gilrs_handler,
            gamepad: Gamepad::new(),
            id,
            mappings: vec![],
            deadzone_percentage: 0.05, // 5%
        }
    }

    pub fn get_inputs_for_mapping<O: Into<Option<bool>>, O2: Into<Option<Vec<GilInputs>>>>(
        &self,
        duration_secs: u64,
        listen_for_gyro_opt: O,
        ignore_axes_opt: O2,
    ) -> Vec<GilInputs> {
        let listen_for_gyro = listen_for_gyro_opt.into().unwrap_or(false);
        let ignore_axes: Vec<GilInputs> = ignore_axes_opt.into().unwrap_or(vec![]);
        let mut gilrs_handler_ref = self.gilrs_handler.borrow_mut();
        let outputmappings = vec![];

        let mut tracky = 0;
        while tracky <= duration_secs {
            let mut dequeued_evs = gilrs_handler_ref.dequeue_event_queue(self.id);
            dequeued_evs.sort_by_key(|k| k.0);

            let mut outputmappings = vec![];
            'ev_loop: for ev in dequeued_evs {
                match ev.1 {
                    GilEventType::AxisChanged(gil_axis, _val, code) => {
                        for ignore_axis in &ignore_axes {
                            match ignore_axis {
                                &GilInputs::Axis(ignore) => {
                                    if gil_axis == ignore.0 && code == ignore.1 {
                                        // gyro! ignore.
                                        // FIXME: add support.
                                        continue 'ev_loop;
                                    }
                                }
                                _ => {}
                            }
                        }
                        // Axis is always -1.0 - 1.0
                        outputmappings.push(GilInputs::Axis((gil_axis, code)));
                    }
                    GilEventType::ButtonPressed(button, code)
                    | GilEventType::ButtonRepeated(button, code)
                    | GilEventType::ButtonReleased(button, code) => {
                        if listen_for_gyro {
                            // ignore
                            break;
                        }
                        outputmappings.push(GilInputs::Button((button, code)));
                    }
                    GilEventType::ButtonChanged(button, _val, code) => {
                        // Potentially an axis?... Unsure what do with that, for now let's just map this as a regular button...
                        if listen_for_gyro {
                            // ignore
                            break;
                        }
                        outputmappings.push(GilInputs::Button((button, code)));
                    }
                    _ => {
                        // TODO: disconnects
                    }
                }
            }
            if listen_for_gyro {
                println!("Listening for accelerometer/gyro data, move your controller around gently ({}s)", tracky);
            } else {
                println!("Waiting for input ({}s)", tracky);
            }

            std::thread::sleep(Duration::from_secs(1));
            tracky += 1;
        }
        outputmappings
    }

    pub fn get_gilrs(&self) -> Ref<'_, Gilrs> {
        Ref::map(self.gilrs_handler.borrow(), |x| &x.gilrs)
    }
}

impl ControllerInput for GilRsInput {
    type ControllerType = GilRsInput;

    fn to_gamepad(&mut self) -> &Gamepad {
        return &self.gamepad;
    }

    fn prep_for_input_events(&mut self) {
        println!(
            "GilRsInput connected: {}",
            self.get_gilrs().gamepad(self.id).name()
        );
    }
}
