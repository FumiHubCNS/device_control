from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SerialSettings:
    baudrate: int = 9600
    timeout: float = 1.0
    write_timeout: float = 1.0
    inter_command_delay_s: float = 0.2


class SerialLine:
    """Small locked-at-caller serial helper for command/response devices."""

    def __init__(
        self,
        port: str,
        *,
        settings: SerialSettings | None = None,
        **serial_kwargs: Any,
    ) -> None:
        self.port = port
        self.settings = settings or SerialSettings()
        self.serial_kwargs = serial_kwargs
        self._serial = None

    @property
    def is_open(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    def open(self) -> None:
        if self.is_open:
            return

        import serial

        kwargs = {
            "port": self.port,
            "baudrate": self.settings.baudrate,
            "bytesize": serial.EIGHTBITS,
            "parity": serial.PARITY_NONE,
            "stopbits": serial.STOPBITS_ONE,
            "timeout": self.settings.timeout,
            "write_timeout": self.settings.write_timeout,
            "rtscts": False,
            "dsrdtr": False,
            "xonxoff": False,
        }
        kwargs.update(self.serial_kwargs)
        self._serial = serial.Serial(**kwargs)
        self._serial.setDTR(True)
        self._serial.setRTS(True)

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def _require_serial(self):
        if not self.is_open:
            raise RuntimeError("Serial port is not open")
        return self._serial

    def write_line(self, command: str) -> None:
        ser = self._require_serial()
        ser.reset_input_buffer()
        ser.write((command + "\r\n").encode("ascii"))
        ser.flush()
        time.sleep(self.settings.inter_command_delay_s)

    def query_line(self, command: str) -> str:
        ser = self._require_serial()
        ser.reset_input_buffer()
        ser.write((command + "\r\n").encode("ascii"))
        ser.flush()
        time.sleep(self.settings.inter_command_delay_s)
        return ser.read_all().decode("ascii", errors="replace").strip()
