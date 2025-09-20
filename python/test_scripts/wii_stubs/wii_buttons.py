#!/usr/bin/env python3
import asyncio
import evdev
from evdev import ecodes, categorize, InputDevice
from evdev.eventio_async import EventIO


async def handle_device(device: InputDevice | EventIO):
    print(f"Listening on {device.path} ({device.name})")
    while True:
        event = await device.async_read_one()

        if event.type == ecodes.EV_KEY:
            key_event = categorize(event)
            if key_event.keystate == key_event.key_down:
                print(
                    f"[{device.name}] Button pressed: {key_event.keycode} {key_event}"
                )
                return  # quit as soon as we get the first event
            elif key_event.keystate == key_event.key_up:
                print(
                    f"[{device.name}] Button released: {key_event.keycode} {key_event}"
                )
                return


async def main():
    devices = [
        d
        for d in map(evdev.InputDevice, evdev.list_devices())
        if d.name.startswith("Nintendo Wii Remote")
    ]

    if not devices:
        print("No Wiimotes found.")
        return

    # Spawn one task per device
    tasks = [asyncio.create_task(handle_device(dev)) for dev in devices]

    # Quit when the *first* one returns
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)


asyncio.run(main())
