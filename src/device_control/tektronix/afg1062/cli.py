from __future__ import annotations

import argparse
import json
import sys

from device_control.protocol import decode_escape_sequences

from .driver import Afg1062


def _bool_value(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "on", "yes"}:
        return True
    if normalized in {"0", "false", "off", "no"}:
        return False
    raise argparse.ArgumentTypeError("expected on/off, true/false, or 1/0")


def _add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--resource", help="VISA resource, e.g. USB0::...::INSTR")
    parser.add_argument("--usbtmc", help="Linux USB-TMC device, e.g. /dev/usbtmc0")
    parser.add_argument("--ip", help="Instrument IP for TCPIP0::<ip>::INSTR")
    parser.add_argument("--backend", default="@py", help="pyvisa ResourceManager backend")
    parser.add_argument("--timeout-ms", type=int, default=10000)
    parser.add_argument("--write-termination", default="\n", help="SCPI write termination")
    parser.add_argument("--verbose", action="store_true")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Control Tektronix AFG1062")
    _add_connection_args(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Read current settings")
    status.add_argument("-ch", "--channel", type=int, choices=[1, 2])

    set_cmd = subparsers.add_parser("set", help="Set channel waveform parameters")
    set_cmd.add_argument("-ch", "--channel", type=int, choices=[1, 2], required=True)
    set_cmd.add_argument("--waveform", help="SIN, SQU, RAMP, PULS, NOIS, DC, USER")
    set_cmd.add_argument("--frequency", type=float, help="Frequency in Hz")
    set_cmd.add_argument("--amplitude", type=float, help="Amplitude in Vpp")
    set_cmd.add_argument("--offset", type=float, help="Offset in V")
    set_cmd.add_argument("--phase", type=float, help="Phase value")
    set_cmd.add_argument("--phase-unit", default="RAD", choices=["RAD", "DEG"])
    set_cmd.add_argument("--duty-cycle", type=float, help="Pulse duty cycle in percent")
    set_cmd.add_argument("--output", type=_bool_value, help="Output state")

    output = subparsers.add_parser("output", help="Set output only")
    output.add_argument("-ch", "--channel", type=int, choices=[1, 2], required=True)
    output.add_argument("state", type=_bool_value)

    return parser.parse_args(argv)


def _open(args: argparse.Namespace) -> Afg1062:
    if args.resource is None and args.usbtmc is None and args.ip is None:
        raise ValueError("Provide --resource for VISA, --usbtmc for Linux USB-TMC, or --ip for TCP/IP")
    afg = Afg1062(
        resource=args.resource,
        usbtmc=args.usbtmc,
        ip=args.ip,
        backend=args.backend,
        timeout_ms=args.timeout_ms,
        write_termination=decode_escape_sequences(args.write_termination),
        verbose=args.verbose,
    )
    afg.connect()
    return afg


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    afg = None
    try:
        afg = _open(args)
        if args.command == "status":
            if args.channel:
                payload = afg.get_channel_settings(args.channel).asdict()
            else:
                payload = {
                    "idn": afg.get_idn(),
                    "channels": [item.asdict() for item in afg.get_all_settings()],
                }
            print(json.dumps(payload, indent=2))
            return 0

        if args.command == "set":
            payload = afg.apply_channel_settings(
                channel=args.channel,
                output=args.output,
                waveform=args.waveform,
                frequency_hz=args.frequency,
                amplitude_vpp=args.amplitude,
                offset_v=args.offset,
                phase=args.phase,
                phase_unit=args.phase_unit,
                duty_cycle_percent=args.duty_cycle,
            )
            print(json.dumps(payload.asdict(), indent=2))
            return 0

        if args.command == "output":
            afg.set_output(args.channel, args.state)
            print(json.dumps(afg.get_channel_settings(args.channel).asdict(), indent=2))
            return 0

        raise RuntimeError(f"Unknown command: {args.command}")

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    finally:
        if afg is not None:
            afg.close()


if __name__ == "__main__":
    raise SystemExit(main())
