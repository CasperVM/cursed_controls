#!/usr/bin/env python

# source: https://blog.malware.re/2023/07/04/Wiimote-on-Linux-with-dev-input/index.html
import time
import evdev
import os
import sys

INPUT_DIR = "/dev/input"
WIIMOTE_NAME = "Nintendo Wii Remote Accelerometer"
WIIMOTE_MAX = 103
WIIMOTE_MIN = -105


def get_wiimote_accel():
    for evnode in os.scandir(INPUT_DIR):
        if evnode.is_dir():
            continue

        try:
            device = evdev.InputDevice(os.path.join(INPUT_DIR, evnode.name))
            if device.name == WIIMOTE_NAME:
                return device
        except:
            continue

    return None


wiimote = get_wiimote_accel()

if wiimote:
    print("Found Wiimote: {}".format(wiimote))
    x = 0
    y = 0
    z = 0
    drive_direction = "s"
    steer_direction = "s"
    sys.stdout.write("X: {}, Y: {}, Z: {}            \r".format(x, y, z))
    for event in wiimote.read_loop():
        if event.type != evdev.ecodes.EV_ABS:
            print(event)
        if event.type == evdev.ecodes.EV_ABS:
            adj = 0.0
            if event.value >= 0:
                adj = float(event.value) / float(WIIMOTE_MAX)
            else:
                adj = float(event.value) / float(WIIMOTE_MIN)
            if event.code == evdev.ecodes.ABS_RX:
                x = adj
                if event.value < 0:
                    drive_direction = "b"
                elif event.value > 0:
                    drive_direction = "f"
                else:
                    drive_direction = "s"
            if event.code == evdev.ecodes.ABS_RY:
                y = adj
                if event.value < 0:
                    steer_direction = "r"
                elif event.value > 0:
                    steer_direction = "l"
                else:
                    steer_direction = "s"
            if event.code == evdev.ecodes.ABS_RZ:
                z = adj

            direction = drive_direction

            if y > 0.3:
                # If Wiimote turned more than 1/3 either way, then send a steering instruction
                # instead of a forward/backward instruction
                direction = steer_direction
            else:
                # In order to give more generous "stop" range, only send a drive instruction if
                # the Wiimote is tilted 10% forward or backward
                if x < 0.1:
                    direction = "s"

            sys.stdout.write(
                "X: {:0.3f}, Y: {:0.3f}, Z: {:0.3f} ({})   \r".format(
                    x, y, z, direction
                )
            )
