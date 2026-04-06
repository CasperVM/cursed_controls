from __future__ import annotations

import evdev
from evdev import ecodes

from cursed_controls.config import AppConfig, TransformKind
from cursed_controls.output import OutputSink, StdoutSink
from cursed_controls.runtime import Mapper
from cursed_controls.xbox import XboxControllerState


def _resolve_code(token: str) -> int:
    """Accept a numeric string or an evdev name like BTN_A / ABS_X."""
    try:
        return int(token)
    except ValueError:
        pass
    code = ecodes.ecodes.get(token)
    if code is None:
        raise ValueError(f"unknown evdev code {token!r}")
    return code


def _code_name(ev_type: int, code: int) -> str:
    return ecodes.bytype.get(ev_type, {}).get(code, str(code))


def _format_state(state: XboxControllerState) -> str:
    buttons = [
        name
        for name, val in [
            ("A", state.a),
            ("B", state.b),
            ("X", state.x),
            ("Y", state.y),
            ("LB", state.lb),
            ("RB", state.rb),
            ("L3", state.l3),
            ("R3", state.r3),
            ("START", state.start),
            ("OPT", state.options),
            ("XBOX", state.xbox),
            ("DU", state.dpad_up),
            ("DD", state.dpad_down),
            ("DL", state.dpad_left),
            ("DR", state.dpad_right),
        ]
        if val
    ]
    parts: list[str] = []
    parts.append("buttons=" + (",".join(buttons) if buttons else "-"))
    if state.left_trigger:
        parts.append(f"LT={state.left_trigger}")
    if state.right_trigger:
        parts.append(f"RT={state.right_trigger}")
    lj = (state.left_joystick_x, state.left_joystick_y)
    rj = (state.right_joystick_x, state.right_joystick_y)
    if any(lj):
        parts.append(f"LJ={lj}")
    if any(rj):
        parts.append(f"RJ={rj}")
    parts.append(f"packet={state.to_packet().hex()}")
    return "  ".join(parts)


class SimulateRuntime:
    """Run a mapping config interactively without real hardware."""

    def __init__(self, config: AppConfig, sink: OutputSink | None = None):
        self.config = config
        self.mapper = Mapper(config)
        self.sink = sink or StdoutSink()
        self.profiles = {p.id: p for p in config.devices}

    def inject(self, profile_id: str, ev_type: int, ev_code: int, value: int) -> bool:
        """Inject a synthetic event. Returns True if controller state changed."""
        if profile_id not in self.profiles:
            raise KeyError(f"no profile {profile_id!r} in config")
        profile = self.profiles[profile_id]
        event = evdev.InputEvent(sec=0, usec=0, type=ev_type, code=ev_code, value=value)
        changed = self.mapper.process_event(profile, event)
        if changed:
            self.sink.send(self.mapper.state)
        return changed

    def _print_banner(self) -> None:
        print("cursed-controls simulate, no hardware needed")
        print()
        print("Profiles from config:")
        for profile in self.config.devices:
            match = profile.match
            ident = (
                f"name={match.name!r}"
                if match.name
                else f"uniq={match.uniq!r}"
                if match.uniq
                else f"phys={match.phys!r}"
            )
            print(f"  [{profile.id}]  match: {ident}")
            for rule in profile.mappings:
                code_name = _code_name(rule.source_type, rule.source_code)
                type_name = {1: "EV_KEY", 3: "EV_ABS"}.get(
                    rule.source_type, str(rule.source_type)
                )
                kind = rule.transform.kind.value
                print(
                    f"    {type_name} {rule.source_code} ({code_name})  [{kind}]  → {rule.target.value}"
                )
        print()
        print("Commands:")
        print("  press   <profile> <code>        inject EV_KEY value=1")
        print("  release <profile> <code>        inject EV_KEY value=0")
        print("  axis    <profile> <code> <n>    inject EV_ABS value=n")
        print("  state                           print current controller state")
        print("  help                            show this message")
        print("  quit / exit / Ctrl-C            exit")
        print()
        print("<code> accepts evdev names (BTN_A, ABS_X) or integers (304, 0)")
        print()

    def _handle_line(self, line: str) -> bool:
        """Parse and execute one REPL line. Returns False to quit."""
        parts = line.strip().split()
        if not parts:
            return True
        cmd = parts[0].lower()

        if cmd in ("quit", "exit", "q"):
            return False

        if cmd in ("state", "s"):
            print("[STATE]", _format_state(self.mapper.state))
            return True

        if cmd in ("help", "h", "?"):
            self._print_banner()
            return True

        if cmd == "press" and len(parts) >= 3:
            try:
                code = _resolve_code(parts[2])
                changed = self.inject(parts[1], ecodes.EV_KEY, code, 1)
                print(
                    "[STATE]",
                    _format_state(self.mapper.state),
                    "" if changed else "(no change)",
                )
            except (KeyError, ValueError) as e:
                print(f"error: {e}")
            return True

        if cmd == "release" and len(parts) >= 3:
            try:
                code = _resolve_code(parts[2])
                changed = self.inject(parts[1], ecodes.EV_KEY, code, 0)
                print(
                    "[STATE]",
                    _format_state(self.mapper.state),
                    "" if changed else "(no change)",
                )
            except (KeyError, ValueError) as e:
                print(f"error: {e}")
            return True

        if cmd == "axis" and len(parts) >= 4:
            try:
                code = _resolve_code(parts[2])
                value = int(parts[3])
                changed = self.inject(parts[1], ecodes.EV_ABS, code, value)
                print(
                    "[STATE]",
                    _format_state(self.mapper.state),
                    "" if changed else "(no change)",
                )
            except (KeyError, ValueError) as e:
                print(f"error: {e}")
            return True

        print(f"unknown command {cmd!r} type 'help' for usage")
        return True

    def run_repl(self) -> None:
        self.sink.open()
        self._print_banner()
        try:
            while True:
                try:
                    line = input("> ")
                except EOFError:
                    break
                if not self._handle_line(line):
                    break
        except KeyboardInterrupt:
            print()
        finally:
            self.sink.close()
