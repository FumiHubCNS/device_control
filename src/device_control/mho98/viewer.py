from __future__ import annotations

from multiprocessing import Process, Queue
import queue as queue_module

import numpy as np


def _run_scope_viewer(data_queue: Queue, interval_ms: int = 50) -> None:
    import pyqtgraph as pg
    from pyqtgraph.Qt import QtCore, QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])

    win = pg.GraphicsLayoutWidget(show=True, title="Scope Streaming Viewer")
    win.resize(1400, 900)

    plots = {}
    curves = {}
    latest = {}

    for ch in [1, 2, 3, 4]:
        row = 0 if ch in (1, 2) else 1
        col = 0 if ch in (1, 3) else 1

        plot = win.addPlot(row=row, col=col)
        plot.setTitle(f"CH{ch}")
        plot.setLabel("left", "Voltage [mV]")
        plot.setLabel("bottom", "Time [us]")
        plot.showGrid(x=True, y=True)

        curve = plot.plot(pen=pg.mkPen(width=1.5))
        plots[ch] = plot
        curves[ch] = curve

    def update() -> None:
        updated_channels = set()

        while True:
            try:
                item = data_queue.get_nowait()
            except queue_module.Empty:
                break

            if item is None:
                app.quit()
                return

            if not isinstance(item, dict) or item.get("type") != "scope_waveform":
                continue

            ch = int(item["channel"])
            latest[ch] = {
                "trigger": int(item["trigger"]),
                "time_us": np.asarray(item["time_us"], dtype=float),
                "voltage_mV": np.asarray(item["voltage_mV"], dtype=float),
            }
            updated_channels.add(ch)

        for ch in updated_channels:
            payload = latest[ch]
            curves[ch].setData(x=payload["time_us"], y=payload["voltage_mV"])
            plots[ch].setTitle(f"CH{ch}  trigger={payload['trigger']}")

    timer = QtCore.QTimer()
    timer.timeout.connect(update)
    timer.start(interval_ms)

    pg.exec()


def launch_scope_viewer(interval_ms: int = 50) -> tuple[Process, Queue]:
    q: Queue = Queue()
    p = Process(
        target=_run_scope_viewer,
        kwargs={"data_queue": q, "interval_ms": interval_ms},
        daemon=True,
    )
    p.start()
    return p, q


def queue_waveform(
    data_queue: Queue,
    trigger_index: int,
    channel_index: int,
    time_us,
    voltage_mV,
) -> None:
    data_queue.put(
        {
            "type": "scope_waveform",
            "trigger": int(trigger_index),
            "channel": int(channel_index),
            "time_us": np.asarray(time_us, dtype=np.float64),
            "voltage_mV": np.asarray(voltage_mV, dtype=np.float64),
        }
    )
