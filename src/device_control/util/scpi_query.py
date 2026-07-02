from __future__ import annotations

import argparse

from device_control.protocol import (
    PyVisaScpiClient,
    ScpiClient,
    UsbtmcScpiClient,
    decode_escape_sequences,
)


def _open_client(args: argparse.Namespace) -> ScpiClient:
    if args.usbtmc:
        return UsbtmcScpiClient(
            args.usbtmc,
            timeout_ms=args.timeout_ms,
            write_termination=decode_escape_sequences(args.write_termination),
            verbose=args.verbose,
        )
    if args.resource:
        return PyVisaScpiClient(
            args.resource,
            backend=args.backend,
            timeout_ms=args.timeout_ms,
            write_termination=decode_escape_sequences(args.write_termination),
            read_termination=decode_escape_sequences(args.read_termination),
            verbose=args.verbose,
        )
    if args.ip:
        return PyVisaScpiClient.tcpip(
            args.ip,
            backend=args.backend,
            timeout_ms=args.timeout_ms,
            verbose=args.verbose,
        )
    raise ValueError("Provide --usbtmc, --resource, or --ip")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send one SCPI command and optionally print the response")
    parser.add_argument("query", nargs="?", default="*IDN?", help="SCPI query or command to send")
    parser.add_argument("--usbtmc", help="Linux USB-TMC device, e.g. /dev/usbtmc0")
    parser.add_argument("--resource", help="VISA resource, e.g. USB0::...::INSTR")
    parser.add_argument("--ip", help="Instrument IP for TCPIP0::<ip>::INSTR")
    parser.add_argument("--backend", default="@py", help="pyvisa ResourceManager backend")
    parser.add_argument("--timeout-ms", type=int, default=10000)
    parser.add_argument("--write-termination", default="\n")
    parser.add_argument("--read-termination", default="\n")
    parser.add_argument("--write-only", action="store_true", help="Send the command without waiting for a response")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    client = _open_client(args)
    try:
        client.connect()
        if args.write_only:
            client.write(args.query)
        else:
            print(client.query(args.query))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
