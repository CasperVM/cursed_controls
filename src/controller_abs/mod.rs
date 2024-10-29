use std::{
    collections::HashMap,
    ops::{Div, Sub},
    u64,
};

use num_traits::{Bounded, FromPrimitive, NumCast, ToPrimitive};
use strum::IntoEnumIterator;
use strum_macros::EnumIter;

pub trait NormalizableNumber:
    Bounded + ToPrimitive + FromPrimitive + NumCast + Sub<Output = Self> + Div<Output = Self> + Copy
{
}
impl<T> NormalizableNumber for T where
    T: Bounded + ToPrimitive + FromPrimitive + NumCast + Sub<Output = T> + Div<Output = T> + Copy
{
}

// help, generics :(...
pub fn normalize<From, To, FR: Into<Option<From>>, TR: Into<Option<To>>>(
    from_value: From,
    from_min: FR,
    from_max: FR,
    to_min: TR,
    to_max: TR,
) -> To
where
    From: NormalizableNumber,
    To: NormalizableNumber,
{
    // Safely convert min and max values to f64
    let from_min_f64 = from_min
        .into()
        .unwrap_or_else(|| From::min_value())
        .to_f64()
        .unwrap();
    let from_max_f64 = from_max
        .into()
        .unwrap_or_else(|| From::max_value())
        .to_f64()
        .unwrap();

    let from_range_ = (from_min_f64 - from_max_f64).abs();

    let to_min_f64 = to_min
        .into()
        .unwrap_or_else(|| To::min_value())
        .to_f64()
        .unwrap();
    let to_max_f64 = to_max
        .into()
        .unwrap_or_else(|| To::max_value())
        .to_f64()
        .unwrap();
    let to_range_ = (to_max_f64 - to_min_f64).abs();

    // Normalize the from_value to the [0, 1] range as f64
    let normalized_value = (from_value.to_f64().unwrap() - from_min_f64) / from_range_;

    // Scale the normalized value to the target type's range
    let scaled_value = normalized_value * to_range_ + to_min_f64;

    // Convert the clamped value to the target type
    To::from_f64(scaled_value).unwrap_or_else(|| {
        if scaled_value < to_min_f64 {
            To::min_value()
        } else {
            To::max_value()
        }
    })
}

macro_rules! normalize {
    ($from_value:expr, $fmin:expr, $fmax:expr) => {
        normalize($from_value, $fmin, $fmax, None, None)
    };
}

#[allow(unused_macros)]
macro_rules! normalizeT {
    ($from_value:expr, $tmin:expr, $tmax:expr) => {
        normalize($from_value, None, None, $tmin, $tmax)
    };
}

#[test]
fn test_normalization() {
    let val: i32 = 0;
    let min: i32 = -50;
    let max: i32 = 50;

    let norm_val_u8: u8 = normalize(val, min, max, None, None);
    let norm_val_u8_macro: u8 = normalize!(val, min, max);

    assert_eq!(norm_val_u8, 127);
    assert_eq!(norm_val_u8_macro, 127);

    // and back :)
    let norm_val_back: i32 = normalize(val, None, None, min, max);
    let norm_val_back_macro: i32 = normalizeT!(val, min, max);

    assert_eq!(norm_val_back, 0);
    assert_eq!(norm_val_back_macro, 0);

    // Test again, but f64
    assert_eq!(normalize::<f64, u8, _, _>(-0.9, -1.0, 1.0, None, None), 12);
    assert_eq!(normalize::<f64, u8, _, _>(-1.0, -1.0, 1.0, None, None), 0);
    assert_eq!(normalize::<f64, u8, _, _>(1.0, -1.0, 1.0, None, None), 255);
    assert_eq!(normalize::<f64, u8, _, _>(0.9, -1.0, 1.0, None, None), 242);
}

// Values in axis are all u64, most likely controllers will have smaller sizes, so more easily convertible.
#[derive(Clone, Debug)]
pub struct Axis {
    pub value: u64,
    min: u64,
    max: u64,
    deadzones: Option<Vec<std::ops::Range<u64>>>,
}

#[macro_export]
macro_rules! AxisNew {
    ($v: expr) => {
        Axis::new($v, None, None)
    };
    ($t:ty, $v:expr) => {
        Axis::new::<$t, _>($v, None, None)
    };
}

impl Axis {
    pub fn new<T, RT: Into<Option<T>> + Copy>(from_value: T, min: RT, max: RT) -> Axis
    where
        T: NormalizableNumber,
    {
        // let min_val = normalize!(
        //     min.into().unwrap_or_else(|| T::min_value()),
        //     T::min_value(),
        //     T::max_value()
        // );
        // let max_val = normalize!(
        //     max.into().unwrap_or_else(|| T::max_value()),
        //     T::min_value(),
        //     T::max_value()
        // );

        let min_val = u64::MIN;
        let max_val = u64::MAX;

        Axis {
            value: normalize(from_value, min.into(), max.into(), min_val, max_val),
            min: min_val,
            max: max_val,
            deadzones: None,
        }
    }

    pub fn set_values<T>(&mut self, from_value: T, min: Option<T>, max: Option<T>)
    where
        T: NormalizableNumber,
    {
        let min_val = normalize!(
            min.unwrap_or_else(|| T::min_value()),
            T::min_value(),
            T::max_value()
        );
        let max_val = normalize!(
            max.unwrap_or_else(|| T::max_value()),
            T::min_value(),
            T::max_value()
        );
        self.value = normalize(
            from_value,
            min,
            max,
            min.unwrap().to_u64(),
            max.unwrap().to_u64(),
        );
        self.min = min_val;
        self.max = max_val;
    }

    pub fn get_value(&mut self) -> &u64 {
        &self.value
    }

    pub fn get_normalized_value(&mut self) -> f64 {
        return normalize(self.value, self.min, self.max, 0.0, 1.0);
    }

    pub fn get_min(&mut self) -> &u64 {
        &self.min
    }

    pub fn get_max(&mut self) -> &u64 {
        &self.max
    }

    pub fn set_deadzones(&mut self, deadzones: Vec<std::ops::Range<u64>>) {
        self.deadzones = Some(deadzones);
    }

    pub fn get_deadzones(&mut self) -> &Option<Vec<std::ops::Range<u64>>> {
        return &self.deadzones;
    }

    pub fn make_deadzone<T>(
        &self,
        input: Vec<std::ops::Range<T>>,
        min: T,
        max: T,
    ) -> Vec<std::ops::Range<u64>>
    where
        T: NormalizableNumber,
    {
        input
            .into_iter()
            .map(|range| {
                let start_normalized: u64 = normalize(range.start, min, max, self.min, self.max);
                let end_normalized: u64 = normalize(range.end, min, max, self.min, self.max);
                std::ops::Range {
                    start: start_normalized,
                    end: end_normalized,
                }
            })
            .collect()
    }

    pub fn convert_into<T, D>(&self, use_deadzones: D) -> T
    where
        T: NormalizableNumber,
        D: Into<Option<bool>>,
    {
        // Normalization step, usually between two different Axis systems
        // Apply deadzones if needed
        if use_deadzones.into().unwrap_or(true) {
            if let Some(deadzones) = &self.deadzones {
                for deadzone in deadzones {
                    if deadzone.contains(&self.value) {
                        let norm_range =
                            (self.min.to_f64().unwrap() - self.max.to_f64().unwrap()).abs();
                        let normalized_ratio = (self.value.to_f64().unwrap()
                            - self.min.to_f64().unwrap())
                            / norm_range;
                        let deadzone_start_ratio = (deadzone.start.to_f64().unwrap()
                            - self.min.to_f64().unwrap())
                            / norm_range;
                        let deadzone_end_ratio = (deadzone.end.to_f64().unwrap()
                            - self.min.to_f64().unwrap())
                            / norm_range;

                        if deadzone_start_ratio > 0.3 && deadzone_end_ratio < 0.7 {
                            // 'middle' deadzone?
                            let middle_value_f64 = self.min.to_f64().unwrap()
                                + (self.max.to_f64().unwrap() - self.min.to_f64().unwrap()) / 2.0;
                            return T::from_f64(middle_value_f64).unwrap();
                        } else if normalized_ratio < 0.3 {
                            // Min
                            return T::min_value();
                        } else {
                            // Max
                            return T::max_value();
                        }
                    }
                }
            }
        }

        return normalize!(self.value, self.min, self.max);
    }

    pub fn invert(&self) -> Self {
        let inverted_value = self.min + (self.max - self.value);
        Axis {
            value: inverted_value,
            min: self.min,
            max: self.max,
            deadzones: self.deadzones.clone(),
        }
    }
}

impl Default for Axis {
    fn default() -> Self {
        Axis {
            min: u64::MIN,
            max: u64::MAX,
            value: 0,
            deadzones: None,
        }
    }
}

#[test]
fn test_axis() {
    assert_eq!(
        Axis::new::<u8, _>(127, u8::MIN, u8::MAX).convert_into::<u8, _>(false),
        127
    );
    assert_eq!(
        Axis::new::<u8, _>(50, 0, 100).convert_into::<u8, _>(false),
        127
    );
    assert_eq!(Axis::new(0.0, -1.0, 1.0).convert_into::<u8, _>(false), 127);
}

#[derive(Clone)]
pub struct BitPackedButton {
    // Button with it's corresponding address
    name: Option<String>,
    pub value: bool,
    addr: u8,
}

impl BitPackedButton {
    pub fn new<N: Into<Option<String>>>(name: N, addr: u8) -> BitPackedButton {
        BitPackedButton {
            name: name.into(),
            value: false,
            addr,
        }
    }
}

pub struct BitPackedButtons {
    pub buttons: Vec<BitPackedButton>,
}

impl BitPackedButtons {
    pub fn get_by_name(self: &Self, name: &String) -> Option<&BitPackedButton> {
        self.buttons
            .iter()
            .find(|button| button.name.as_ref() == Some(name))
    }

    pub fn to_bytes_repr(self: &Self) -> u8 {
        let mut buttons_sorted = self.buttons.to_vec();
        buttons_sorted.sort_by_key(|button| button.addr);
        return buttons_sorted
            .iter()
            .map(|button| (button.value as u8) << button.addr)
            .fold(0, |acc, bit| acc | bit);
    }
}

// Joystick is usually just 2 Axis'
pub struct JoystickState {
    pub x: Axis,
    pub y: Axis,
}

#[macro_export]
macro_rules! JoystickStateNew {
    ($t:ty, $v:expr) => {
        JoystickState::new(AxisNew!($t, $v), AxisNew!($t, $v))
    };
}

impl JoystickState {
    pub fn new(axis1: Axis, axis2: Axis) -> JoystickState {
        JoystickState { x: axis1, y: axis2 }
    }
}

// Generic gamepad
#[derive(EnumIter, Hash, Eq, PartialEq, Clone, Debug)]
pub enum GamepadButton {
    North,
    East,
    South,
    West,
    LeftShoulderButton,
    RightShoulderButton,
    Select,
    Start,
    Mode,
    LeftThumb,
    RightThumb,
    DPadUp,
    DPadDown,
    DPadLeft,
    DPadRight,
}

#[derive(EnumIter, PartialEq, Eq, Hash, Clone, Debug)]
pub enum GamepadAxis {
    LeftTrigger,
    RightTrigger,
    LeftJoystickX,
    LeftJoystickY,
    RightJoystickX,
    RightJoystickY,
}

pub struct Gamepad {
    pub buttons: HashMap<GamepadButton, bool>,
    pub axes: HashMap<GamepadAxis, Axis>,
}

impl Gamepad {
    pub fn new() -> Self {
        let mut buttons = HashMap::new();
        let mut axes = HashMap::new();

        // Automatically include all enum variants
        for button in GamepadButton::iter() {
            // buttons.insert(button);
            buttons.insert(button, false);
        }
        for axis_type in GamepadAxis::iter() {
            axes.insert(axis_type, AxisNew!(0));
        }

        Gamepad { buttons, axes }
    }

    pub fn set_button(self: &mut Self, button: GamepadButton, value: bool) {
        *self.buttons.get_mut(&button).unwrap() = value;
    }

    pub fn get_axis_ref(self: &mut Self, axis: GamepadAxis) -> &mut Axis {
        return self.axes.get_mut(&axis).unwrap();
    }
}

pub enum InputType {
    Button,
    Axis,
}

// Mappings
#[derive(Clone, Debug)]
pub enum OutputMapping {
    Button(GamepadButton),
    Axis(GamepadAxis),
}

pub struct ControllerMapping<T>
where
    T: Clone,
{
    pub input: T,
    pub output: OutputMapping,
}

pub trait ControllerInput {
    type ControllerType;
    fn to_gamepad(&mut self) -> &Gamepad;
    fn prep_for_input_events(&mut self);
}
