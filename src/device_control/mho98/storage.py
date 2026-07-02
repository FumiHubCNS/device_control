from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from .acquisition import WaveformRecord


class ScopeHDF5Writer:
    """Append triggered scope waveform records to an HDF5 file."""

    def __init__(self, path: str | Path, *, mode: str = "w") -> None:
        self.path = Path(path)
        self.h5 = h5py.File(self.path, mode)

        dt_i64 = np.int64
        dt_f64 = np.float64
        dt_vlen_f64 = h5py.vlen_dtype(dt_f64)

        self.ds_trigger = self._dataset(
            "trigger_index", dtype=dt_i64
        )
        self.ds_channel = self._dataset(
            "channel_index", dtype=dt_i64
        )
        self.ds_time = self._dataset(
            "time_us", dtype=dt_vlen_f64
        )
        self.ds_voltage = self._dataset(
            "voltage_mV", dtype=dt_vlen_f64
        )
        self.ds_points = self._dataset(
            "preamble_points", dtype=dt_i64
        )
        self.ds_x_inc = self._dataset(
            "preamble_x_inc_s", dtype=dt_f64
        )
        self.ds_x_ori = self._dataset(
            "preamble_x_ori_s", dtype=dt_f64
        )
        self.ds_y_inc = self._dataset(
            "preamble_y_inc_v_per_count",
            dtype=dt_f64,
        )
        self.ds_y_ori = self._dataset(
            "preamble_y_ori_v", dtype=dt_f64
        )
        self.ds_y_ref = self._dataset(
            "preamble_y_ref", dtype=dt_f64
        )

    def _dataset(self, name: str, *, dtype):
        if name in self.h5:
            return self.h5[name]
        return self.h5.create_dataset(
            name,
            shape=(0,),
            maxshape=(None,),
            dtype=dtype,
            chunks=True,
        )

    def _append_one(self, ds, value) -> None:
        n = len(ds)
        ds.resize((n + 1,))
        ds[n] = value

    def append(self, record: WaveformRecord) -> None:
        self._append_one(self.ds_trigger, int(record.trigger_index))
        self._append_one(self.ds_channel, int(record.channel_index))
        self._append_one(self.ds_time, np.asarray(record.time_us, dtype=np.float64))
        self._append_one(self.ds_voltage, np.asarray(record.voltage_mV, dtype=np.float64))

        preamble = record.preamble
        self._append_one(self.ds_points, int(preamble["points"]))
        self._append_one(self.ds_x_inc, float(preamble["x_inc"]))
        self._append_one(self.ds_x_ori, float(preamble["x_ori"]))
        self._append_one(self.ds_y_inc, float(preamble["y_inc"]))
        self._append_one(self.ds_y_ori, float(preamble["y_ori"]))
        self._append_one(self.ds_y_ref, float(preamble["y_ref"]))
        self.h5.flush()

    def append_many(self, records: list[WaveformRecord]) -> None:
        for record in records:
            self.append(record)

    def close(self) -> None:
        self.h5.close()

    def __enter__(self) -> ScopeHDF5Writer:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
