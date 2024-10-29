use controller_abs::{ControllerInput, Gamepad, GamepadAxis, OutputMapping};
use futures_util::TryStreamExt;
use std::cell::RefCell;
use std::io::{self, Write};
use std::rc::Rc;
use std::thread::sleep;
use std::time::Duration;
use strum::IntoEnumIterator;
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
use controller_in::{GilInputs, GilRsHandler, GilRsInput, XWiiInput};

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

fn get_user_input(prompt: &str) -> String {
    print!("{} (q to quit): ", prompt);
    io::stdout().flush().unwrap();

    let mut input = String::new();

    // Read input from stdin (standard input)
    io::stdin()
        .read_line(&mut input)
        .expect("Failed to read user input");

    let retval = input.trim().to_string();

    if retval.to_lowercase() == "q" {
        std::process::exit(0);
    }

    retval
}

fn cli_map_user_input(inp: &mut InputType, outputmapping: OutputMapping) {
    // First await input
    match inp {
        InputType::WiiInput(_wii_inp) => {
            // FIXME
        }
        InputType::GilInput(gil_inp) => {
            // We have no idea which axis's might be gyro, so let's capture it seperately.
            let gyro_inputs = gil_inp.get_inputs_for_mapping(10, true, None);
            let inps = gil_inp.get_inputs_for_mapping(10, false, gyro_inputs);

            loop {
                let choice;
                if inps.len() < 1 {
                    println!("No input was captured!");
                    return;
                } else if inps.len() == 1 {
                    choice = &inps[0];
                } else {
                    println!(
                        "Captured multiple! Select the input you want to use (to map to {:?}):",
                        outputmapping
                    );
                    for (index, inp) in inps.iter().enumerate() {
                        match inp {
                            GilInputs::Axis(x) => {
                                println!("{}. Axis: {:?}, code: {}", index + 1, x.0, x.1)
                            }
                            GilInputs::Button(x) => {
                                println!("{}. Button: {:?}, code: {}", index + 1, x.0, x.1)
                            }
                        }
                    }
                    let userinp = get_user_input("input");
                    let optional_choice = userinp.parse::<usize>();

                    if optional_choice.is_err() {
                        println!("Invalid input, try again");
                        continue;
                    }

                    let choice = optional_choice.unwrap();
                    if choice < 1 || choice > inps.len() {
                        println!("Invalid input, try again");
                        continue;
                    }
                    let x = inps[choice - 1];
                }
            }
        }
    }
}

fn cli_gamepad_settings(inp: &mut InputType) {
    loop {
        // List all output mapping options
        println!("The following options are available to map to (not your input controller!):");
        println!("\n\nButtons:");
        for (index, button) in GamepadButton::iter().enumerate() {
            println!("  {}: {:?}", index + 1, button);
        }

        // Calculate offset for axes numbering
        let button_count = GamepadButton::iter().count();

        // List all Gamepad Axes
        println!("\nAxes:");
        for (index, axis) in GamepadAxis::iter().enumerate() {
            println!("  {}: {:?}", button_count + index + 1, axis);
        }

        let userinp = get_user_input("\n\nSelect which button/axis you want to map to:");
        let optional_choice = userinp.parse::<usize>();

        if optional_choice.is_err()
            || optional_choice.as_ref().unwrap() < &1
            || optional_choice.as_ref().unwrap() > &GamepadButton::iter().len()
        {
            println!("Invalid input, try again");
            continue;
        }
        let choice = optional_choice.unwrap();

        // Button selected
        let selected_button = GamepadButton::iter().nth(choice - 1).unwrap();
        println!("You selected button: {:?}", selected_button);

        // Await user input
        cli_map_user_input(inp, OutputMapping::Button(selected_button));
    }
}

fn cli_gamepads_overview(inps: &mut Vec<InputType>) {
    let n_controllers = inps.len();
    loop {
        println!("Detected {} controller(s):\n", n_controllers);

        let mut n_gamepads: u8 = 0;

        for inp in inps {
            n_gamepads += 1;
            match inp {
                InputType::GilInput(gil_inp) => {
                    let gilrs = gil_inp.get_gilrs();
                    let gil_gampead = gilrs.gamepad(gil_inp.id);
                    if gil_gampead.os_name().to_lowercase() != gil_gampead.name().to_lowercase() {
                        println!(
                            "{}. {} ({})",
                            n_gamepads,
                            gil_gampead.name(),
                            gil_gampead.os_name()
                        );
                    } else {
                        println!("{}. {}", n_gamepads, gil_gampead.name());
                    }
                }
                InputType::WiiInput(_wii_inp) => {
                    println!("Wii mote #{}", n_gamepads);
                }
            }
        }

        let choice: usize;

        loop {
            let inp = get_user_input("Select which controller you would like to set up");

            let gamepad_id = inp.parse::<usize>();
            if gamepad_id.is_err()
                || gamepad_id.as_ref().unwrap() < &1
                || gamepad_id.as_ref().unwrap() > &n_gamepads.into()
            {
                println!("Invalid input, try again");
            } else {
                choice = gamepad_id.unwrap();
                break;
            }
        }
        // wip fix
        cli_gamepad_settings(&mut inps[choice - 1])
    }
}

enum InputType {
    WiiInput(XWiiInput),
    GilInput(GilRsInput),
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let mut inps = vec![];
    // Need to keep gilrs_handler in scope at all times, as it handles the overarching event loop.
    // It's passed as a ref to other input objs.
    let gilrs_handler = Rc::new(RefCell::new(GilRsHandler::new()));

    for inp in XWiiInput::discover_all() {
        inps.push(InputType::WiiInput(inp));
    }

    let gilrs_handler_b = gilrs_handler.borrow_mut();

    for inp in gilrs_handler_b.discover_all(Rc::clone(&gilrs_handler)) {
        inps.push(InputType::GilInput(inp));
    }

    if inps.len() == 0 {
        println!("You have no connected controllers!");
        std::process::exit(1);
    }

    cli_gamepads_overview(&mut inps);

    Ok(())
}

// OLD

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
