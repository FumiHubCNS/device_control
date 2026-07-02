from __future__ import annotations

import csv
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from device_control.protocol import PyVisaScpiClient, ScpiClient


@dataclass
class ChannelConfig:
    channel: int
    display: bool | None = None
    scale_v: float | None = None
    position_div: float | None = None
    offset_v: float | None = None
    coupling: str | None = None
    bandwidth: str | None = None

    def asdict(self) -> dict:
        return asdict(self)


@dataclass
class TriggerConfig:
    trigger_type: str | None = None
    source: str | None = None
    slope: str | None = None
    level_v: float | None = None
    mode: str | None = None

    def asdict(self) -> dict:
        return asdict(self)


@dataclass
class Waveform:
    channel: int
    time_s: np.ndarray
    voltage_v: np.ndarray
    preamble: dict

    def to_jsonable(self) -> dict:
        return {
            "channel": int(self.channel),
            "time_s": self.time_s.astype(float).tolist(),
            "voltage_v": self.voltage_v.astype(float).tolist(),
            "preamble": self.preamble,
        }


class Mdo3034:
    """Tektronix MDO3034 SCPI controller."""

    def __init__(
        self,
        *,
        resource: str | None = None,
        ip: str | None = None,
        socket: bool = False,
        socket_port: int = 4000,
        backend: str = "@py",
        timeout_ms: int = 20000,
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
        elif ip is not None and socket:
            self.client = PyVisaScpiClient.tcpip_socket(
                ip,
                port=socket_port,
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

    @staticmethod
    def _validate_channel(channel: int) -> None:
        if channel not in (1, 2, 3, 4):
            raise ValueError("MDO3034 channel must be 1, 2, 3, or 4")

    @staticmethod
    def _parse_bool(value: str) -> bool:
        return value.strip().upper() in {"1", "ON", "TRUE"}

    @staticmethod
    def _clean(value: str) -> str:
        return value.strip().strip('"')

    def _query_optional(self, command: str) -> str | None:
        try:
            return self._clean(self.query(command))
        except Exception:
            return None

    def _query_float_optional(self, command: str) -> float | None:
        try:
            return float(self.query(command))
        except Exception:
            return None

    def get_channel_config(self, channel: int) -> ChannelConfig:
        self._validate_channel(channel)
        display_raw = self._query_optional(f"SELect:CH{channel}?")
        return ChannelConfig(
            channel=channel,
            display=self._parse_bool(display_raw) if display_raw is not None else None,
            scale_v=self._query_float_optional(f"CH{channel}:SCAle?"),
            position_div=self._query_float_optional(f"CH{channel}:POSition?"),
            offset_v=self._query_float_optional(f"CH{channel}:OFFSet?"),
            coupling=self._query_optional(f"CH{channel}:COUPling?"),
            bandwidth=self._query_optional(f"CH{channel}:BANdwidth?"),
        )

    def get_all_channel_configs(self) -> list[ChannelConfig]:
        return [self.get_channel_config(channel) for channel in (1, 2, 3, 4)]

    def apply_channel_config(
        self,
        *,
        channel: int,
        display: bool | None = None,
        scale_v: float | None = None,
        position_div: float | None = None,
        offset_v: float | None = None,
        coupling: str | None = None,
        bandwidth: str | None = None,
    ) -> ChannelConfig:
        self._validate_channel(channel)
        if display is not None:
            self.write(f"SELect:CH{channel} {'ON' if display else 'OFF'}")
        if scale_v is not None:
            self.write(f"CH{channel}:SCAle {scale_v}")
        if position_div is not None:
            self.write(f"CH{channel}:POSition {position_div}")
        if offset_v is not None:
            self.write(f"CH{channel}:OFFSet {offset_v}")
        if coupling:
            self.write(f"CH{channel}:COUPling {coupling}")
        if bandwidth:
            self.write(f"CH{channel}:BANdwidth {bandwidth}")
        return self.get_channel_config(channel)

    def get_trigger_config(self) -> TriggerConfig:
        return TriggerConfig(
            trigger_type=self._query_optional("TRIGger:A:TYPe?"),
            source=self._query_optional("TRIGger:A:EDGE:SOUrce?"),
            slope=self._query_optional("TRIGger:A:EDGE:SLOpe?"),
            level_v=self._query_float_optional("TRIGger:A:LEVel?"),
            mode=self._query_optional("TRIGger:A:MODe?"),
        )

    def apply_trigger_config(
        self,
        *,
        source: str | None = None,
        slope: str | None = None,
        level_v: float | None = None,
        mode: str | None = None,
    ) -> TriggerConfig:
        self.write("TRIGger:A:TYPe EDGE")
        if source:
            self.write(f"TRIGger:A:EDGE:SOUrce {source}")
        if slope:
            self.write(f"TRIGger:A:EDGE:SLOpe {slope}")
        if level_v is not None:
            self.write(f"TRIGger:A:LEVel {level_v}")
        if mode:
            self.write(f"TRIGger:A:MODe {mode}")
        return self.get_trigger_config()

    def setup_ascii_waveform_transfer(self, *, start: int = 1, stop: int = 10000) -> None:
        self.write("DATa:ENCdg ASCII")
        self.write("DATa:WIDth 1")
        self.write(f"DATa:STARt {start}")
        self.write(f"DATa:STOP {stop}")

    def record_length(self) -> int | None:
        for command in ("HORizontal:RECOrdlength?", "HORizontal:RECOrdlength:ACTual?"):
            value = self._query_float_optional(command)
            if value is not None:
                return max(1, int(value))
        return None

    def get_waveform_point_info(self, channel: int) -> dict:
        self._validate_channel(channel)
        self.write(f"DATa:SOUrce CH{channel}")
        record_length = self.record_length()
        if record_length is not None:
            self.setup_ascii_waveform_transfer(start=1, stop=record_length)
        return {
            "point_offset": float(self.query("WFMOutpre:PT_Off?")),
            "nr_points": self._query_float_optional("WFMOutpre:NR_Pt?"),
            "record_length": record_length,
        }

    def trigger_window_bounds(
        self,
        channel: int,
        *,
        pretrigger_points: int,
        posttrigger_points: int,
    ) -> tuple[int, int, dict]:
        info = self.get_waveform_point_info(channel)
        trigger_zero_based = max(0, round(info["point_offset"]))
        start_zero_based = max(0, trigger_zero_based - pretrigger_points)
        stop_zero_based = trigger_zero_based + posttrigger_points
        if info["nr_points"] is not None:
            stop_zero_based = min(stop_zero_based, max(0, int(info["nr_points"]) - 1))
        start = start_zero_based + 1
        stop = max(start, stop_zero_based + 1)
        return start, stop, info

    def arm_single(self) -> None:
        self.write("ACQuire:STOPAfter SEQuence")
        self.write("ACQuire:STATE RUN")

    def resume_continuous(self) -> None:
        self.write("ACQuire:STOPAfter RUNSTop")
        self.write("ACQuire:STATE RUN")

    def reset_stop_after(self) -> None:
        self.write("ACQuire:STOPAfter RUNSTop")

    def wait_for_acquisition_complete(
        self,
        *,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.1,
    ) -> None:
        started_at = time.time()
        last_state = None
        while True:
            state = self.query("ACQuire:STATE?").strip()
            last_state = state
            if state in {"0", "OFF", "STOP"}:
                return
            if time.time() - started_at > timeout_s:
                trigger_state = self._query_optional("TRIGger:STATE?")
                raise TimeoutError(
                    "MDO3034 acquisition timed out "
                    f"(last acquisition state={last_state!r}, trigger state={trigger_state!r}). "
                    "If no trigger is expected, disable Single to read the current waveform."
                )
            time.sleep(poll_interval_s)

    def read_waveform(self, channel: int, *, start: int = 1, stop: int = 10000) -> Waveform:
        self._validate_channel(channel)
        self.write(f"DATa:SOUrce CH{channel}")
        self.setup_ascii_waveform_transfer(start=start, stop=stop)

        xincr = float(self.query("WFMOutpre:XINcr?"))
        xzero = float(self.query("WFMOutpre:XZEro?"))
        pt_off = float(self.query("WFMOutpre:PT_Off?"))
        ymult = float(self.query("WFMOutpre:YMUlt?"))
        yzero = float(self.query("WFMOutpre:YZEro?"))
        yoff = float(self.query("WFMOutpre:YOFF?"))
        nr_pt = self._query_float_optional("WFMOutpre:NR_Pt?")

        raw = self.query("CURVe?")
        raw_values = np.fromstring(raw.replace("\n", ""), sep=",", dtype=np.float64)
        indices = np.arange(start - 1, start - 1 + raw_values.size, dtype=np.float64)
        time_s = xzero + (indices - pt_off) * xincr
        voltage_v = (raw_values - yoff) * ymult + yzero
        return Waveform(
            channel=channel,
            time_s=time_s,
            voltage_v=voltage_v,
            preamble={
                "x_increment_s": xincr,
                "x_zero_s": xzero,
                "point_offset": pt_off,
                "y_multiplier_v": ymult,
                "y_zero_v": yzero,
                "y_offset": yoff,
                "nr_points": nr_pt,
                "start": start,
                "stop": stop,
                "trigger_point": pt_off + 1,
            },
        )

    def read_waveform_around_trigger(
        self,
        channel: int,
        *,
        pretrigger_points: int = 1000,
        posttrigger_points: int = 1000,
    ) -> Waveform:
        start, stop, info = self.trigger_window_bounds(
            channel,
            pretrigger_points=pretrigger_points,
            posttrigger_points=posttrigger_points,
        )
        waveform = self.read_waveform(channel, start=start, stop=stop)
        waveform.preamble["trigger_window"] = {
            "requested_pretrigger_points": pretrigger_points,
            "requested_posttrigger_points": posttrigger_points,
            "actual_start": start,
            "actual_stop": stop,
            "point_info": info,
        }
        return waveform

    def acquire_waveforms(
        self,
        *,
        channels: list[int],
        start: int = 1,
        stop: int = 10000,
        single: bool = True,
        timeout_s: float = 30.0,
        trigger_window: bool = False,
        pretrigger_points: int = 1000,
        posttrigger_points: int = 1000,
    ) -> list[Waveform]:
        if single:
            self.arm_single()
            try:
                self.wait_for_acquisition_complete(timeout_s=timeout_s)
            finally:
                self.reset_stop_after()
        else:
            self.resume_continuous()
        if trigger_window:
            return [
                self.read_waveform_around_trigger(
                    channel,
                    pretrigger_points=pretrigger_points,
                    posttrigger_points=posttrigger_points,
                )
                for channel in channels
            ]
        return [self.read_waveform(channel, start=start, stop=stop) for channel in channels]


def timestamped_csv_path(directory: str | Path = ".") -> Path:
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(directory) / f"{now}.csv"


def write_waveforms_csv(path: str | Path, waveforms: list[Waveform]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    max_len = max((len(w.time_s) for w in waveforms), default=0)
    by_channel = {waveform.channel: waveform for waveform in waveforms}
    channels = sorted(by_channel)

    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        header = ["sample_index"]
        for channel in channels:
            header.extend([f"ch{channel}_time_s", f"ch{channel}_voltage_v"])
        writer.writerow(header)

        for index in range(max_len):
            row: list[float | int | str] = [index]
            for channel in channels:
                waveform = by_channel[channel]
                if index < len(waveform.time_s):
                    row.extend(
                        [
                            float(waveform.time_s[index]),
                            float(waveform.voltage_v[index]),
                        ]
                    )
                else:
                    row.extend(["", ""])
            writer.writerow(row)
    return path
