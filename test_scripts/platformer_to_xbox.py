#!/usr/bin/env python3
import asyncio
from dataclasses import dataclass
import dataclasses
import evdev
from evdev import KeyEvent, ecodes, categorize, InputDevice
from evdev.eventio_async import EventIO


import ctypes
import os
import time

from python.x360 import XboxControllerState

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


# WII
# [ecodes.BTN_1,
# ecodes.BTN_2,
# ecodes.KEY_NEXT,
# ecodes.BTN_MODE,
# ecodes.KEY_PREVIOUS,
# ecodes.BTN_A,
# ecodes.BTN_B,
# ecodes.KEY_UP,
# ecodes.KEY_DOWN,
# ecodes.KEY_LEFT,
# ecodes.KEY_RIGHT
# ]

# self.a = BitPackedButton("A", 0x04)
# self.b = BitPackedButton("B", 0x05)
# self.x = BitPackedButton("X", 0x06)
# self.y = BitPackedButton("Y", 0x07)
# self.lb = BitPackedButton("LB", 0x00)
# self.rb = BitPackedButton("RB", 0x01)
# self.l3 = BitPackedButton("L3", 0x06)
# self.r3 = BitPackedButton("R3", 0x07)
# self.start = BitPackedButton("START", 0x04)
# self.options = BitPackedButton("OPTIONS", 0x05)
# self.xbox = BitPackedButton("XBOX", 0x02)
# self.dpad_up = BitPackedButton("DPAD_UP", 0x00)
# self.dpad_down = BitPackedButton("DPAD_DOWN", 0x01)
# self.dpad_left = BitPackedButton("DPAD_LEFT", 0x02)
# self.dpad_right = BitPackedButton("DPAD_RIGHT", 0x03)


async def handle_wiimote_event_frame(device: InputDevice | EventIO, state: dict):
    print(f"Listening on {device.path} ({device.name})")
    while True:
        event = await device.async_read_one()

        if event.type == ecodes.EV_SYN:
            break
        elif event.type == ecodes.EV_KEY:
            key_event = categorize(event)
            state[key_event.event.code] = key_event.keystate == key_event.key_down
        elif event.type == ecodes.EV_ABS:
            print(event)


# (silksong)
# wiimote_xbox_map = {
#     ecodes.BTN_1 : "X", # attack
#     ecodes.BTN_2 : "A",  # jump
#     ecodes.BTN_B : "RIGHT_TRIGGER", # sprint
#     ecodes.BTN_A : "B", # bind/heal

#     ecodes.KEY_NEXT: "START", # pause
#     ecodes.KEY_PREVIOUS: "OPTIONS", # inventory

#     # dpad...
#     ecodes.KEY_RIGHT : "DPAD_UP",
#     ecodes.KEY_DOWN : "DPAD_RIGHT",
#     ecodes.KEY_LEFT : "DPAD_DOWN",
#     ecodes.KEY_UP : "DPAD_LEFT"
# }

# alt_button=ecodes.BTN_MODE
# alt_map = {
#     ecodes.BTN_B : "RB", # tool

#     ecodes.KEY_NEXT: "Y",  # needolin
#     ecodes.KEY_PREVIOUS: "LB",  # map

#     ecodes.BTN_A : "LEFT_TRIGGER", # harpoon
# }

wiimote_xbox_map = {
    ecodes.BTN_1: "X",  # attack
    ecodes.BTN_2: "A",  # jump
    ecodes.BTN_B: "RIGHT_TRIGGER",  # sprint
    ecodes.BTN_MODE: "B",  # back/bind/heal
    ecodes.KEY_NEXT: "START",  # pause
    ecodes.KEY_PREVIOUS: "OPTIONS",  # inventory
    # dpad...
    ecodes.KEY_RIGHT: "DPAD_UP",
    ecodes.KEY_DOWN: "DPAD_RIGHT",
    ecodes.KEY_LEFT: "DPAD_DOWN",
    ecodes.KEY_UP: "DPAD_LEFT",
}

alt_button = ecodes.BTN_A
alt_map = {
    ecodes.BTN_1: "RB",  # tool
    # ecodes.BTN_2 : "B",  # back/bind/heal
    ecodes.BTN_B: "LEFT_TRIGGER",  # harpoon
    ecodes.KEY_NEXT: "Y",  # needolin
    ecodes.KEY_PREVIOUS: "LB",  # map
}


async def main():
    fd = init_360_gadget(True, 1)
    print("fd =", fd)

    xboxstate = XboxControllerState()

    devices = [
        d
        for d in map(evdev.InputDevice, evdev.list_devices())
        if d.name == "Nintendo Wii Remote"
    ]

    if not devices:
        print("No Wiimotes found.")
        return

    def update_xbox_state(state: XboxControllerState, mapping: dict, k, v):
        for wii_button, mapping in mapping.items():
            if wii_button == k:
                try:
                    state.buttons.get_button(mapping).value = v
                except:
                    # No button found, maybe its an axis?
                    match mapping:
                        case "LEFT_TRIGGER":
                            state.left_trigger.value = 255 if v else 0
                            break
                        case "RIGHT_TRIGGER":
                            state.right_trigger.value = 255 if v else 0
                            break

    wiimote = {}
    try:
        while True:
            await handle_wiimote_event_frame(devices[0], wiimote)
            alt_mode_active = wiimote.get(alt_button, False)

            for k, v in wiimote.items():
                if k == alt_button:
                    pass
                if alt_mode_active and k in alt_map.keys():
                    update_xbox_state(xboxstate, alt_map, k, v)
                    update_xbox_state(xboxstate, wiimote_xbox_map, k, False)
                    continue
                update_xbox_state(xboxstate, wiimote_xbox_map, k, v)
                update_xbox_state(xboxstate, alt_map, k, False)

            packet = xboxstate.to_packet()
            ok = send_to_ep(fd, 0, packet)
            print("Packet sent:", packet, "ok:", ok)
    finally:
        close_360_gadget(fd)


asyncio.run(main())
