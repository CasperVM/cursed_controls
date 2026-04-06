#!/bin/bash
# install.sh — cursed-controls one-shot installer for Raspberry Pi OS
# Usage: bash install.sh
# Safe to re-run; each step skips if already complete.
set -euo pipefail

INSTALL_USER="$(whoami)"
INSTALL_HOME="$(eval echo ~"$INSTALL_USER")"
CC_DIR="$INSTALL_HOME/cursed_controls"
RAW_GADGET_DIR="$INSTALL_HOME/raw-gadget"
NEED_REBOOT=0

info() { echo "[cursed-controls] $*"; }
ok()   { echo "[cursed-controls] ✓ $*"; }
warn() { echo "[cursed-controls] ⚠ $*"; }

# ── 1. Detect architecture → pick linux-headers package ──────────────────────
ARCH="$(uname -m)"
case "$ARCH" in
    aarch64) HEADERS_PKG="linux-headers-rpi-v8" ;;
    armv7l)  HEADERS_PKG="linux-headers-rpi-v7l" ;;
    armv6l)  HEADERS_PKG="linux-headers-rpi-v6" ;;
    *)       warn "Unknown arch $ARCH — skipping linux-headers"; HEADERS_PKG="" ;;
esac

# ── 2. Show detected hardware (UDC is resolved at runtime via /sys/class/udc) ─
MODEL="$(cat /sys/firmware/devicetree/base/model 2>/dev/null | tr -d '\0' || echo 'unknown')"
info "Hardware: $MODEL ($ARCH)"
info "UDC will be auto-detected from /sys/class/udc/ at runtime"

# ── 3. System packages ────────────────────────────────────────────────────────
info "Installing system packages..."
sudo apt-get update -qq
PKGS=(git build-essential curl python3-venv bluetooth bluez
      libtool autoconf automake m4 libudev-dev libncurses5-dev)
[ -n "$HEADERS_PKG" ] && PKGS+=("$HEADERS_PKG")
sudo apt-get install -y -qq "${PKGS[@]}"
ok "System packages"

# ── 4. Bluetooth: ClassicBondedOnly=false ────────────────────────────────────
if ! grep -q "ClassicBondedOnly=false" /etc/bluetooth/input.conf 2>/dev/null; then
    info "Configuring BlueZ (ClassicBondedOnly=false)..."
    sudo mkdir -p /etc/bluetooth
    grep -q "\[Policy\]" /etc/bluetooth/input.conf 2>/dev/null \
        || echo "[Policy]" | sudo tee -a /etc/bluetooth/input.conf >/dev/null
    echo "ClassicBondedOnly=false" | sudo tee -a /etc/bluetooth/input.conf >/dev/null
    sudo systemctl restart bluetooth || true
fi
ok "Bluetooth config"

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

if ! grep -q "dtoverlay=dwc2" "$BOOT_CONFIG"; then
    info "Enabling USB OTG overlay in $BOOT_CONFIG..."
    echo "dtoverlay=dwc2" | sudo tee -a "$BOOT_CONFIG" >/dev/null
    NEED_REBOOT=1
fi
if ! grep -q "^dwc2$" /etc/modules; then
    echo "dwc2" | sudo tee -a /etc/modules >/dev/null
    NEED_REBOOT=1
fi
ok "USB OTG overlay"

# ── 7. raw-gadget kernel module ───────────────────────────────────────────────
if [ ! -d "$RAW_GADGET_DIR" ]; then
    info "Cloning raw-gadget..."
    git clone https://github.com/xairy/raw-gadget.git "$RAW_GADGET_DIR"
fi
if [ ! -f "$RAW_GADGET_DIR/raw_gadget/raw_gadget.ko" ]; then
    info "Building raw-gadget kernel module..."
    make -C "$RAW_GADGET_DIR/raw_gadget" -j"$(nproc)"
fi
ok "raw-gadget"

# ── 8. Rust toolchain ─────────────────────────────────────────────────────────
if ! command -v cargo &>/dev/null && [ ! -f "$INSTALL_HOME/.cargo/bin/cargo" ]; then
    info "Installing Rust (may take several minutes on Pi Zero)..."
    # RUSTUP_IO_THREADS=1 prevents OOM on low-RAM devices like Pi Zero
    export RUSTUP_IO_THREADS=1
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path
fi
# shellcheck disable=SC1090
source "$INSTALL_HOME/.cargo/env" 2>/dev/null || true
ok "Rust ($(cargo --version 2>/dev/null || echo 'path not yet active — open new shell'))"

# ── 9. cursed_controls repo ───────────────────────────────────────────────────
if [ ! -d "$CC_DIR/.git" ]; then
    info "Cloning cursed_controls..."
    git clone https://github.com/Berghopper/cursed_controls.git "$CC_DIR"
fi
cd "$CC_DIR"
git submodule update --init --recursive
ok "cursed_controls repo"

# ── 10. Build 360-w-raw-gadget shared library ─────────────────────────────────
SO_PATH="$CC_DIR/360-w-raw-gadget/target/release/libx360_w_raw_gadget.so"
if [ ! -f "$SO_PATH" ]; then
    info "Building 360-w-raw-gadget (may take several minutes on Pi Zero)..."
    RUSTUP_IO_THREADS=1 cargo build --release \
        --manifest-path "$CC_DIR/360-w-raw-gadget/Cargo.toml"
fi
ok "360-w-raw-gadget (.so built)"

# ── 11. Python venv ───────────────────────────────────────────────────────────
if [ ! -d "$CC_DIR/.venv" ]; then
    info "Creating Python venv..."
    python3 -m venv "$CC_DIR/.venv"
fi
"$CC_DIR/.venv/bin/pip" install -e "$CC_DIR" -q
ok "Python venv"

# ── 12. Write init-raspbian.sh with correct raw-gadget path ──────────────────
cat > "$CC_DIR/init-raspbian.sh" <<INITEOF
#!/bin/bash
sudo modprobe uinput
sudo modprobe hid-wiimote
(cd "$RAW_GADGET_DIR/raw_gadget" && sudo bash ./insmod.sh)
INITEOF
chmod +x "$CC_DIR/init-raspbian.sh"
ok "init-raspbian.sh"

# ── 13. Install systemd service ───────────────────────────────────────────────
info "Installing systemd service..."
sed \
    -e "s|__INSTALL_HOME__|$INSTALL_HOME|g" \
    -e "s|__INSTALL_USER__|$INSTALL_USER|g" \
    "$CC_DIR/cursed-controls.service" \
    | sudo tee /etc/systemd/system/cursed-controls.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable cursed-controls.service
ok "systemd service (cursed-controls.service enabled)"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  cursed-controls installed on $MODEL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Default config : $CC_DIR/mapping.yaml"
echo "  Change config  : echo 'CC_CONFIG=/path/to/config.yaml' | sudo tee /etc/cursed-controls.env"
echo "  View logs      : journalctl -u cursed-controls -f"
echo ""
if [ "$NEED_REBOOT" = "1" ]; then
    echo "  ⚠  REBOOT REQUIRED — USB OTG overlay was added to $BOOT_CONFIG"
    echo "     sudo reboot"
    echo ""
    echo "  After reboot the service will start automatically on boot."
else
    echo "  Start now: sudo systemctl start cursed-controls"
    echo ""
    echo "  On next boot the service will start automatically."
fi
echo ""
