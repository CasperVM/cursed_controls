# Raspbian setup

Tested on Raspberry Pi Zero 2W (64-bit Raspberry Pi OS).

## System dependencies

```bash
sudo apt update -y && sudo apt upgrade -y
sudo apt install -y git python3-venv bluetooth bluez \
    libtool autoconf automake m4 libudev-dev libncurses5-dev \
    linux-headers-rpi-v8
```

Details:
- `xwiimote` dependencies: `libtool autoconf automake m4 libudev-dev libncurses5-dev`
- `raw-gadget` dependency: `linux-headers-rpi-v8` (use `rpi-{v6,v7,v7l}` on 32-bit)

## Bluetooth / Wiimote

Add a udev rule so evdev devices are readable without root:

```bash
echo 'KERNEL=="uinput", MODE="0666"' | sudo tee -a /etc/udev/rules.d/wiimote.rules
sudo service udev restart
```

Disable the `ClassicBondedOnly` restriction in BlueZ so Wiimotes stay connected:

```bash
echo 'ClassicBondedOnly=false' | sudo tee -a /etc/bluetooth/input.conf
sudo service bluetooth restart
```

Build and install `xwiimote`:

```bash
cd ~
git clone https://github.com/xwiimote/xwiimote.git
cd xwiimote
./autogen.sh
make -j
sudo make install
```

## USB OTG / raw-gadget

Enable the USB OTG overlay:

```bash
echo "dtoverlay=dwc2" | sudo tee -a /boot/firmware/config.txt
echo "dwc2" | sudo tee -a /etc/modules
```

Build and install raw-gadget:

```bash
cd ~
git clone https://github.com/xairy/raw-gadget.git
cd ~/raw-gadget/raw_gadget
make -j
```

## Get cursed_controls

```bash
cd ~
git clone https://github.com/Berghopper/cursed_controls.git
cd cursed_controls
git submodule update --init --recursive
```

## Build the gadget library

Install Rust if not already present:

```bash
# Set RUSTUP_IO_THREADS=1 on Pi Zero to avoid OOM during install
export RUSTUP_IO_THREADS=1
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env
```

Build the shared library:

```bash
cd ~/cursed_controls/python/360-w-raw-gadget
cargo build --release
# produces: target/release/libx360_w_raw_gadget.so
```

## Python setup

```bash
cd ~/cursed_controls/python
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Reboot

Reboot after enabling the OTG overlay and adding kernel modules:

```bash
sudo reboot
```

## Load kernel modules

After reboot, load the required modules (or use the provided script):

```bash
./init-raspbian.sh
# which runs:
#   sudo modprobe uinput
#   sudo modprobe hid-wiimote
#   cd ~/raw-gadget/raw_gadget && sudo ./insmod.sh
```

## Running

Connect your Wiimote via Bluetooth:

```bash
bluetoothctl
# scan on
# connect <WIIMOTE-MAC>
```

Run cursed_controls (needs root for raw-gadget):

```bash
cd ~/cursed_controls/python
source .venv/bin/activate
sudo .venv/bin/cursed-controls run example_wiimote.yaml
```

## Power saving (Pi Zero 2W headless)

`/boot/firmware/config.txt`:

```toml
[all]
dtoverlay=dwc2

# Power save
dtoverlay=disable-bt=off
dtoverlay=disable-wifi=off
hdmi_blanking=1
hdmi_ignore_hotplug=1
camera_auto_detect=0
display_auto_detect=0
dtparam=audio=off
gpu_mem=16
dtparam=act_led_trigger=none
dtparam=act_led_activelow=on
```

## Known issues

- Some system packages may conflict with `xwiimote`. A clean install following this guide is the most reliable approach.
- On 32-bit OS, replace `linux-headers-rpi-v8` with `linux-headers-rpi-{v6,v7,v7l}`.
