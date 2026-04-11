sudo modprobe uinput
sudo modprobe hid-wiimote

# Xbox One BT controllers disconnect immediately if ERTM is enabled
echo 1 | sudo tee /sys/module/bluetooth/parameters/disable_ertm > /dev/null

lsmod | grep -q raw_gadget || (cd /home/casper/raw-gadget/raw_gadget && sudo bash ./insmod.sh)
