# Raspbian setup

Tested on Raspberry Pi Zero 2W (64-bit Raspberry Pi OS). Should work on any Pi with a USB OTG port.

## Quick install (recommended)

Run the install script — it handles everything automatically and is safe to re-run:

```bash
cd ~
git clone https://github.com/Berghopper/cursed_controls.git
bash ~/cursed_controls/install.sh
```

It will:
1. Install system packages (adapts linux-headers to your Pi's architecture)
2. Configure Bluetooth for Wiimote compatibility
3. Enable USB OTG overlay
4. Clone and build `raw-gadget`
5. Install Rust and build the gadget shared library
6. Set up the Python venv
7. Register and enable the `cursed-controls` systemd service

Reboot if prompted, then continue to **Set up your mapping**.

---

## Set up your mapping

The service loads `~/cursed_controls/mapping.yaml` on boot. You need to create this file.

### Option A — copy an example

```bash
# Wii Remote + Nunchuk (generic)
cp ~/cursed_controls/example_wiimote.yaml ~/cursed_controls/mapping.yaml

# Wii Remote + Nunchuk for Rocket League (sideways hold)
cp ~/cursed_controls/example_rocket_league.yaml ~/cursed_controls/mapping.yaml
```

Edit the file to adjust button mappings as needed.

### Option B — build interactively with the TUI mapper

Plug in or connect your controller first, then:

```bash
cd ~/cursed_controls
sudo .venv/bin/cursed-controls map mapping.yaml
```

The TUI walks you through each Xbox surface and asks you to press the matching button on your controller. It writes the YAML automatically.

### Option C — write it manually

See the [config format](README.md#config-format) in the README, or use an example as a reference.

---

## Start the service

```bash
sudo systemctl start cursed-controls

# Watch logs live
journalctl -u cursed-controls -f
```

The service also starts automatically on every boot.

To change which config is loaded without editing the service file:

```bash
echo 'CC_CONFIG=/home/casper/cursed_controls/example_rocket_league.yaml' \
    | sudo tee /etc/cursed-controls.env
sudo systemctl restart cursed-controls
```

---

## Manual setup (if not using install.sh)

### System packages

```bash
sudo apt update -y && sudo apt upgrade -y

# 64-bit OS (Pi Zero 2W, Pi 3, Pi 4, Pi 5)
sudo apt install -y git build-essential curl python3-venv bluetooth bluez \
    libtool autoconf automake m4 libudev-dev libncurses5-dev \
    linux-headers-rpi-v8

# 32-bit OS — replace linux-headers-rpi-v8 with:
#   armv7l → linux-headers-rpi-v7l
#   armv6l → linux-headers-rpi-v6
```

### Bluetooth

Allow Wiimotes to stay connected without full bonding:

```bash
sudo mkdir -p /etc/bluetooth
grep -q '\[Policy\]' /etc/bluetooth/input.conf 2>/dev/null \
    || echo '[Policy]' | sudo tee -a /etc/bluetooth/input.conf
echo 'ClassicBondedOnly=false' | sudo tee -a /etc/bluetooth/input.conf
sudo systemctl restart bluetooth
```

Allow evdev access without root:

```bash
echo 'KERNEL=="uinput", MODE="0666"' \
    | sudo tee /etc/udev/rules.d/99-cursed-controls.rules
sudo udevadm control --reload-rules
```

### USB OTG overlay

```bash
echo "dtoverlay=dwc2" | sudo tee -a /boot/firmware/config.txt
echo "dwc2" | sudo tee -a /etc/modules
sudo reboot
```

### raw-gadget kernel module

```bash
git clone https://github.com/xairy/raw-gadget.git ~/raw-gadget
make -C ~/raw-gadget/raw_gadget -j$(nproc)
```

### Rust + gadget library

```bash
# RUSTUP_IO_THREADS=1 prevents OOM on Pi Zero
export RUSTUP_IO_THREADS=1
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source ~/.cargo/env

cargo build --release \
    --manifest-path ~/cursed_controls/360-w-raw-gadget/Cargo.toml
```

### Python venv

```bash
cd ~/cursed_controls
python3 -m venv .venv
.venv/bin/pip install -e .
```

### Load kernel modules (after reboot)

```bash
bash ~/cursed_controls/init-raspbian.sh
```

---

## Power saving (Pi Zero 2W headless)

Add to `/boot/firmware/config.txt`:

```
dtoverlay=dwc2
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

---

## Known issues

- On 32-bit OS, replace `linux-headers-rpi-v8` with the variant matching your kernel (`rpi-v6`, `rpi-v7l`).
- `raw_gadget.ko` is built against your current kernel. After a kernel upgrade (`apt upgrade`), rebuild it: `make -C ~/raw-gadget/raw_gadget -j$(nproc)`.
