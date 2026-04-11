#!/usr/bin/env python3

import asyncio
import ctypes
from dataclasses import dataclass, field
from enum import Enum
import json

import sys

import time
from typing import Dict, Generator, List
import evdev
from evdev import ecodes
import os
from pathlib import Path
from x360 import Axis, BitPackedButton, JoystickAxis, X360Surfaces, XboxControllerState


### C MAPPINGS

# Xbox Emu
# Path to shared lib
LIB_PATH = os.path.join("360-w-raw-gadget", "lib360wgadget.so")

# Load the shared library
lib = ctypes.CDLL(LIB_PATH)

# Declare function signatures
lib.init_360_gadget.argtypes = [ctypes.c_bool, ctypes.c_int]
lib.init_360_gadget.restype = ctypes.c_int

lib.close_360_gadget.argtypes = [ctypes.c_int]
lib.close_360_gadget.restype = None

lib.send_to_ep.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_ubyte),
    ctypes.c_size_t,
]
lib.send_to_ep.restype = ctypes.c_bool


# Python wrappers
def init_360_gadget(await_endpoint_availability: bool, n_interfaces: int) -> int:
    return lib.init_360_gadget(await_endpoint_availability, n_interfaces)


def close_360_gadget(fd: int) -> None:
    lib.close_360_gadget(fd)


def send_to_ep(fd: int, n: int, data: bytes) -> bool:
    arr = (ctypes.c_ubyte * len(data))(*data)
    return lib.send_to_ep(fd, n, arr, len(data))


###


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
        if self.phys_id:
            return f"'{self.name}': {self.phys_id}"
        elif self.uniq:
            return f"'{self.name}': {self.uniq}"
        return f"'{self.name}': {self.event_path}"

    def first_identifier(self):
        """
        Returns first possible identifier
        """
        return self.uniq or self.phys_id or self.name


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
    except ValueError:
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
    except OSError:
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


# Mapping strategies/conversion classes
class ButtonToJoystickAxis(Enum):
    MAX_OUT = "MAX_OUT"
    MIN_OUT = "MIN_OUT"
    MIN_TO_MAX = "MIN_TO_MAX"  # No button press = MIN
    MAX_TO_MIN = "MAX_TO_MIN"  # No button press = MAX


@dataclass
class InputMapping:
    device_identifier: str
    # parent_identifier: str | None
    cap_type: int
    cap_code: int
    x360_out: X360Surfaces
    button_to_joystick: ButtonToJoystickAxis | None = None
    input_axis_absinfo: evdev.AbsInfo | None = None

    def __str__(self):
        return f"{self.device_identifier}-{self.cap_type}-{self.cap_code}-{self.x360_out.value[0]}"

    def to_dict(self):
        return {
            "device_identifier": self.device_identifier,
            "cap_type": self.cap_type,
            "cap_code": self.cap_code,
            "x360_out": self.x360_out.value[0],
            "button_to_joystick": self.button_to_joystick.value,
            "input_axis_absinfo": None,  # FIXME...
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InputMapping":
        bj = d.get("button_to_joystick")
        return cls(
            device_identifier=d["device_identifier"],
            cap_type=d["cap_type"],
            cap_code=d["cap_code"],
            x360_out=X360Surfaces[d["x360_out"]],
            button_to_joystick=ButtonToJoystickAxis(bj) if bj is not None else None,
            input_axis_absinfo=None,
        )


class DeviceMenu:
    def __init__(self):
        self.parents = build_parent_device_tree()
        # flatten
        self.devices = [i for p in self.parents for i in p.flatten()]
        self.mapping = {}

    def mapping_to_file(self, outfile="out.json"):
        all_mappings = [m.to_dict() for m in self.mapping.values()]
        with open(outfile, "w") as f:
            f.write(json.dumps(all_mappings))

    def main_menu(self, last_input_err=False):
        while True:
            os.system("clear")
            if last_input_err:
                print("=====\nPlease choose a device number!\n=====")

            print("Options:")
            print("(v): view mapping")
            print()

            for idx, d in enumerate(self.devices):
                if not d.meta.is_composite_parent:
                    print(f"  ({idx}): {d}")
                    continue
                print(f"({idx}): {d}")

            try:
                inp_usr = input("Choose device for mapping: ")
                if inp_usr == "v":
                    self.view_mapping()
                    continue
                mapping_idx_usr = int(inp_usr)
                if mapping_idx_usr not in range(0, len(self.devices)):
                    self.main_menu(last_input_err=True)
                self.device_menu(mapping_idx_usr)
            except KeyboardInterrupt:
                sys.exit()
            # except:
            #     # FIXME properly catch
            #     self.main_menu(last_input_err=True)

    def device_menu(self, idx):
        dev: evdev.InputDevice = self.devices[idx].device
        meta: InputDeviceMetadata = self.devices[idx].meta
        while True:
            os.system("clear")
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
                print(f" ({jdx + len(button_menu_list)}). {capability_name}")
            print()
            # try:
            inp_opt = input("Choose option: ")

            if inp_opt == "b":
                return
            elif inp_opt == "v":
                self.view_mapping()
                continue
            else:
                to_map = whole_menu[int(inp_opt)]
                device_identifier = meta.uniq or meta.phys_id or meta.name

                x_out_mapping = self.xbox_mapping_view()
                mapping = InputMapping(
                    device_identifier=device_identifier,
                    cap_type=to_map[2],
                    cap_code=to_map[1],
                    x360_out=x_out_mapping,
                )
                self.mapping[str(mapping)] = mapping
                self.mapping_to_file()

    def xbox_mapping_view(self):
        os.system("clear")
        for idx, n in enumerate(list(X360Surfaces)):
            print(f"({idx}). {n.value[0]}")
        print()
        inp_opt_map = int(input("Select option: "))
        return X360Surfaces(list(X360Surfaces)[inp_opt_map])

    def view_mapping(self):
        while True:
            os.system("clear")
            print("Options:")
            print("(b): back")
            print()
            # Print out mapping
            for m in self.mapping.values():
                m: InputMapping
                print("---")
                print(f"name (device): {m.device_identifier}")
                print(f"name (in): {ecodes.bytype[m.cap_type][m.cap_code]}")
                print(f"out: {m.x360_out.value[0]}")
                print("---")
            print()
            inp_opt = input("Choose option: ")
            if inp_opt == "b":
                return


def use_mapping_file(in_name: str, debug_print=False, dry_run=False):
    """
    Loops forever.
    debug_mode: Print packet upon change, but don't sen
    dry_run: Do not create virtual usb device (e.g. when testing outside of a raspi).

    FIXME: device disconnects
    FIXME: loop through mapping strategies and assign them before looping (no lazy eval?)
    TODO: Trigger axis strategies? (direct value/different default value)
    TODO: Multiple output states/controllers
    TODO: Rumble
    """

    # Initialize device
    fd = None
    if not dry_run:
        fd = init_360_gadget(True, 1)

    try:
        # Read json mapping
        json_mappings = None
        with open(in_name) as file_mapping:
            json_mappings = json.loads("\n".join(file_mapping.readlines()))
        if json_mappings is None:
            raise ValueError(
                f"Mapping file {in_name} contained null JSON; expected a list of mappings"
            )
        mappings: list[InputMapping] = [
            InputMapping(
                device_identifier=m.get("device_identifier"),
                cap_type=m.get("cap_type"),
                cap_code=m.get("cap_code"),
                x360_out=X360Surfaces[m.get("x360_out")],
                button_to_joystick=m.get("button_to_joystick"),
            )
            for m in json_mappings
        ]
        print(mappings)

        # Singular controller state (for now)
        xboxstate = XboxControllerState()
        last_packet = xboxstate.to_packet()

        # Loop through current devices dynamically and assign the proper mappings.
        get_devices = lambda: list(
            map(
                lambda x: (
                    evdev.InputDevice(x),
                    device_path_to_meta(evdev.InputDevice(x)),
                ),
                evdev.list_devices(),
            )
        )
        all_devices = get_devices()
        start_time = time.perf_counter_ns()
        while True:
            try:
                for d, meta in all_devices:
                    # Match witht the inputmapping ident.
                    ident = meta.uniq or meta.phys_id or meta.name
                    # Applicable mappings for this current device.
                    current_device_mappings = filter(
                        lambda x: x.device_identifier == ident, mappings
                    )
                    # Await next event.
                    event: evdev.InputEvent = d.read_one()
                    if event == None:
                        continue

                    # Process by matching
                    # categorized_event = evdev.categorize(event)
                    if current_event_mappings := list(
                        filter(
                            lambda x: x.cap_type == event.type
                            and x.cap_code == event.code,
                            current_device_mappings,
                        )
                    ):
                        current_event_mapping = current_event_mappings[0]

                        # key to key
                        if (
                            current_event_mapping.cap_type == ecodes.EV_KEY
                            and current_event_mapping.x360_out.is_button()
                        ):
                            # Update the state.
                            button: BitPackedButton = xboxstate.by_enum(
                                current_event_mapping.x360_out
                            )
                            button.value = 0
                            # might be 2 on repeat.
                            if event.value > 0:
                                button.value = 1
                        # key to axis
                        elif (
                            current_event_mapping.cap_type == ecodes.EV_KEY
                            and current_event_mapping.x360_out.is_axis()
                        ):
                            match current_event_mapping.x360_out:
                                case (
                                    X360Surfaces.LEFT_TRIGGER
                                    | X360Surfaces.RIGHT_TRIGGER
                                ):
                                    # 0-255
                                    # simple, just max it out.
                                    trigger_axis: Axis = xboxstate.by_enum(
                                        current_event_mapping.x360_out
                                    )
                                    trigger_axis.value = 0
                                    # might be 2 on repeat
                                    if event.value > 0:
                                        trigger_axis.value = 255
                                case _:
                                    # -32767 - 0 - 32767
                                    joystick_axis: JoystickAxis = xboxstate.by_enum(
                                        current_event_mapping.x360_out
                                    )

                                    match current_event_mapping.button_to_joystick:
                                        case ButtonToJoystickAxis.MAX_OUT | None:
                                            joystick_axis.value = 0
                                            if event.value > 0:
                                                joystick_axis.value = 32767
                                        case ButtonToJoystickAxis.MIN_OUT:
                                            joystick_axis.value = 0
                                            if event.value > 0:
                                                joystick_axis.value = -32767
                                        case ButtonToJoystickAxis.MIN_TO_MAX:
                                            joystick_axis.value = -32767
                                            if event.value > 0:
                                                joystick_axis.value = 32767
                                        case ButtonToJoystickAxis.MAX_TO_MIN:
                                            joystick_axis.value = 32767
                                            if event.value > 0:
                                                joystick_axis.value = -32767

                        # TODO:
                        # axis to axis
                        ## Dynamic abs info?/dyn calib.
                        elif (
                            current_event_mapping.cap_type == ecodes.EV_ABS
                            and current_event_mapping.x360_out.is_axis()
                        ):
                            print(event)
                        # axis to key
                        ## Threshold values? e.g. 10% deadzone -> press

                    # send or print out the current state on update.
                    if last_packet != xboxstate.to_packet():
                        last_packet = xboxstate.to_packet()
                        if debug_print:
                            print(last_packet)
                        if not dry_run:
                            send_to_ep(fd, 0, last_packet)
            except:
                # some error occured, probably device disconnect?
                # reload devices.
                all_devices = get_devices()
            finally:
                # time how long we took, and sleep slightly less than 1 ms. (900)
                end_time = time.perf_counter_ns()
                elapsed_s = (end_time - start_time) / 1_000_000_000
                target_s = 0.001
                max_sleep_s = 0.00095
                time_to_sleep = max(0, min(target_s - elapsed_s, max_sleep_s))
                time.sleep(time_to_sleep)
                start_time = time.perf_counter_ns()
    finally:
        if fd:
            close_360_gadget(fd)


# Example usage
async def main():
    # DeviceMenu().main_menu()

    use_mapping_file("out.json", dry_run=True, debug_print=True)


if __name__ == "__main__":
    asyncio.run(main())
