from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from device_control.protocol import PyVisaScpiClient, ScpiClient


Waveform = Literal["SIN", "SQU", "RAMP", "PULS", "NOIS", "DC", "USER"]


@dataclass
class ChannelSettings:
    channel: int
    output: bool | None = None
    waveform: str | None = None
    frequency_hz: float | None = None
    amplitude_vpp: float | None = None
    offset_v: float | None = None
    phase_rad: float | None = None
    duty_cycle_percent: float | None = None

    def asdict(self) -> dict:
        return asdict(self)


class Afg1062:
    """Tektronix AFG1062 SCPI controller."""

    def __init__(
        self,
        *,
        resource: str | None = None,
        ip: str | None = None,
        backend: str = "@py",
        timeout_ms: int = 10000,
        verbose: bool = False,
        client: ScpiClient | None = None,
    ) -> None:
        if client is not None:
            self.client = client
        elif resource is not None:
            self.client = PyVisaScpiClient(
                resource,
                backend=backend,
                timeout_ms=timeout_ms,
                verbose=verbose,
            )
        elif ip is not None:
            self.client = PyVisaScpiClient.tcpip(
                ip,
                backend=backend,
                timeout_ms=timeout_ms,
                verbose=verbose,
            )
        else:
            raise ValueError("Either resource, ip, or client must be provided")

    def connect(self) -> None:
        self.client.connect()

    def close(self) -> None:
        self.client.close()

    def write(self, command: str) -> None:
        self.client.write(command)

    def query(self, command: str) -> str:
        return self.client.query(command)

    def get_idn(self) -> str:
        return self.query("*IDN?")

    def reset(self) -> None:
        self.write("*RST")

    def clear_status(self) -> None:
        self.write("*CLS")

    def next_error(self) -> str:
        return self.query("SYSTem:ERRor:NEXT?")

    @staticmethod
    def _validate_channel(channel: int) -> None:
        if channel not in (1, 2):
            raise ValueError("AFG1062 channel must be 1 or 2")

    @staticmethod
    def _parse_bool(value: str) -> bool:
        return value.strip().upper() in {"1", "ON", "TRUE"}

    @staticmethod
    def _clean(value: str) -> str:
        return value.strip().strip('"')

    def get_channel_settings(self, channel: int) -> ChannelSettings:
        self._validate_channel(channel)
        settings = ChannelSettings(channel=channel)
        settings.output = self._parse_bool(self.query(f"OUTPut{channel}:STATe?"))
        settings.waveform = self._clean(self.query(f"SOURce{channel}:FUNCtion:SHAPe?"))
        settings.frequency_hz = float(self.query(f"SOURce{channel}:FREQuency:FIXed?"))
        settings.amplitude_vpp = float(self.query(f"SOURce{channel}:VOLTage:AMPLitude?"))
        settings.offset_v = float(self.query(f"SOURce{channel}:VOLTage:OFFSet?"))
        try:
            settings.phase_rad = float(self.query(f"SOURce{channel}:PHASe:ADJust?"))
        except Exception:
            settings.phase_rad = None
        try:
            settings.duty_cycle_percent = float(self.query(f"SOURce{channel}:PULSe:DCYCle?"))
        except Exception:
            settings.duty_cycle_percent = None
        return settings

    def get_all_settings(self) -> list[ChannelSettings]:
        return [self.get_channel_settings(1), self.get_channel_settings(2)]

    def set_output(self, channel: int, enabled: bool) -> None:
        self._validate_channel(channel)
        self.write(f"OUTPut{channel}:STATe {'ON' if enabled else 'OFF'}")

    def set_waveform(self, channel: int, waveform: str) -> None:
        self._validate_channel(channel)
        self.write(f"SOURce{channel}:FUNCtion:SHAPe {waveform}")

    def set_frequency(self, channel: int, frequency_hz: float) -> None:
        self._validate_channel(channel)
        self.write(f"SOURce{channel}:FREQuency:FIXed {frequency_hz}")

    def set_amplitude(self, channel: int, amplitude_vpp: float) -> None:
        self._validate_channel(channel)
        self.write(f"SOURce{channel}:VOLTage:AMPLitude {amplitude_vpp}")

    def set_offset(self, channel: int, offset_v: float) -> None:
        self._validate_channel(channel)
        self.write(f"SOURce{channel}:VOLTage:OFFSet {offset_v}")

    def set_phase(self, channel: int, phase: float, unit: str = "RAD") -> None:
        self._validate_channel(channel)
        self.write(f"SOURce{channel}:PHASe:ADJust {phase}{unit}")

    def set_duty_cycle(self, channel: int, duty_cycle_percent: float) -> None:
        self._validate_channel(channel)
        self.write(f"SOURce{channel}:PULSe:DCYCle {duty_cycle_percent}")

    def apply_channel_settings(
        self,
        *,
        channel: int,
        output: bool | None = None,
        waveform: str | None = None,
        frequency_hz: float | None = None,
        amplitude_vpp: float | None = None,
        offset_v: float | None = None,
        phase: float | None = None,
        phase_unit: str = "RAD",
        duty_cycle_percent: float | None = None,
    ) -> ChannelSettings:
        self._validate_channel(channel)
        if waveform is not None:
            self.set_waveform(channel, waveform)
        if frequency_hz is not None:
            self.set_frequency(channel, frequency_hz)
        if amplitude_vpp is not None:
            self.set_amplitude(channel, amplitude_vpp)
        if offset_v is not None:
            self.set_offset(channel, offset_v)
        if phase is not None:
            self.set_phase(channel, phase, phase_unit)
        if duty_cycle_percent is not None:
            self.set_duty_cycle(channel, duty_cycle_percent)
        if output is not None:
            self.set_output(channel, output)
        return self.get_channel_settings(channel)
