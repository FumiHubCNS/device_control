from __future__ import annotations

import argparse
import json
import sys

from .driver import Mdo3034


def _channels(value: str) -> list[int]:
    channels = [int(item) for item in value.replace(",", " ").split()]
    if not channels:
        raise argparse.ArgumentTypeError("at least one channel is required")
    invalid = [channel for channel in channels if channel not in (1, 2, 3, 4)]
    if invalid:
        raise argparse.ArgumentTypeError(f"invalid channel(s): {invalid}")
    return channels


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Control Tektronix MDO3034")
    parser.add_argument("--resource", help="VISA resource, e.g. TCPIP0::...::INSTR")
    parser.add_argument("--ip", help="Oscilloscope IP")
    parser.add_argument("--socket", action="store_true", help="Use TCPIP socket resource")
    parser.add_argument("--socket-port", type=int, default=4000)
    parser.add_argument("--backend", default="@py", help="pyvisa ResourceManager backend")
    parser.add_argument("--timeout-ms", type=int, default=20000)
    parser.add_argument("--verbose", action="store_true")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Read IDN, channel config, and trigger config")

    acquire = subparsers.add_parser("acquire", help="Acquire or read waveforms")
    acquire.add_argument("-ch", "--channels", type=_channels, default=[1], help="Channels, e.g. '1 2'")
    acquire.add_argument("--start", type=int, default=1)
    acquire.add_argument("--stop", type=int, default=2000)
    acquire.add_argument("--trigger-window", action="store_true")
    acquire.add_argument("--pretrigger-points", type=int, default=1000)
    acquire.add_argument("--posttrigger-points", type=int, default=1000)
    acquire.add_argument("--single", action="store_true", help="Arm single sequence before reading")
    acquire.add_argument("--timeout", type=float, default=60.0)

    return parser.parse_args(argv)


def _open(args: argparse.Namespace) -> Mdo3034:
    if args.resource is None and args.ip is None:
        raise ValueError("Provide --resource or --ip")
    scope = Mdo3034(
        resource=args.resource,
        ip=args.ip,
        socket=args.socket,
        socket_port=args.socket_port,
        backend=args.backend,
        timeout_ms=args.timeout_ms,
        verbose=args.verbose,
    )
    scope.connect()
    return scope


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scope = None
    try:
        scope = _open(args)
        if args.command == "status":
            print(
                json.dumps(
                    {
                        "idn": scope.get_idn(),
                        "channels": [item.asdict() for item in scope.get_all_channel_configs()],
                        "trigger": scope.get_trigger_config().asdict(),
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "acquire":
            waveforms = scope.acquire_waveforms(
                channels=args.channels,
                start=args.start,
                stop=args.stop,
                single=args.single,
                timeout_s=args.timeout,
                trigger_window=args.trigger_window,
                pretrigger_points=args.pretrigger_points,
                posttrigger_points=args.posttrigger_points,
            )
            print(
                json.dumps(
                    {
                        "waveforms": [
                            {
                                "channel": waveform.channel,
                                "points": int(waveform.time_s.size),
                                "time_start_s": float(waveform.time_s[0])
                                if waveform.time_s.size
                                else None,
                                "time_stop_s": float(waveform.time_s[-1])
                                if waveform.time_s.size
                                else None,
                                "voltage_min_v": float(waveform.voltage_v.min())
                                if waveform.voltage_v.size
                                else None,
                                "voltage_max_v": float(waveform.voltage_v.max())
                                if waveform.voltage_v.size
                                else None,
                                "start": waveform.preamble.get("start"),
                                "stop": waveform.preamble.get("stop"),
                                "trigger_point": waveform.preamble.get("trigger_point"),
                                "trigger_window": waveform.preamble.get("trigger_window"),
                                "preamble": waveform.preamble,
                            }
                            for waveform in waveforms
                        ]
                    },
                    indent=2,
                )
            )
            return 0

        raise RuntimeError(f"Unknown command: {args.command}")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if scope is not None:
            scope.close()


if __name__ == "__main__":
    raise SystemExit(main())
