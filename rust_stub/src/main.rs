use controller_abs::{ControllerInput, GamepadAxis, OutputMapping};
use futures_util::TryStreamExt;
use std::thread::sleep;
use std::time::Duration;
use tokio;
use xwiimote::events::{Event, Key, KeyState, NunchukKey};
use xwiimote::{Monitor, Result};

#[allow(dead_code)]
mod controller_abs;
#[allow(dead_code)]
mod controller_in;
#[allow(dead_code)]
mod controller_out;

use controller_abs::GamepadButton;
use controller_in::{GilRsInput, XWiiInput};

use controller_out::x360::XboxControllerState;

// Declare externals
extern "C" {
    fn init_360_gadget(await_endpoint_availability: bool, n_interfaces: i32) -> i32;
    fn close_360_gadget(fd: i32);
    fn send_to_ep(fd: i32, n: i32, data: *const u8, len: usize) -> bool;
}

fn init_360_gadget_c(await_endpoint_availability: bool, n_interfaces: i32) -> i32 {
    unsafe { init_360_gadget(await_endpoint_availability, n_interfaces) }
}

#[allow(dead_code)]
fn close_360_gadget_c(fd: i32) {
    unsafe { close_360_gadget(fd) }
}

fn send_to_ep_c(fd: i32, n: i32, data: *const u8, len: usize) -> bool {
    unsafe { send_to_ep(fd, n, data, len) }
}

#[allow(dead_code)]
fn example_loop() {
    print!("Starting 360 gadget...");

    let fd = init_360_gadget_c(true, 1);
    let mut controller_state = XboxControllerState::new();
    loop {
        sleep(std::time::Duration::from_secs(1));
        controller_state.buttons.a.value = !controller_state.buttons.a.value;
        controller_state.buttons.b.value = !controller_state.buttons.b.value;
        controller_state.buttons.x.value = !controller_state.buttons.x.value;
        controller_state.buttons.y.value = !controller_state.buttons.y.value;
        // Set left joystick to north-east
        controller_state.left_joystick.x.value = 32760;
        controller_state.left_joystick.y.value = 32760;
        let packet = controller_state.to_packet();
        send_to_ep_c(fd, 0, packet.as_ptr(), 20);
    }
    // close_360_gadget_c(fd);
}

// #[tokio::main(flavor = "current_thread")]
// async fn main() -> Result<()> {
//     // Create a monitor to enumerate connected Wii Remotes
//     let mut monitor = Monitor::enumerate().unwrap();
//     let address = monitor.try_next().await.unwrap().unwrap();
//     let mut wii_input = XWiiInput::new(&address);

//     // Set mapping for rocket league
//     macro_rules! MapKeyToKey {
//         ($key: expr, $button: expr) => {
//             wii_input.map_event(
//                 Event::Key($key, KeyState::Up),
//                 OutputMapping::Button($button),
//             )
//         };
//     }

//     // Jump
//     MapKeyToKey!(Key::A, GamepadButton::South);
//     // Throttle
//     wii_input.map_event(
//         Event::Key(Key::B, KeyState::Up),
//         OutputMapping::Axis(GamepadAxis::RightTrigger),
//     );
//     // Menu
//     MapKeyToKey!(Key::Plus, GamepadButton::Start);
//     MapKeyToKey!(Key::Minus, GamepadButton::Select);
//     MapKeyToKey!(Key::Home, GamepadButton::Mode);
//     // Boost
//     MapKeyToKey!(Key::Down, GamepadButton::East);
//     // Ball cam
//     MapKeyToKey!(Key::One, GamepadButton::North);
//     // Dpad
//     MapKeyToKey!(Key::Up, GamepadButton::DPadUp);
//     MapKeyToKey!(Key::Left, GamepadButton::DPadLeft);
//     MapKeyToKey!(Key::Right, GamepadButton::DPadRight);
//     MapKeyToKey!(Key::Two, GamepadButton::DPadDown);

//     // Nunchuck
//     // Brake
//     wii_input.map_event(
//         Event::NunchukKey(NunchukKey::Z, KeyState::Up),
//         OutputMapping::Axis(GamepadAxis::LeftTrigger),
//     );
//     // Handbrake
//     wii_input.map_event(
//         Event::NunchukKey(NunchukKey::C, KeyState::Up),
//         OutputMapping::Button(GamepadButton::West),
//     );

//     macro_rules! EventNunchuckMove {
//         () => {
//             Event::NunchukMove {
//                 x: 0,
//                 y: 0,
//                 x_acceleration: 0,
//                 y_acceleration: 0,
//             }
//         };
//     }

//     wii_input.map_event(
//         EventNunchuckMove!(),
//         OutputMapping::Axis(controller_abs::GamepadAxis::LeftJoystickX),
//     );
//     wii_input.map_event(
//         EventNunchuckMove!(),
//         OutputMapping::Axis(controller_abs::GamepadAxis::LeftJoystickY),
//     );

//     let fd = init_360_gadget_c(true, 1);
//     let mut controller_state = XboxControllerState::new();
//     wii_input.prep_for_input_events();

//     loop {
//         // println!("Getting inputs...");
//         let _res = wii_input.get_next_inputs().await;
//         // println!("Updating state...");
//         controller_state.update_from_gamepad(wii_input.to_gamepad());
//         // println!("A button: {}", controller_state.buttons.a.value);

//         let success = send_to_ep_c(fd, 0, controller_state.to_packet().as_ptr(), 20);
//         if !success {
//             // Probably crashed?
//             break;
//         }
//         // After sending state, sleep 1ms.
//         tokio::time::sleep(Duration::from_micros(900)).await;
//     }

//     Ok(())
// }




#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let fd = init_360_gadget_c(true, 1);
    let mut controller_state = XboxControllerState::new();
    
    let mut gil_inps = GilRsInput::discover_all();
    gil_inps[0].prep_for_input_events();

    loop {
        // println!("Getting inputs...");
        let _res = gil_inps[0].get_next_inputs().await;
        // println!("Updating state...");
        controller_state.update_from_gamepad(gil_inps[0].to_gamepad());
        // println!("A button: {}", controller_state.buttons.a.value);

        let success = send_to_ep_c(fd, 0, controller_state.to_packet().as_ptr(), 20);
        if !success {
            // Probably crashed?
            break;
        }
        // After sending state, sleep 1ms.
        tokio::time::sleep(Duration::from_micros(900)).await;
    }

    Ok(())
}
