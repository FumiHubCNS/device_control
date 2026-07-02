from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from device_control.protocol import PyVisaScpiClient, ScpiClient, UsbtmcScpiClient


Waveform = Literal["SIN", "SQU", "RAMP", "PULS", "PRN", "DC"]


WAVEFORM_ALIASES = {
    "SIN": "SINusoid",
    "SINE": "SINusoid",
    "SINUSOID": "SINusoid",
    "SQU": "SQUare",
    "SQUARE": "SQUare",
    "RAMP": "RAMP",
    "PULS": "PULSe",
    "PULSE": "PULSe",
    "PRN": "PRNoise",
    "PRNOISE": "PRNoise",
    "NOIS": "PRNoise",
    "NOISE": "PRNoise",
    "DC": "DC",
}


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
    duty_cycle_error: str | None = None

    def asdict(self) -> dict:
        return asdict(self)


class Afg1062:
    """Tektronix AFG1062 SCPI controller."""

    def __init__(
        self,
        *,
        resource: str | None = None,
        ip: str | None = None,
        usbtmc: str | None = None,
        backend: str = "@py",
        timeout_ms: int = 10000,
        write_termination: str = "\n",
        verbose: bool = False,
        client: ScpiClient | None = None,
    ) -> None:
        if client is not None:
            self.client = client
        elif usbtmc is not None:
            self.client = UsbtmcScpiClient(
                usbtmc,
                timeout_ms=timeout_ms,
                write_termination=write_termination,
                verbose=verbose,
            )
        elif resource is not None:
            self.client = PyVisaScpiClient(
                resource,
                backend=backend,
                timeout_ms=timeout_ms,
                write_termination=write_termination,
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
            raise ValueError("Either resource, ip, usbtmc, or client must be provided")

    def connect(self) -> None:
        self.client.connect()

    def close(self) -> None:
        self.client.close()

    def write(self, command: str) -> None:
        self.client.write(command)

    def query(self, command: str) -> str:
        return self.client.query(command)

    def _checked_write(self, command: str) -> None:
        self.write(command)
        self.raise_on_error(command)

    def get_idn(self) -> str:
        return self.query("*IDN?")

    def reset(self) -> None:
        self.write("*RST")

    def clear_status(self) -> None:
        self.write("*CLS")

    def next_error(self) -> str | None:
        for command in ("SYSTem:ERRor?", "SYSTem:ERRor:NEXT?"):
            try:
                return self.query(command)
            except Exception:
                continue
        return None

    def raise_on_error(self, context: str) -> None:
        error = self.next_error()
        if error is None:
            return
        if not error.startswith("0"):
            raise RuntimeError(f"AFG1062 rejected {context!r}: {error}")

    @staticmethod
    def normalize_waveform(waveform: str) -> str:
        return WAVEFORM_ALIASES.get(waveform.strip().upper(), waveform)

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
        self._checked_write(f"OUTPut{channel}:STATe {'ON' if enabled else 'OFF'}")

    def set_waveform(self, channel: int, waveform: str) -> None:
        self._validate_channel(channel)
        self._checked_write(f"SOURce{channel}:FUNCtion:SHAPe {self.normalize_waveform(waveform)}")

    def set_frequency(self, channel: int, frequency_hz: float) -> None:
        self._validate_channel(channel)
        self._checked_write(f"SOURce{channel}:FREQuency:FIXed {frequency_hz}")

    def set_amplitude(self, channel: int, amplitude_vpp: float) -> None:
        self._validate_channel(channel)
        self._checked_write(f"SOURce{channel}:VOLTage:AMPLitude {amplitude_vpp}Vpp")

    def set_offset(self, channel: int, offset_v: float) -> None:
        self._validate_channel(channel)
        self._checked_write(f"SOURce{channel}:VOLTage:OFFSet {offset_v}V")

    def set_phase(self, channel: int, phase: float, unit: str = "RAD") -> None:
        self._validate_channel(channel)
        self._checked_write(f"SOURce{channel}:PHASe:ADJust {phase}{unit}")

    def set_duty_cycle(self, channel: int, duty_cycle_percent: float) -> None:
        self._validate_channel(channel)
        percent_text = f"{duty_cycle_percent:g}"
        candidates = [
            f"SOURce{channel}:PULSe:DCYCle {percent_text}",
            f"SOURce{channel}:PULSe:DCYCle {percent_text} PCT",
            f"SOURce{channel}:PULSe:DCYCle {percent_text}PCT",
            f"SOURce{channel}:FUNCtion:PULSe:DCYCle {percent_text}",
            f"SOURce{channel}:FUNCtion:PULSe:DCYCle {percent_text} PCT",
        ]
        errors = []
        for command in candidates:
            try:
                self._checked_write(command)
                return
            except Exception as exc:
                errors.append(str(exc))
        raise RuntimeError("; ".join(errors))

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
        try:
            self.clear_status()
        except Exception:
            pass
        normalized_waveform = self.normalize_waveform(waveform) if waveform is not None else None
        if waveform is not None:
            self.set_waveform(channel, normalized_waveform)
        if frequency_hz is not None and normalized_waveform != "DC":
            self.set_frequency(channel, frequency_hz)
        if amplitude_vpp is not None and normalized_waveform != "DC":
            self.set_amplitude(channel, amplitude_vpp)
        if offset_v is not None:
            self.set_offset(channel, offset_v)
        if phase is not None:
            self.set_phase(channel, phase, phase_unit)
        duty_cycle_error = None
        if duty_cycle_percent is not None and normalized_waveform == "PULSe":
            try:
                self.set_duty_cycle(channel, duty_cycle_percent)
            except Exception as exc:
                duty_cycle_error = str(exc)
        if output is not None:
            self.set_output(channel, output)
        settings = self.get_channel_settings(channel)
        settings.duty_cycle_error = duty_cycle_error
        return settings
