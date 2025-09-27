#!/usr/bin/env python3

import asyncio
from dataclasses import dataclass, field
import sys
import time
from typing import Dict, Generator, List
import evdev
from evdev import ecodes
from evdev.ecodes import ABS
import os, subprocess, re

from pathlib import Path

from x360 import X360Surfaces


@dataclass
class InputDeviceMetadata:
    name: str  # device name
    phys_id: str  # phys attribute
    uniq: str  # uniq attribute
    event_path: str  # /dev/input/eventN
    event_real: str  # resolved real event path
    hid_syspath: str  # /sys/bus/hid/devices/...
    parent_uhid: str  # e.g. "0005:057E:0306.0011"
    is_composite: bool  # Is this a composite device?
    is_composite_parent: bool  # True if this is the main UHID device

    def __str__(self):
        prefix = ""
        # if self.parent_uhid:
        #     prefix += f"('{self.parent_uhid}'): "

        if self.phys_id:
            return f"{prefix}'{self.name}': {self.phys_id}"
        elif self.uniq:
            return f"{prefix}'{self.name}': {self.uniq}"
        return f"{prefix}'{self.name}': {self.event_path}"


def device_path_to_meta(device: evdev.InputDevice) -> InputDeviceMetadata:
    """
    Given /dev/input/eventN, return metadata including phys, uniq,
    HID sysfs path, and parent UHID handle.
    """
    event_path = str(device.path)
    event_sys = Path("/sys/class/input") / Path(event_path).name / "device"

    if not event_sys.exists():
        raise FileNotFoundError(f"sysfs path for {event_path} not found: {event_sys}")

    # Read phys and uniq (may be empty)
    phys_path = event_sys / "phys"
    uniq_path = event_sys / "uniq"

    phys = phys_path.read_text().strip() if phys_path.exists() else ""
    uniq = uniq_path.read_text().strip() if uniq_path.exists() else ""

    # Resolve the real sysfs path
    event_real = os.path.realpath(str(event_sys))

    # Find HID sysfs device
    hid_syspath = None
    hid_base = "/sys/bus/hid/devices"
    if os.path.isdir(hid_base):
        for entry in os.listdir(hid_base):
            hid_path = os.path.realpath(os.path.join(hid_base, entry))
            try:
                if os.path.commonpath([event_real, hid_path]) == hid_path:
                    hid_syspath = hid_path
                    break
            except ValueError:
                continue

    # Find parent UHID (if any), usually present for composite devices.
    split_sysfs_path = event_real.split("/")
    parent_uhid = None
    try:
        parent_uhid = split_sysfs_path[split_sysfs_path.index("uhid") + 1]
    except:
        pass

    # Determine if this is the main device under the UHID handle
    is_parent = False or not parent_uhid
    try:
        if parent_uhid:
            uhid_input_path = f"/sys/devices/virtual/misc/uhid/{parent_uhid}/input"
            # Sort to pick the first input node under UHID
            if os.path.isdir(uhid_input_path):
                inputs = sorted(os.listdir(uhid_input_path))
                main_input = inputs[0] if inputs else None
                if (
                    main_input
                    and os.path.realpath(os.path.join(uhid_input_path, main_input))
                    == event_real
                ):
                    is_parent = True
    except:
        pass

    return InputDeviceMetadata(
        is_composite=bool(parent_uhid),
        is_composite_parent=is_parent,
        name=device.name,
        phys_id=phys,
        uniq=uniq,
        event_path=event_path,
        event_real=event_real,
        hid_syspath=hid_syspath,
        parent_uhid=parent_uhid,
    )


@dataclass
class InputDevice:
    device: evdev.InputDevice
    meta: InputDeviceMetadata

    def __str__(self):
        return f"{self.meta}"


@dataclass
class InputDeviceParent(InputDevice):
    children: List[InputDevice] = field(default_factory=list)

    def add_child(self, child: InputDevice):
        self.children.append(child)

    def flatten(self) -> Generator[InputDevice, None, None]:
        yield self
        for child in self.children:
            yield child


def build_parent_device_tree():
    # map UHID or event_path to node
    parent_nodes: Dict[str, InputDeviceParent] = {}
    child_nodes: List[InputDevice] = []

    for d in map(evdev.InputDevice, evdev.list_devices()):
        meta = device_path_to_meta(d)
        if meta.is_composite_parent or not meta.parent_uhid:
            # parent node: key = UHID if composite, else event_path
            key = meta.parent_uhid if meta.is_composite_parent else meta.event_path
            parent_nodes[key] = InputDeviceParent(d, meta)
        else:
            child_nodes.append(InputDevice(d, meta))

    for child in child_nodes:
        parent = parent_nodes.get(child.meta.parent_uhid)
        if parent:
            parent.add_child(child)
            continue
        # No parent? -> add to parent list.
        parent_nodes[child.meta.event_path] = InputDeviceParent(
            child.device, child.meta
        )

    return list(parent_nodes.values())


@dataclass
class InputMapping:
    device_identifier: str
    # parent_identifier: str | None
    cap_type: int
    cap_code: int
    x360_out: X360Surfaces


class DeviceMenu:
    def __init__(self):
        self.parents = build_parent_device_tree()
        # flatten
        self.devices = [i for p in self.parents for i in p.flatten()]
        self.mapping = []

    def main_menu(self, last_input_err=False):
        while True:
            os.system("clear")
            if last_input_err:
                print("=====\nPlease choose a device number!\n=====")
            for idx, d in enumerate(self.devices):
                if not d.meta.is_composite_parent:
                    print(f"  ({idx}): {d}")
                    continue
                print(f"({idx}): {d}")

            try:
                mapping_idx_usr = int(input("Choose device for mapping: "))
                if mapping_idx_usr not in range(0, len(self.devices)):
                    self.main_menu(last_input_err=True)
                self.device_menu(mapping_idx_usr)
            except KeyboardInterrupt:
                sys.exit()
            # except:
            #     # FIXME properly catch
            #     self.main_menu(last_input_err=True)

    def device_menu(self, idx):
        os.system("clear")
        dev: evdev.InputDevice = self.devices[idx].device
        meta: InputDeviceMetadata = self.devices[idx].meta
        while True:
            print(f"Selected device:\n ({idx}): {self.devices[idx]}\n")
            print("Options:")
            print("(v): view mapping")
            print("(b): back")
            # Loop through capabilities.
            button_menu_list = []
            abs_menu_list = []

            for event_type, event_cap_list in dev.capabilities(verbose=True).items():
                event_type_name, event_type_code = event_type
                if event_type_code not in (ecodes.EV_ABS, ecodes.EV_KEY):
                    continue
                for i in event_cap_list:
                    # print(f"DEBUG {i}")
                    if event_type_code == ecodes.EV_ABS:
                        capability_info, capability_abs_info = i
                        capability_name, capability_code = capability_info
                        abs_menu_list.append(
                            (capability_name, capability_code, event_type_code)
                        )
                        continue
                    else:
                        capability_name, capability_code = i
                        button_menu_list.append(
                            (capability_name, capability_code, event_type_code)
                        )
            whole_menu = button_menu_list + abs_menu_list
            print("KEYS:")
            for jdx, i in enumerate(button_menu_list):
                capability_name, capability_code, event_type_code = i
                if event_type_code == ecodes.EV_KEY:
                    print(f" ({jdx}). {capability_name}")
            print("AXES:")
            for jdx, i in enumerate(abs_menu_list):
                capability_name, capability_code, event_type_code = i
                print(f" ({jdx+len(button_menu_list)}). {capability_name}")
            print()
            # try:
            inp_opt = input("Choose option: ")

            if inp_opt == "b":
                return
            elif inp_opt == "v":
                # FIXME
                print("Not implemented...")
                time.sleep(2)
            else:
                os.system("clear")
                to_map = whole_menu[int(inp_opt)]
                device_identifier = meta.uniq or meta.phys_id or meta.name

                for jdx, n in enumerate(list(X360Surfaces)):
                    print(f"({jdx}). {n.value[0]}")
                print()
                inp_opt_map = int(input("Select option: "))

                self.mapping.append(
                    InputMapping(
                        device_identifier=device_identifier,
                        cap_type=event_type_code,
                        cap_code=capability_code,
                        x360_out=X360Surfaces(list(X360Surfaces)[inp_opt_map].value[0]),
                    )
                )
                print(self.mapping)
                time.sleep(1)

            # except e as Error:
            #     print(e)
            #     time.sleep(12)

            #     # FIXME properly catch
            #     return


# Example usage
async def main():
    DeviceMenu().main_menu()


if __name__ == "__main__":
    asyncio.run(main())
