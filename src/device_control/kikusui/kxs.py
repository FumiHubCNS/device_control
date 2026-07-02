from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import Optional

from device_control.protocol.serial_line import SerialLine, SerialSettings


DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_BAUDRATE = 9600
DEFAULT_ADDRESS = "A1"

TK5_RE = re.compile(
    r"(?P<voltage>[+-]?\d+(?:\.\d+)?)V,(?P<current>[+-]?\d+(?:\.\d+)?)A"
)


@dataclass
class PowerStatus:
    connected: bool = False
    remote: bool = False
    output: Optional[bool] = None
    set_voltage_v: Optional[float] = None
    set_current_a: Optional[float] = None
    measured_voltage_v: Optional[float] = None
    measured_current_a: Optional[float] = None
    last_raw: Optional[str] = None
    last_error: Optional[str] = None
    updated_at: Optional[float] = None

    def asdict(self) -> dict:
        return asdict(self)


class KxsPowerSupply:
    """KIKUSUI KX-S style serial power-supply controller."""

    def __init__(
        self,
        port: str = DEFAULT_PORT,
        *,
        address: str = DEFAULT_ADDRESS,
        baudrate: int = DEFAULT_BAUDRATE,
    ) -> None:
        self.port = port
        self.address = address
        self.lock = threading.Lock()
        self.status = PowerStatus()
        self.line = SerialLine(
            port,
            settings=SerialSettings(baudrate=baudrate),
        )

    def connect(self) -> None:
        with self.lock:
            self.line.open()
            time.sleep(0.2)
            self.status.connected = True
            self.status.last_error = None

            # Remote selection returns no payload on the tested KX-S unit.
            self.line.write_line(self.address)
            self.status.remote = True
            self.status.updated_at = time.time()

    def close(self) -> None:
        with self.lock:
            self.line.close()
            self.status.connected = False
            self.status.updated_at = time.time()

    def write(self, command: str) -> None:
        with self.lock:
            self.line.write_line(command)

    def query(self, command: str) -> str:
        with self.lock:
            return self.line.query_line(command)

    def set_voltage(self, voltage_v: float) -> PowerStatus:
        with self.lock:
            self.line.write_line(f"{self.address},OV{voltage_v:.3f}")
            self.status.set_voltage_v = voltage_v
            self.status.last_error = None
            self.status.updated_at = time.time()
            return self.status

    def set_current(self, current_a: float) -> PowerStatus:
        with self.lock:
            self.line.write_line(f"{self.address},OC{current_a:.3f}")
            self.status.set_current_a = current_a
            self.status.last_error = None
            self.status.updated_at = time.time()
            return self.status

    def set_output(self, on: bool) -> PowerStatus:
        with self.lock:
            self.line.write_line(f"{self.address},OT{1 if on else 0}")
            self.status.output = on
            self.status.last_error = None
            self.status.updated_at = time.time()
            return self.status

    def read_measurement(self) -> PowerStatus:
        with self.lock:
            raw = self.line.query_line(f"{self.address},TK5")
            self.status.last_raw = raw
            self.status.updated_at = time.time()

            match = TK5_RE.search(raw)
            if not match:
                self.status.last_error = f"Unexpected TK5 response: {raw!r}"
                return self.status

            self.status.measured_voltage_v = float(match.group("voltage"))
            self.status.measured_current_a = float(match.group("current"))
            self.status.connected = True
            self.status.remote = True
            self.status.last_error = None
            return self.status


def find_ft232_port() -> str:
    from serial.tools import list_ports

    ports = list(list_ports.comports())

    for port in ports:
        if port.vid == 0x0403 and port.pid == 0x6001:
            return port.device

    for port in ports:
        if "ttyUSB" in port.device:
            return port.device

    raise RuntimeError("FT232 / ttyUSB device not found")
