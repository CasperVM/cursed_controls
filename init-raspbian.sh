sudo modprobe uinput
sudo modprobe hid-wiimote

# Unblock Bluetooth (may be soft-blocked by rfkill on fresh boot)
sudo rfkill unblock bluetooth 2>/dev/null || true

# Xbox One BT controllers disconnect immediately if ERTM is enabled
echo 1 | sudo tee /sys/module/bluetooth/parameters/disable_ertm > /dev/null

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
INSTALL_HOME="$(dirname "$SCRIPT_DIR")"
RAW_GADGET_DIR="${RAW_GADGET_DIR:-$INSTALL_HOME/raw-gadget}"
sudo modprobe dwc2 2>/dev/null || true
sudo modprobe libcomposite 2>/dev/null || true
lsmod | grep -q raw_gadget || (cd "$RAW_GADGET_DIR/raw_gadget" && sudo bash ./insmod.sh)
