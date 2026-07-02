from __future__ import annotations

import os
import time
from typing import Protocol


def decode_escape_sequences(value: str) -> str:
    r"""Decode simple CLI/UI escape sequences such as \n and \r."""

    return value.encode("utf-8").decode("unicode_escape")


class ScpiClient(Protocol):
    """Minimal SCPI client interface used by device drivers."""

    def connect(self) -> None:
        ...

    def close(self) -> None:
        ...

    def write(self, command: str) -> None:
        ...

    def query(self, command: str) -> str:
        ...

    def read_raw(self) -> bytes:
        ...


class PyVisaScpiClient:
    """SCPI client backed by pyvisa."""

    def __init__(
        self,
        resource: str,
        *,
        backend: str = "@py",
        timeout_ms: int = 10000,
        write_termination: str = "\n",
        read_termination: str = "\n",
        verbose: bool = False,
    ) -> None:
        self.resource = resource
        self.backend = backend
        self.timeout_ms = timeout_ms
        self.write_termination = write_termination
        self.read_termination = read_termination
        self.verbose = verbose

        self._rm = None
        self._instrument = None

    @classmethod
    def tcpip(
        cls,
        ip: str,
        *,
        backend: str = "@py",
        timeout_ms: int = 10000,
        verbose: bool = False,
    ) -> PyVisaScpiClient:
        return cls(
            f"TCPIP0::{ip}::INSTR",
            backend=backend,
            timeout_ms=timeout_ms,
            verbose=verbose,
        )

    @classmethod
    def tcpip_socket(
        cls,
        ip: str,
        *,
        port: int = 4000,
        backend: str = "@py",
        timeout_ms: int = 10000,
        verbose: bool = False,
    ) -> PyVisaScpiClient:
        return cls(
            f"TCPIP0::{ip}::{port}::SOCKET",
            backend=backend,
            timeout_ms=timeout_ms,
            verbose=verbose,
        )

    def _log(self, prefix: str, value: str) -> None:
        if self.verbose:
            print(f"{prefix} {value}")

    @property
    def instrument(self):
        if self._instrument is None:
            raise RuntimeError("SCPI resource is not open")
        return self._instrument

    def connect(self) -> None:
        import pyvisa

        self._rm = pyvisa.ResourceManager(self.backend)
        self._instrument = self._rm.open_resource(self.resource)
        self._instrument.write_termination = self.write_termination
        self._instrument.read_termination = self.read_termination
        self._instrument.timeout = self.timeout_ms

    def close(self) -> None:
        if self._instrument is not None:
            self._instrument.close()
            self._instrument = None
        if self._rm is not None:
            self._rm.close()
            self._rm = None

    def write(self, command: str) -> None:
        self._log(">>>", command)
        self.instrument.write(command)

    def query(self, command: str) -> str:
        self._log(">>>", command)
        try:
            response = self.instrument.query(command).strip()
        except Exception as exc:
            raise RuntimeError(
                f"SCPI query failed for {command!r} on {self.resource}: {exc}"
            ) from exc
        self._log("<<<", response)
        return response

    def read_raw(self) -> bytes:
        return self.instrument.read_raw()


class UsbtmcScpiClient:
    """SCPI client backed by Linux USB-TMC character devices."""

    def __init__(
        self,
        device: str = "/dev/usbtmc0",
        *,
        timeout_ms: int = 10000,
        write_termination: str = "\n",
        read_chunk_size: int = 65536,
        poll_interval_s: float = 0.01,
        verbose: bool = False,
    ) -> None:
        self.device = device
        self.timeout_ms = timeout_ms
        self.write_termination = write_termination
        self.read_chunk_size = read_chunk_size
        self.poll_interval_s = poll_interval_s
        self.verbose = verbose
        self._fd: int | None = None

    def _log(self, prefix: str, value: str) -> None:
        if self.verbose:
            print(f"{prefix} {value}")

    @property
    def fd(self) -> int:
        if self._fd is None:
            raise RuntimeError("USB-TMC device is not open")
        return self._fd

    def connect(self) -> None:
        try:
            self._fd = os.open(self.device, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError as exc:
            raise PermissionError(
                f"Permission denied opening {self.device}. "
                "Grant read/write access to the USB-TMC device, for example with a udev rule "
                'such as: SUBSYSTEM=="usbmisc", KERNEL=="usbtmc*", MODE="0660", GROUP="plugdev"'
            ) from exc

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def write(self, command: str) -> None:
        self._log(">>>", command)
        payload = (command + self.write_termination).encode("ascii")
        written = 0
        while written < len(payload):
            try:
                count = os.write(self.fd, payload[written:])
            except BlockingIOError:
                time.sleep(self.poll_interval_s)
                continue
            if count == 0:
                raise TimeoutError(f"Timed out writing to {self.device}")
            written += count

    def query(self, command: str) -> str:
        self.write(command)
        try:
            response = self.read_raw().decode("ascii", errors="replace").strip()
        except TimeoutError as exc:
            raise TimeoutError(f"Timed out after SCPI query {command!r}: {exc}") from exc
        self._log("<<<", response)
        return response

    def read_raw(self) -> bytes:
        chunks = []
        deadline = time.monotonic() + self.timeout_ms / 1000
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if chunks:
                    return b"".join(chunks)
                raise TimeoutError(
                    f"Timed out reading from {self.device}. "
                    "The command was written, but no response was received. "
                    "Check that the device is not locked by another process and try a simple query such as *IDN?."
                )

            try:
                chunk = os.read(self.fd, self.read_chunk_size)
            except BlockingIOError:
                time.sleep(min(self.poll_interval_s, max(remaining, 0)))
                continue
            if not chunk:
                if chunks:
                    return b"".join(chunks)
                continue

            chunks.append(chunk)
            if chunk.endswith(b"\n"):
                return b"".join(chunks)
