# cursed_controls

[![Test](https://github.com/CasperVM/cursed_controls/actions/workflows/test.yml/badge.svg)](https://github.com/CasperVM/cursed_controls/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi-c51a4a)](https://www.raspberrypi.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Universal controller receiver and mapper running on an sbc.

Got a weird Bluetooth controller that nothing supports natively? Xbox 360 controllers work on nearly everything. So make it one.

cursed_controls runs on a Raspberry Pi Zero between your controllers and the host, emulating a real Xbox 360 wireless receiver over USB OTG. Combine multiple physical devices into a single virtual Xbox pad (think Wii Remote + Nunchuk), with up to 4 controller slots. Works on Windows and Linux; macOS might limited to 1 slot on older versions.

I initially wanted to make this, as some games (especially in unity) can be super finicky about the controllers connected. e.g. even a wireless xbox controller can sometimes cause weird mappings and other issues. In these cases it's useful to 'act' as a wired controller, while still having the benefit of being wireless :D. This completely circumvents having to do painful config on the host/gaming machine where you just want to play. Instead you just let the pi handle it. This is also useful for when you just want to switch between multiple devices without having to pair your BT controllers CONSTANTLY.

Tested on Raspberry Pi Zero W and Pi Zero 2W.

> **Small disclaimer**: The hard part of initially making it work was done by hand. However, to finish this project and make it useful, this was partially vibe coded (yes I know, very bad. But finished is better than never seeing the light of day).

## [Demo](https://caspervm.github.io/cursed_controls/)

This is a visual mock of the web UI for quick exploration. It does not connect to hardware, Bluetooth, APIs, or the live backend.

## How it works

1. Physical controllers connect to the Pi (Bluetooth, USB, etc.) and appear as evdev devices.
2. `cursed-controls` reads their events, applies a YAML mapping config, and builds Xbox 360 HID packets.
3. Packets are sent to [360-w-raw-gadget](https://github.com/CasperVM/360-w-raw-gadget) (a submodule), which emulates a real Xbox 360 wireless receiver over the Pi's USB OTG port.
4. Rumble commands from the host are forwarded back to any physical device that supports force feedback.

## Requirements

- Raspberry Pi (or similar SBC) with a USB OTG port
- Python 3.11+
- `raw_gadget` kernel module (handled by `install.sh`)
- `360-w-raw-gadget` built as a shared library (handled by `install.sh`)
- Plugging in the pi over USB (duh)

## Setup

See [SetupRaspbian.md](SetupRaspbian.md) for the full Pi setup guide.

`curl|bash` oneline installs (RUN ON PI):

**One-liner (recommended):**

```bash
curl -fsSL https://raw.githubusercontent.com/CasperVM/cursed_controls/main/install.sh | bash
```

**Headless appliance** — faster boot, lower idle power, no HDMI:

```bash
curl -fsSL https://raw.githubusercontent.com/CasperVM/cursed_controls/main/install.sh | bash -s -- --headless-fast-boot
```

**Prefer to inspect first?**

```bash
git clone https://github.com/CasperVM/cursed_controls.git
bash ~/cursed_controls/install.sh [--headless-fast-boot]
```

The installer is safe to re-run — each step skips if already complete.

### Web UI / After install go to: `http://<pi-ip>:8000`

Open the web UI from another device on the same network at the above url.

Example:

`http://192.168.1.123:8000`

`--headless-fast-boot` adds these settings to `config.txt`:

```text
hdmi_blanking=1
hdmi_ignore_hotplug=1
camera_auto_detect=0
display_auto_detect=0
dtparam=audio=off
gpu_mem=16
dtparam=act_led_trigger=none
dtparam=act_led_activelow=on
```

It does not disable Wi-Fi or Bluetooth.

## Running CLI

```bash
# List detected input devices
cursed-controls list-devices

# Run with a mapping config (requires root for raw-gadget)
sudo cursed-controls run mapping.yaml

# Dry-run: print packets to stdout instead of opening gadget
cursed-controls run --stdout mapping.yaml

# Interactive simulation (no hardware needed)
cursed-controls simulate mapping.yaml

# Interactive TUI to build a new mapping file (WIP — see note below)
cursed-controls map mapping.yaml

# Live axis debug TUI: shows per-axis current value, min/max, and bar chart
# Run without arguments to get a device selection menu
python scripts/show_axis_range.py
python scripts/show_axis_range.py /dev/input/eventN   # skip menu
```

> **Note on `map`:** The interactive mapper is a work in progress. It can be
> finicky with drifty axes (e.g. Nunchuk joystick). For reliable results,
> especially when tuning axis ranges, it's often easier to edit the YAML
> directly. Use `show_axis_range.py` to find the real min/max values, then
> set `source_min`/`source_max` by hand.

The Raspberry Pi install uses `cursed-controls-web.service`, which starts the web UI on boot. From the UI, you can edit `mapping.yaml` and start or stop the gadget runtime.

## Config format

```yaml
runtime:
  output_mode: gadget        # or "stdout" for dry-run
  gadget_library: 360-w-raw-gadget/target/release/libx360_w_raw_gadget.so
  # gadget_driver is auto-detected from /sys/class/udc/ — override only if needed
  interfaces: 1              # controller slots (1–4)
  rumble: true               # forward rumble to physical devices

devices:
  - id: my-controller
    connection:
      type: wiimote          # wiimote | bluetooth | evdev (default)
      timeout_s: 60          # how long to wait/scan before giving up
    match:
      name: "Nintendo Wii Remote"   # match by name, uniq, or phys
    mappings:
      # Button → button
      - source_type: 1    # EV_KEY
        source_code: 304  # BTN_A
        target: A
        kind: button

      # Button → axis (e.g. trigger)
      - source_type: 1
        source_code: 305  # BTN_B
        target: RIGHT_TRIGGER
        kind: button
        on_value: 255
        off_value: 0

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

### Connection types

| type | behaviour |
|---|---|
| `evdev` | Device is already in `/dev/input/` (default) |
| `bluetooth` | Connect by MAC at startup (`mac:` required) |
| `wiimote` | Scan for Nintendo Wii Remote; user presses 1+2 |

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

- [`example_wiimote.yaml`](example_wiimote.yaml) — Wii Remote + Nunchuk (generic)
- [`example_rocket_league.yaml`](example_rocket_league.yaml) — Wii Remote + Nunchuk for Rocket League
- [`example_tv_remote.yaml`](example_tv_remote.yaml) — Wii Remote only, held vertically (navigation/media)
- [`example_xbox_passthrough.yaml`](example_xbox_passthrough.yaml) — Xbox Wireless Controller passthrough

## Rumble

When `rumble: true`, the runtime polls the gadget for rumble commands from the host each tick and forwards them to any bound physical device that exposes `EV_FF` / `FF_RUMBLE`. Works with Wii Remotes (the `hid-wiimote` driver exposes FF).

## Testing

```bash
pytest
# or with uv:
uv run pytest
```

All tests run without hardware (FakeSink, mock devices).
