from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from device_control.protocol import PyVisaScpiClient, ScpiClient, extract_definite_block_payload


@dataclass
class WaveformRecord:
    trigger_index: int
    channel_index: int
    time_us: np.ndarray
    voltage_mV: np.ndarray
    preamble: dict

    def to_jsonable(self) -> dict:
        return {
            "trigger_index": int(self.trigger_index),
            "channel_index": int(self.channel_index),
            "time_us": self.time_us.astype(float).tolist(),
            "voltage_mV": self.voltage_mV.astype(float).tolist(),
            "preamble": self.preamble,
        }


class RigolScope:
    def __init__(
        self,
        ip: str,
        timeout_ms: int = 10000,
        backend: str = "@py",
        verbose: bool = False,
        client: ScpiClient | None = None,
    ) -> None:
        self.ip = ip
        self.timeout_ms = timeout_ms
        self.backend = backend
        self.verbose = verbose
        self.client = client or PyVisaScpiClient.tcpip(
            ip,
            timeout_ms=timeout_ms,
            backend=backend,
            verbose=verbose,
        )

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def _write(self, cmd: str) -> None:
        self.client.write(cmd)

    def _query(self, cmd: str) -> str:
        return self.client.query(cmd)

    def connect(self) -> None:
        self.client.connect()

    def close(self) -> None:
        self.client.close()

    def get_idn(self) -> str:
        return self._query("*IDN?")

    def setup_waveform_transfer(
        self,
        points: int = 1000,
        mode: str = "NORMal",
        fmt: str = "BYTE",
    ) -> None:
        self._write(f":WAVeform:FORMat {fmt}")
        self._write(f":WAVeform:MODE {mode}")
        self._write(f":WAVeform:POINts {points}")

    def arm_single(self) -> None:
        self._write(":SINGle")

    def wait_for_single_trigger(
        self,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.05,
    ) -> str:
        t0 = time.time()
        while True:
            status = self._query(":TRIGger:STATus?")
            if status in ("TD", "STOP"):
                return status

            if time.time() - t0 > timeout_s:
                raise TimeoutError("Single trigger timed out.")

            time.sleep(poll_interval_s)

    @staticmethod
    def parse_preamble(preamble: str) -> dict:
        parts = [p.strip() for p in preamble.split(",")]
        values = list(map(float, parts))

        return {
            "format": int(values[0]),
            "type": int(values[1]),
            "points": int(values[2]),
            "count": int(values[3]),
            "x_inc": values[4],
            "x_ori": values[5],
            "x_ref": values[6],
            "y_inc": values[7],
            "y_ori": values[8],
            "y_ref": values[9],
            "source_requested": None,
            "source_actual": None,
            "valid": False,
            "error": None,
        }

    @staticmethod
    def _empty_preamble(ch: int, error: str | None = None) -> dict:
        return {
            "format": None,
            "type": None,
            "points": 0,
            "count": None,
            "x_inc": None,
            "x_ori": None,
            "x_ref": None,
            "y_inc": None,
            "y_ori": None,
            "y_ref": None,
            "source_requested": ch,
            "source_actual": None,
            "valid": False,
            "error": error,
        }

    def read_channel_waveform(self, ch: int) -> tuple[np.ndarray, np.ndarray, dict]:
        empty_time = np.array([], dtype=np.float64)
        empty_voltage = np.array([], dtype=np.float64)
        empty_preamble = self._empty_preamble(ch)

        try:
            self._write(f":WAVeform:SOURce CHANnel{ch}")

            actual_source = self._query(":WAVeform:SOURce?").strip()
            actual_upper = actual_source.upper()
            expected_candidates = {f"CHAN{ch}", f"CHANNEL{ch}", f"CH{ch}"}

            if actual_upper not in expected_candidates:
                empty_preamble["source_actual"] = actual_source
                empty_preamble["error"] = (
                    f"Waveform source mismatch: requested CH{ch}, got {actual_source}"
                )
                self._log(empty_preamble["error"])
                return empty_time, empty_voltage, empty_preamble

            preamble_raw = self._query(":WAVeform:PREamble?")
            preamble = self.parse_preamble(preamble_raw)
            preamble["source_requested"] = ch
            preamble["source_actual"] = actual_source

            self._write(":WAVeform:DATA?")
            raw = self.client.read_raw()
            payload = extract_definite_block_payload(raw)
            data = np.frombuffer(payload, dtype=np.uint8).astype(np.float64)

            if data.size == 0:
                preamble["error"] = f"No waveform payload for CH{ch}"
                self._log(preamble["error"])
                return empty_time, empty_voltage, preamble

            voltages_mV = (
                (data - preamble["y_ori"] - preamble["y_ref"])
                * preamble["y_inc"]
                * 1e3
            )
            times_us = (
                np.arange(len(data), dtype=np.float64) * preamble["x_inc"]
                + preamble["x_ori"]
            ) * 1e6

            preamble["valid"] = True
            return times_us, voltages_mV, preamble

        except Exception as exc:
            empty_preamble["error"] = str(exc)
            self._log(f"read_channel_waveform(CH{ch}) failed: {exc}")
            return empty_time, empty_voltage, empty_preamble

    def acquire_one_trigger_all_channels(
        self,
        trigger_index: int,
        channels: Iterable[int],
        timeout_s: float = 30.0,
    ) -> list[WaveformRecord]:
        self.arm_single()
        self.wait_for_single_trigger(timeout_s=timeout_s)

        records: list[WaveformRecord] = []
        for ch in channels:
            time_us, voltage_mV, preamble = self.read_channel_waveform(ch)
            if not preamble.get("valid", False):
                self._log(f"Skip CH{ch}: {preamble.get('error')}")
                continue

            records.append(
                WaveformRecord(
                    trigger_index=trigger_index,
                    channel_index=ch,
                    time_us=time_us,
                    voltage_mV=voltage_mV,
                    preamble=preamble,
                )
            )

        return records
