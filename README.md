# cursed_controls

Map any evdev input device to a virtual Xbox 360 wireless receiver over USB OTG. Turns a Raspberry Pi into a controller adapter. e.g. Wii Remote + Nunchuk or any generic gamepad → Xbox 360.

Tested on Raspberry Pi Zero 2W.

## How it works

1. Physical controllers connect to the Pi (Bluetooth, USB, etc.) and appear as evdev devices.
2. `cursed-controls` reads their events, applies a YAML mapping config, and builds Xbox 360 HID packets.
3. Packets are sent to [360-w-raw-gadget](python/360-w-raw-gadget/) (a submodule), which emulates a real Xbox 360 wireless receiver over the Pi's USB OTG port.
4. Rumble commands from the host are forwarded back to any physical device that supports force feedback.

## Requirements

- Linux (Raspberry Pi or similar SBC with USB OTG)
- Python 3.11+
- `evdev` Python package
- `360-w-raw-gadget` built as a shared library (see below)
- `raw_gadget` kernel module

## Setup

See [SetupRaspbian.md](SetupRaspbian.md) for the full Pi setup guide (Bluetooth, OTG, raw-gadget, venv).

## Building the gadget library

```bash
cd python/360-w-raw-gadget
cargo build --release
# produces python/360-w-raw-gadget/target/release/libx360_w_raw_gadget.so
```

## Installing the Python package

```bash
cd python
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Running

```bash
# List detected input devices
cursed-controls list-devices

# Run with a mapping config (requires root for gadget + raw-gadget)
sudo cursed-controls run example_wiimote.yaml

# Dry-run: print packets to stdout instead of opening gadget
cursed-controls run --stdout example_wiimote.yaml

# Interactive simulation (no hardware needed)
cursed-controls simulate example_wiimote.yaml

# Interactive TUI to build a new mapping file
cursed-controls map my_config.yaml
```

## Config format

```yaml
runtime:
  output_mode: gadget        # or "stdout" for dry-run
  gadget_library: 360-w-raw-gadget/target/release/libx360_w_raw_gadget.so
  gadget_driver: 3f980000.usb
  interfaces: 1              # controller slots (1–4)
  rumble: true               # forward rumble to physical devices

devices:
  - id: my-controller
    match:
      name: "Nintendo Wii Remote"   # match by name, uniq, or phys
    mappings:
      # Button → button
      - source_type: 1    # EV_KEY
        source_code: 304  # BTN_A
        target: A
        kind: button

      # Axis → axis (with scaling and deadzone)
      - source_type: 3    # EV_ABS
        source_code: 16   # ABS_HAT0X
        target: LEFT_JOYSTICK_X
        kind: axis
        source_min: -120
        source_max: 120
        target_min: -32767
        target_max: 32767
        deadzone: 0.05

      # Hat axis → d-pad button (ABS_HAT0X/Y, values -1/0/1)
      - source_type: 3
        source_code: 16   # ABS_HAT0X
        target: DPAD_LEFT
        kind: hat
```

### Mapping kinds

| kind | source | target | notes |
|---|---|---|---|
| `button` | `EV_KEY` or `EV_ABS` | button or trigger | `on_value`/`off_value` optional |
| `axis` | `EV_ABS` | joystick or trigger | scales `source_min..max` → `target_min..max` |
| `hat` | `EV_ABS` (`-1/0/1`) | `DPAD_*` | infers direction from target surface |

### Xbox target surfaces

Buttons: `A B X Y BUMPER_L BUMPER_R STICK_L STICK_R START OPTIONS XBOX DPAD_UP DPAD_DOWN DPAD_LEFT DPAD_RIGHT`

Axes: `LEFT_JOYSTICK_X LEFT_JOYSTICK_Y RIGHT_JOYSTICK_X RIGHT_JOYSTICK_Y LEFT_TRIGGER RIGHT_TRIGGER`

## Example configs

- [`example_wiimote.yaml`](python/example_wiimote.yaml) Wii Remote + Nunchuk
- [`example_xbox_passthrough.yaml`](python/example_xbox_passthrough.yaml) Xbox Wireless Controller passthrough

## Rumble

When `rumble: true`, the runtime polls the gadget for rumble commands from the host each tick and forwards them to any bound physical device that exposes `EV_FF` / `FF_RUMBLE`.

## Testing

```bash
cd python
pytest
```

All tests run without hardware (FakeSink, mock devices).
