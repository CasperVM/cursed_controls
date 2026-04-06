from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from cursed_controls.config import load_config
from cursed_controls.discovery import list_devices
from cursed_controls.output import RawGadgetSink, StdoutSink
from cursed_controls.runtime import Runtime
from cursed_controls.simulate import SimulateRuntime


def main() -> None:
    parser = argparse.ArgumentParser(prog="cursed-controls")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-devices")

    run = sub.add_parser("run")
    run.add_argument("config")
    run.add_argument(
        "--stdout",
        action="store_true",
        help="print packets instead of opening gadget",
    )

    sim = sub.add_parser("simulate", help="interactive mock run without real hardware")
    sim.add_argument("config")

    map_p = sub.add_parser("map", help="interactive TUI to build a mapping config")
    map_p.add_argument("output", help="output YAML path")

    args = parser.parse_args()
    if args.cmd == "list-devices":
        print(json.dumps([asdict(d) for d in list_devices()], indent=2))
        return

    if args.cmd == "simulate":
        config = load_config(args.config)
        SimulateRuntime(config).run_repl()
        return

    if args.cmd == "map":
        from cursed_controls.mapper_tui import MapperTUI

        MapperTUI(args.output).run()
        return

    config = load_config(args.config)
    sink = (
        StdoutSink()
        if args.stdout or config.runtime.output_mode == "stdout"
        else RawGadgetSink(
            library_path=config.runtime.gadget_library,
            num_slots=config.runtime.interfaces,
            driver=config.runtime.gadget_driver,
            device=config.runtime.gadget_device,
        )
    )
    Runtime(config, sink).run()


if __name__ == "__main__":
    main()
