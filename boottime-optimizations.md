# Boot Time Optimizations — Raspberry Pi Zero 2 W

Documented optimizations applied to minimize time-to-usable-state on a headless Pi Zero 2 W.
Target services: USB gadget, WiFi, SSH, cursed-controls web UI.

## Results

| Milestone | Before | After |
|---|---|---|
| Total boot | 23.1s | ~10.2s |
| Userspace (multi-user.target) | 18.2s | ~6.5s |
| USB gadget ready | — | ~5.5s from power-on |
| SSH available | ~18s | ~6.5s from power-on |

Hardware: Pi Zero 2 W, SanDisk Ultra SD card, powered via USB2 (500mA).

---

## What's happening at each second (after optimization)

```
0.0s  Power on
3.5s  Kernel hands off to systemd
4.6s  SD card partitions detected (MMC hardware init)
5.1s  Filesystems mounted, tmpfiles set up
5.1s  basic.target reached
5.5s  cursed-controls up — USB gadget active
6.3s  WiFi chipset firmware loaded, wpa_supplicant fires
6.5s  SSH ready
7-8s  DHCP lease obtained, web UI reachable
```

---

## Optimizations

### 1. Disable systemd-networkd-wait-online

**What it does:** Blocks `network-online.target` until the network has a full IP and routing.
Most services only need `network.target` (stack initialized), not full connectivity.
This service is the single most common boot blocker on Pi setups.

```bash
sudo systemctl mask systemd-networkd-wait-online.service
```

**Risk:** Services that explicitly `After=network-online.target` (e.g. apt timers) will
start before the network is fully up. For headless appliances this is almost always fine.

---

### 2. Disable and mask cloud-init

**What it does:** cloud-init runs 4 staged services at every boot to apply cloud provisioning
config. On Raspberry Pi OS it seeds from `/boot/firmware/user-data`, which ships as an
all-comments template doing nothing. It was adding ~6s to the critical chain and injecting
`After=cloud-init-network.service` into SSH, blocking it.

```bash
# Disable via the official mechanism
sudo touch /etc/cloud/cloud-init.disabled

# Mask all stages so they can't be started even if wanted
sudo systemctl mask \
  cloud-init-main.service \
  cloud-init-local.service \
  cloud-init-network.service \
  cloud-config.service \
  cloud-final.service \
  cloud-init-hotplugd.socket \
  cloud-init.target \
  cloud-config.target
```

**Risk:** If you actually use cloud-init for first-boot setup (SSH keys, user creation,
hostname, etc.) this will break that. On a Pi used as a fixed appliance it's safe.
Revert with `sudo rm /etc/cloud/cloud-init.disabled` and unmask the services.

---

### 3. Replace NetworkManager with systemd-networkd + wpa_supplicant

**What it does:** NetworkManager is a heavy-weight network manager taking ~5s to declare
itself up. `systemd-networkd` + `wpa_supplicant@<iface>` is a lightweight alternative
that reaches `network.target` in under 1s on a single-interface WiFi setup.

**Step 1 — Write wpa_supplicant config** (replace with your network details):

```bash
sudo tee /etc/wpa_supplicant/wpa_supplicant-wlan0.conf > /dev/null << 'EOF'
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=0
country=NL

network={
    ssid="YourNetworkName"
    psk="YourPassword"
    key_mgmt=WPA-PSK
    priority=10
}

network={
    ssid="FallbackNetwork"
    psk="FallbackPassword"
    key_mgmt=WPA-PSK
    priority=5
}
EOF
sudo chmod 600 /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
```

> **Important:** Always quote `ssid` and `psk` values. Without quotes, special characters
> like `#` are treated as comments and silently truncate your password.

> **`update_config=0`** prevents wpa_supplicant from writing back to the config file at
> runtime (e.g. caching BSSID info). Set to `1` only if you use `wpa_cli` to add networks
> on the fly. With `0`, the SD card is never written during normal WiFi operation.

**Step 2 — Write systemd-networkd config:**

```bash
sudo mkdir -p /etc/systemd/network
sudo tee /etc/systemd/network/10-wlan0.network > /dev/null << 'EOF'
[Match]
Name=wlan0

[Network]
DHCP=yes
IPv6AcceptRA=yes

[DHCPv4]
RouteMetric=600
UseDNS=yes
UseDomains=yes

[DHCPv6]
RouteMetric=600
EOF
```

**Step 3 — Make resolv.conf static** (networkd without systemd-resolved doesn't write it):

```bash
sudo tee /etc/resolv.conf > /dev/null << 'EOF'
nameserver <your-router-ip>
nameserver 8.8.8.8
nameserver 8.8.4.4
search lan
EOF
```

**Step 4 — Enable new stack, disable old:**

```bash
# Enable
sudo systemctl enable systemd-networkd wpa_supplicant@wlan0

# Disable NetworkManager and ModemManager
sudo systemctl disable NetworkManager NetworkManager-dispatcher wpa_supplicant
sudo systemctl mask ModemManager
```

**Step 5 — Reboot** (do not stop NM before rebooting — your current SSH session will drop).

**Risk:** If the wpa_supplicant config has any error (wrong password, bad syntax, missing
quotes around special characters) the Pi will have no WiFi and you'll need SD card access
to fix it. Test your config carefully before rebooting. The standalone `wpa_supplicant.service`
must be disabled to avoid conflicting with `wpa_supplicant@wlan0.service`.

---

### 4. Disable unnecessary services

Services that add boot time and are not needed on a headless appliance Pi:

```bash
# AppArmor — ships with no active profiles on Pi OS, loads and does nothing
sudo systemctl disable apparmor

# Console keyboard and font setup — not needed headless
sudo systemctl disable keyboard-setup console-setup

# ext4 online metadata check — runs at every boot, only useful for active scrubbing
sudo systemctl mask e2scrub_reap

# ModemManager — probes serial ports for LTE modems; Pi Zero 2 W has none.
# Also interferes with Bluetooth UART initialization.
sudo systemctl mask ModemManager
```

**Risk:** Low. AppArmor, keyboard-setup and console-setup are genuinely unused on headless.
e2scrub_reap can be unmasked if you want periodic ext4 scrubbing (the timer still works,
just not the every-boot activation).

---

### 5. Disable GPU/DRM stack

**What it does:** `dtoverlay=vc4-kms-v3d` in `config.txt` loads the full Mesa/KMS GPU
stack (5+ kernel modules, ~313ms). On a headless Pi with no display this is wasted time
and memory.

In `/boot/firmware/config.txt`, remove or do not include:
```
dtoverlay=vc4-kms-v3d
max_framebuffers=2
disable_fw_kms_setup=1
```

**Risk:** If you ever attach an HDMI display and want a desktop, you'll need to add these
back. For headless use there is no downside.

---

### 6. Skip fsck on boot

**What it does:** Two separate fsck skips:

**a) Kernel parameter** — skips fsck on the root ext4 partition:

In `/boot/firmware/cmdline.txt`, replace `fsck.repair=yes` with `fsck.mode=skip`. While
editing this file, also add `quiet` to suppress verbose kernel log output during boot
(minor improvement, cleaner serial output):

```
... fsck.mode=skip quiet rootwait ...
```

**b) fstab passno** — stops systemd from generating a fsck unit for the `/boot/firmware`
FAT32 partition:

In `/etc/fstab`, set the 6th field (fsck pass) for the boot partition to `0`:
```
PARTUUID=xxxx-01  /boot/firmware  vfat  defaults  0  0
                                                      ^
                                                      was 2, now 0
```

**Risk:** If the Pi loses power mid-write to either partition, corruption will go undetected
until it causes visible errors. For a stable deployment where you control firmware updates
this is acceptable. If you frequently pull power without clean shutdown, leave fsck enabled.

---

### 7. Move kernel module loading out of app startup

**What it does:** If your service loads kernel modules in `ExecStartPre`, those loads happen
serially, blocking the app. Moving them to `modules-load.d` makes systemd load them in
parallel during `sysinit.target`, well before your service starts.

For cursed-controls specifically, `init-raspbian.sh` was loading `uinput`, `hid-wiimote`,
`udc_core`, and `raw_gadget` at service start time. `dwc2` and `libcomposite` were
also being modprobed there despite already being loaded via `modules-load=dwc2,libcomposite`
in `cmdline.txt` (redundant).

**Step 1 — Install raw_gadget as a proper system module** (it's out-of-tree, so not in the
kernel tree by default):

```bash
sudo mkdir -p /lib/modules/$(uname -r)/extra
sudo cp ~/raw-gadget/raw_gadget/raw_gadget.ko /lib/modules/$(uname -r)/extra/
sudo depmod -a

# Verify it's found:
sudo modinfo raw_gadget | grep -E 'filename|vermagic'
```

The `vermagic` field must match `uname -r` exactly — if you update the kernel, rebuild
the module and repeat this step.

**Step 2 — Create a modules-load.d config:**

```bash
sudo tee /etc/modules-load.d/cursed-controls.conf > /dev/null << 'EOF'
uinput
hid-wiimote
udc_core
raw_gadget
EOF
```

These now load during `systemd-modules-load.service` at `sysinit.target`, in parallel
with other early boot work, instead of blocking your service start.

**Step 3 — Replace ExecStartPre in the service unit** with inlined commands (the module
loads are gone; only the two fast sysfs operations remain):

```ini
ExecStartPre=-/usr/sbin/rfkill unblock bluetooth
ExecStartPre=/bin/sh -c 'echo 1 > /sys/module/bluetooth/parameters/disable_ertm'
```

The `init-raspbian.sh` script has an `lsmod` check and will safely skip the raw_gadget
insmod if the module is already loaded — so if you apply only steps 1–2 without step 3,
the script becomes a fast no-op for module loading and still works correctly.

**Risk:** Module load ordering. `systemd-modules-load.service` completes during
`sysinit.target`, before `basic.target`, which is before most user services — so there is
no race in practice. The main risk is kernel updates invalidating the installed `.ko`; pin
your kernel or add the reinstall step to your update process.

---

### 8. Decouple app startup from network if not required

**What it does:** If your service does work that doesn't need a network connection (USB
gadget, hardware I/O, local processing), don't block it on `network.target`. Change
`After=network.target` to `After=basic.target` in the unit file. The service starts as
soon as the system is initialized, not after the WiFi stack is ready.

For `cursed-controls-web.service` specifically, the original unit had:

```ini
[Unit]
After=network.target bluetooth.target
Wants=bluetooth.target
```

Changed to:

```ini
[Unit]
After=basic.target
```

`Wants=bluetooth.target` was also removed — Bluetooth still starts (it's enabled
separately), it just no longer blocks the service. The app handles a delayed BT connection
gracefully. This moved cursed-controls startup from ~6.7s (after WiFi stack) to ~5.3s
(after basic system init), putting it before the WiFi chipset has even loaded its firmware.

For a web UI that binds to `0.0.0.0`, binding works without a DHCP lease — the port is
open immediately, it just isn't reachable until the lease arrives in the background.

**Risk:** If your app genuinely needs a network address at startup (outbound connections,
hostname resolution), this will cause startup failures. Use `Restart=on-failure` +
`RestartSec=5` as a safety net so it retries when network is available.

---

### 9. force_turbo and CPU frequency

**What it does:** By default the Pi uses the `ondemand` CPU governor, scaling between
600MHz and 1000MHz. During early boot (before load is detected), the CPU may run at
600MHz, slowing all initialization. `force_turbo=1` in `config.txt` locks the CPU at
maximum frequency from the first firmware instruction.

Note: the standard Linux kernel parameter `cpufreq.default_governor=performance` in
`cmdline.txt` does **not** work on Pi — the `raspberrypi-cpufreq` driver ignores it.
`force_turbo=1` in `config.txt` is the only reliable method and operates at the firmware
level before the kernel boots.

In `/boot/firmware/config.txt`:
```
arm_boost=1
force_turbo=1
```

**Risk:** On USB2 power (500mA / 2.5W), the Pi Zero 2 W at full load draws close to the
limit. In practice it's fine (normal operating draw is well under 2.5W), but if you see
under-voltage warnings (`vcgencmd get_throttled` returning non-zero), revert this.
`force_turbo=1` also disables thermal throttling — on a Zero 2 W without a heatsink in a
warm enclosure this could theoretically cause issues, though in practice the chip is
efficient enough that it's rarely a concern.

---

### 10. SD card overclock

**What it does:** The SDHOST MMC controller defaults to 50MHz. On quality SD cards it can
be pushed higher, reducing kernel load time and SD card detection latency.

In `/boot/firmware/config.txt` (in the `[all]` section):
```
dtparam=sd_overclock=100
```

The Pi Zero 2 W's controller runs from a 400MHz base clock with integer dividers, giving
achievable steps of 50MHz → 100MHz → 200MHz. 108MHz or other intermediate values will
silently snap to 100MHz.

**Tested stable at 100MHz** on a SanDisk Ultra (manufacturer ID 0x03). Saved ~630ms off
SD card detection time.

**200MHz is not recommended** for mid-range cards (Ultra, Endurance). It may work but
risks silent data corruption. The Extreme Pro line handles it more reliably.

**Risk:** If the card can't handle the clock speed, the Pi will fail to boot or corrupt
the filesystem. If it fails to boot, reduce the value via SD card access on another machine.
Start at 100MHz and only go higher if you have a card rated for it.

---

### 11. Journal storage — persistent for debugging, volatile for production

By default the systemd journal is stored in RAM (`Storage=volatile`) and lost on reboot.
For debugging boot failures, enable persistent storage temporarily:

```bash
sudo mkdir -p /var/log/journal
# With Storage=auto (default), the directory existing is enough to trigger persistence
```

Read logs from the previous boot:
```bash
journalctl --boot -1
```

Once the system is stable, revert to volatile to eliminate the only active SD card
writer during normal operation:

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/volatile.conf > /dev/null << 'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=20M
EOF
sudo rm -rf /var/log/journal
```

With `Storage=volatile` and `update_config=0` in wpa_supplicant, the SD card is
effectively read-only during normal operation — safe for frequent power pulls.

---

## Diagnostic commands

```bash
# Overall boot time breakdown
systemd-analyze time

# Per-service time (sorted by slowest)
systemd-analyze blame

# Full dependency chain to default target
systemd-analyze critical-chain

# Chain for a specific service
systemd-analyze critical-chain ssh.service

# Check for CPU/power throttling
vcgencmd get_throttled   # 0x0 = no issues

# Check actual SD card clock
sudo cat /sys/kernel/debug/mmc0/ios | grep clock

# Check CPU frequency and governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
```

---

## What we didn't do (and why)

**Static IP** — eliminates DHCP round trip (100–400ms). Trade-off is needing to manage
a fixed IP assignment. Worth doing if you need the last few hundred milliseconds.

**SSH socket activation** — systemd holds port 22 open immediately; SSH daemon starts on
first connection. Shifts the ~700ms SSH startup from boot time to first-connection latency.
Not a net win if you connect immediately after boot.

**Custom kernel** — stripping unused drivers from the kernel config can shave 1s+ off
kernel boot time. Significant effort, breaks with upstream kernel updates.

**initramfs optimization** — moving WiFi firmware into the initramfs could reduce the
brcmfmac initialization time (~2.5s in userspace). Complex to set up and maintain.
