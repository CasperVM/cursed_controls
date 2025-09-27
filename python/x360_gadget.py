import ctypes
import os
import time

from x360 import XboxControllerState

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


def example_loop():
    fd = init_360_gadget(True, 1)
    print("fd =", fd)

    state = XboxControllerState()

    try:
        while True:
            time.sleep(1)

            # toggle some buttons
            state.buttons.a.value = not state.buttons.a.value
            state.buttons.b.value = not state.buttons.b.value

            # move left joystick NE
            state.left_joystick.x.value = 32760
            state.left_joystick.y.value = 32760

            packet = state.to_packet()
            ok = send_to_ep(fd, 0, packet)
            print("Packet sent:", packet, "ok:", ok)

    finally:
        close_360_gadget(fd)


if __name__ == "__main__":
    example_loop()
