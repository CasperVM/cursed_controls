# cursed_controls
Controller to virtual controller mapping. Essentially turning any OTG capable SBC into a wireless controller receiver/input converter.

E.g.:
- wii remote + nunchuck & PS5 controlelr -> virtual xbox controller

Note: This project is still in early development and probably pretty broken for now.

## Raspberry pi setup

Take a look at the install guide: [SetupRaspbian.md](SetupRaspbian.md).

## Why:

An Xbox controller is really well supported on many devices, usually drivers pre-exist for it.
Connecting a Wii remote to a device is a bit more tricky, to say the least.

## Capabilities

Input controllers:

- Wii mote + nunchuck
- Any controller supported by [GilRs](https://docs.rs/gilrs/latest/gilrs/)

### TBA:

- Debugging of GilRs/refactoring
- Adding a proper mapping format w/ json
- Basic CLI for building a mapping
- Webinterface for setup?
- Axis to button mapping?
- Rumble support
- Other 'fancy' settings (leds etc.)

## Known issues

- xwiimote not linked properly => try to compile with `XWIIMOTE_SYS_STATIC=1`
