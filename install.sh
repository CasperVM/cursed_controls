#!/bin/bash
# install.sh — cursed-controls one-shot installer for Raspberry Pi OS
#
# One-liner (recommended):
#   curl -fsSL https://raw.githubusercontent.com/CasperVM/cursed_controls/main/install.sh | bash
#
# Headless appliance (faster boot, lower idle power):
#   curl -fsSL https://raw.githubusercontent.com/CasperVM/cursed_controls/main/install.sh | bash -s -- --headless-fast-boot
#
# Local usage:
#   bash install.sh [--headless-fast-boot]
#
# Safe to re-run; each step skips if already complete.
set -euo pipefail

HEADLESS_FAST_BOOT=0
for arg in "$@"; do
    case "$arg" in
        --headless-fast-boot) HEADLESS_FAST_BOOT=1 ;;
        *)
            echo "Usage: bash install.sh [--headless-fast-boot]" >&2
            exit 1
            ;;
    esac
done

INSTALL_USER="$(whoami)"
INSTALL_HOME="$(eval echo ~"$INSTALL_USER")"
CC_DIR="$INSTALL_HOME/cursed_controls"
RAW_GADGET_DIR="$INSTALL_HOME/raw-gadget"
XWIIMOTE_DIR="$INSTALL_HOME/xwiimote"
RAW_GADGET_KERNEL_STAMP="$RAW_GADGET_DIR/raw_gadget/.kernel-release"
WEB_SERVICE_NAME="cursed-controls-web.service"
UV_BIN="$INSTALL_HOME/.local/bin/uv"
PYTHON_REQUEST="$(cat "$CC_DIR/.python-version" 2>/dev/null || echo "3.13")"
NEED_REBOOT=0

info() { echo "[cursed-controls] $*"; }
ok()   { echo "[cursed-controls] ✓ $*"; }
warn() { echo "[cursed-controls] ⚠ $*"; }

ensure_boot_config_line() {
    local line="$1"
    grep -qxF "$line" "$BOOT_CONFIG" 2>/dev/null || {
        echo "$line" | sudo tee -a "$BOOT_CONFIG" >/dev/null
        NEED_REBOOT=1
    }
}

# ── 1. Detect architecture → pick linux-headers package ──────────────────────
ARCH="$(uname -m)"
case "$ARCH" in
    aarch64) HEADERS_PKG="linux-headers-rpi-v8" ;;
    armv7l)  HEADERS_PKG="linux-headers-rpi-v7l" ;;
    armv6l)  HEADERS_PKG="linux-headers-rpi-v6" ;;
    *)       warn "Unknown arch $ARCH — skipping linux-headers"; HEADERS_PKG="" ;;
esac
BUILD_JOBS="$(nproc)"
[ "$BUILD_JOBS" -gt 4 ] && BUILD_JOBS=4

# ── 2. Show detected hardware (UDC is resolved at runtime via /sys/class/udc) ─
MODEL="$(cat /sys/firmware/devicetree/base/model 2>/dev/null | tr -d '\0' || echo 'unknown')"
info "Hardware: $MODEL ($ARCH)"
info "UDC will be auto-detected from /sys/class/udc/ at runtime"

# ── 3. System packages ────────────────────────────────────────────────────────
info "Installing system packages..."
sudo apt-get update -qq
PKGS=(git build-essential curl python3-venv python3-dev bluetooth bluez
      libtool autoconf automake m4 libudev-dev libncurses5-dev)
[ -n "$HEADERS_PKG" ] && PKGS+=("$HEADERS_PKG")
sudo apt-get install -y -qq "${PKGS[@]}"
sudo apt-get clean
sudo rm -rf /var/lib/apt/lists/*
ok "System packages"

# ── 4. Bluetooth: ClassicBondedOnly=false ────────────────────────────────────
# BlueZ reads ClassicBondedOnly from [General] in input.conf (not [Policy]).
# Uncomment the existing commented line in-place; append only if not present at all.
if ! grep -q "^ClassicBondedOnly=false" /etc/bluetooth/input.conf 2>/dev/null; then
    info "Configuring BlueZ (ClassicBondedOnly=false)..."
    sudo mkdir -p /etc/bluetooth
    if grep -q "^#ClassicBondedOnly" /etc/bluetooth/input.conf 2>/dev/null; then
        sudo sed -i 's/^#ClassicBondedOnly=.*/ClassicBondedOnly=false/' /etc/bluetooth/input.conf
    else
        printf '\n[General]\nClassicBondedOnly=false\n' | sudo tee -a /etc/bluetooth/input.conf >/dev/null
    fi
    sudo systemctl restart bluetooth || true
fi
ok "Bluetooth config"

# ── 4b. xwiimote (for Wiimote rumble + LEDs) ─────────────────────────────────
if ! ldconfig -p 2>/dev/null | grep -q "libxwiimote"; then
    if [ ! -d "$XWIIMOTE_DIR" ]; then
        info "Cloning xwiimote..."
        if ! git clone https://github.com/xwiimote/xwiimote.git "$XWIIMOTE_DIR"; then
            warn "xwiimote clone failed — libxwiimote not available, Wiimote rumble/LEDs will be disabled"
        fi
    fi
    if [ -d "$XWIIMOTE_DIR" ] && ! ldconfig -p 2>/dev/null | grep -q "libxwiimote"; then
        info "Building xwiimote..."
        if (
            cd "$XWIIMOTE_DIR"
            info "Patching xwiimote for modern 32-bit input headers..."
            python3 - <<'PY'
from pathlib import Path

path = Path("lib/core.c")
text = path.read_text()
helper = """static void copy_input_event_time(struct timeval *dst, const struct input_event *src)
{
\tdst->tv_sec = src->input_event_sec;
\tdst->tv_usec = src->input_event_usec;
}

"""
needle = "/* table to convert interface to name */\n"
old = "memcpy(&ev->time, &input.time, sizeof(struct timeval));"
new = "copy_input_event_time(&ev->time, &input);"

if helper not in text:
    if needle not in text:
        raise SystemExit("xwiimote patch failed: insertion point missing")
    text = text.replace(needle, helper + needle, 1)

if old in text:
    text = text.replace(old, new)

path.write_text(text)
PY
            ./autogen.sh
            make -j"$BUILD_JOBS"
            sudo make install
        ); then
            sudo ldconfig
        else
            warn "xwiimote build failed — libxwiimote not available, Wiimote rumble/LEDs will be disabled"
        fi
    fi
fi
ok "xwiimote"

# ── 5. udev rules (uinput readable without root) ─────────────────────────────
UDEV_FILE="/etc/udev/rules.d/99-cursed-controls.rules"
UDEV_RULE='KERNEL=="uinput", MODE="0666"'
if ! grep -qF "$UDEV_RULE" "$UDEV_FILE" 2>/dev/null; then
    info "Installing udev rules..."
    echo "$UDEV_RULE" | sudo tee "$UDEV_FILE" >/dev/null
    sudo udevadm control --reload-rules
fi
ok "udev rules"

# ── 6. USB OTG overlay (dwc2) ─────────────────────────────────────────────────
# Try /boot/firmware/config.txt (newer Pi OS), fall back to /boot/config.txt
BOOT_CONFIG="/boot/firmware/config.txt"
[ -f "$BOOT_CONFIG" ] || BOOT_CONFIG="/boot/config.txt"

if grep -qxF "dtoverlay=dwc2,dr_mode=host" "$BOOT_CONFIG" 2>/dev/null; then
    info "Switching USB overlay from host mode to gadget mode in $BOOT_CONFIG..."
    sudo sed -i 's/^dtoverlay=dwc2,dr_mode=host$/dtoverlay=dwc2/' "$BOOT_CONFIG"
    NEED_REBOOT=1
fi
if ! grep -qxF "dtoverlay=dwc2" "$BOOT_CONFIG"; then
    info "Enabling USB OTG overlay in $BOOT_CONFIG..."
    ensure_boot_config_line "dtoverlay=dwc2"
fi
if ! grep -q "^dwc2$" /etc/modules; then
    echo "dwc2" | sudo tee -a /etc/modules >/dev/null
    NEED_REBOOT=1
fi
if [ "$HEADLESS_FAST_BOOT" = "1" ]; then
    info "Applying headless fast-boot tuning in $BOOT_CONFIG..."
    for line in \
        "hdmi_blanking=1" \
        "hdmi_ignore_hotplug=1" \
        "camera_auto_detect=0" \
        "display_auto_detect=0" \
        "dtparam=audio=off" \
        "gpu_mem=16" \
        "dtparam=act_led_trigger=none" \
        "dtparam=act_led_activelow=on"
    do
        ensure_boot_config_line "$line"
    done
    ok "Headless fast-boot tuning"
fi
ok "USB OTG overlay"

# ── 7. raw-gadget kernel module ───────────────────────────────────────────────
KERNEL_RELEASE="$(uname -r)"
RAW_GADGET_KO="$RAW_GADGET_DIR/raw_gadget/raw_gadget.ko"
if [ ! -d "$RAW_GADGET_DIR" ]; then
    info "Cloning raw-gadget..."
    git clone https://github.com/xairy/raw-gadget.git "$RAW_GADGET_DIR"
fi
if [ ! -f "$RAW_GADGET_KO" ] || [ ! -f "$RAW_GADGET_KERNEL_STAMP" ] || \
   [ "$(cat "$RAW_GADGET_KERNEL_STAMP" 2>/dev/null)" != "$KERNEL_RELEASE" ]; then
    info "Building raw-gadget kernel module for $KERNEL_RELEASE..."
    make -C "$RAW_GADGET_DIR/raw_gadget" -j"$BUILD_JOBS"
    printf '%s\n' "$KERNEL_RELEASE" > "$RAW_GADGET_KERNEL_STAMP"
fi
ok "raw-gadget"

# ── 8. Rust toolchain ─────────────────────────────────────────────────────────
if ! command -v cargo &>/dev/null && [ ! -f "$INSTALL_HOME/.cargo/bin/cargo" ]; then
    info "Installing Rust (may take several minutes on Pi Zero)..."
    # RUSTUP_IO_THREADS=1 prevents OOM on low-RAM devices like Pi Zero
    export RUSTUP_IO_THREADS=1
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path --profile minimal
fi
# shellcheck disable=SC1090
source "$INSTALL_HOME/.cargo/env" 2>/dev/null || true
ok "Rust ($(cargo --version 2>/dev/null || echo 'path not yet active — open new shell'))"

# ── 9. cursed_controls repo ───────────────────────────────────────────────────
if [ ! -d "$CC_DIR" ]; then
    info "Cloning cursed_controls..."
    git clone https://github.com/CasperVM/cursed_controls.git "$CC_DIR"
fi
cd "$CC_DIR"
if [ -d "$CC_DIR/.git" ]; then
    git submodule sync --recursive
    git submodule update --init --recursive
else
    info "Using existing local checkout at $CC_DIR"
fi
ok "cursed_controls repo"

# ── 10. Build 360-w-raw-gadget shared library ─────────────────────────────────
SO_PATH="$CC_DIR/360-w-raw-gadget/target/release/libx360_w_raw_gadget.so"
if [ ! -f "$SO_PATH" ]; then
    info "Building 360-w-raw-gadget (may take several minutes on Pi Zero)..."
    RUSTUP_IO_THREADS=1 cargo build --release \
        -j "$BUILD_JOBS" \
        --manifest-path "$CC_DIR/360-w-raw-gadget/Cargo.toml"
fi
ok "360-w-raw-gadget (.so built)"

# ── 11. Python env via uv ─────────────────────────────────────────────────────
if [ ! -x "$UV_BIN" ] && ! command -v uv &>/dev/null; then
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
[ -x "$UV_BIN" ] || UV_BIN="$(command -v uv)"
if [ ! -d "$CC_DIR/.venv" ]; then
    info "Creating Python env with uv..."
    "$UV_BIN" venv --python "$PYTHON_REQUEST" "$CC_DIR/.venv"
fi
if [ "$ARCH" = "armv6l" ]; then
    info "Preinstalling wheel-backed ARMv6 packages from piwheels..."
    "$UV_BIN" pip install \
        --python "$CC_DIR/.venv/bin/python" \
        --index-url https://www.piwheels.org/simple \
        evdev==1.9.2 \
        PyYAML==6.0.3 \
        pydantic-core==2.41.4
fi
info "Syncing Python dependencies with uv..."
"$UV_BIN" sync \
    --directory "$CC_DIR" \
    --python "$PYTHON_REQUEST" \
    --no-dev \
    --locked
ok "Python env"

# ── 12. Seed default mapping and prepare init script ──────────────────────────
if [ ! -f "$CC_DIR/mapping.yaml" ]; then
    info "Seeding default mapping from example_tv_remote.yaml..."
    cp "$CC_DIR/example_tv_remote.yaml" "$CC_DIR/mapping.yaml"
fi
ok "mapping.yaml"

sed \
    -e "s|__RAW_GADGET_DIR__|$RAW_GADGET_DIR|g" \
    "$CC_DIR/init-raspbian.sh" \
    > "$CC_DIR/init-raspbian.sh.tmp"
mv "$CC_DIR/init-raspbian.sh.tmp" "$CC_DIR/init-raspbian.sh"
chmod +x "$CC_DIR/init-raspbian.sh"
ok "init-raspbian.sh"

# ── 13. Install systemd service ───────────────────────────────────────────────
info "Installing systemd web service..."
sed \
    -e "s|__INSTALL_HOME__|$INSTALL_HOME|g" \
    "$CC_DIR/$WEB_SERVICE_NAME" \
    | sudo tee "/etc/systemd/system/$WEB_SERVICE_NAME" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable "$WEB_SERVICE_NAME"
ok "systemd service ($WEB_SERVICE_NAME enabled)"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  cursed-controls web UI installed on $MODEL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Default config : $CC_DIR/mapping.yaml"
echo "  Service        : $WEB_SERVICE_NAME"
echo "  View logs      : journalctl -u $WEB_SERVICE_NAME -f"
echo ""
if [ "$HEADLESS_FAST_BOOT" = "1" ]; then
    echo "  Headless fast-boot tuning was applied to $BOOT_CONFIG"
fi
echo "  Reboot now, then plug the Pi into USB."
echo "  After reboot the web UI will start automatically on boot."
echo ""
