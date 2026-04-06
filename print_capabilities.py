#!/usr/bin/env python3

import asyncio
import evdev
from evdev import ecodes
from evdev.ecodes import ABS


async def main():
    for d in map(evdev.InputDevice, evdev.list_devices()):
        print(
            f"'{d.name}' has the following capabilites:\n '{d.capabilities(verbose=True)}'"
        )
    # print('reading inputs:')
    # for d in map(evdev.InputDevice, evdev.list_devices()):
    #     if d.name == 'Xbox Wireless Controller':
    #         for event in d.read_loop():
    #             categorized_event = evdev.categorize(event)
    #             if event.type == ecodes.EV_ABS:
    #                 print(f"{ABS[categorized_event.event.code]}: {event.value}")
    #             else:
    #                 print(categorized_event)


if __name__ == "__main__":
    asyncio.run(main())
