from __future__ import annotations

from typing import Protocol


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
        response = self.instrument.query(command).strip()
        self._log("<<<", response)
        return response

    def read_raw(self) -> bytes:
        return self.instrument.read_raw()
