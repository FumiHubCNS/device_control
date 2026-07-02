from __future__ import annotations

import argparse
import asyncio
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from device_control.webui import page

from .acquisition import RigolScope, WaveformRecord
from .storage import ScopeHDF5Writer


class ConnectRequest(BaseModel):
    ip: str = "172.16.206.60"
    backend: str = "@py"
    timeout_ms: int = Field(default=60000, ge=1000, le=120000)


class SetupRequest(BaseModel):
    points: int = Field(default=1000, ge=1, le=1_000_000)
    mode: str = "NORMal"
    fmt: str = "BYTE"


class AcquireRequest(BaseModel):
    channels: list[int] = Field(default_factory=lambda: [1, 2, 3, 4])
    timeout_s: float = Field(default=30.0, gt=0)
    save: bool = False
    output_file: Optional[str] = None


@dataclass
class ScopeWebState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    scope: RigolScope | None = None
    ip: str | None = None
    idn: str | None = None
    connected: bool = False
    trigger_index: int = 0
    last_records: list[WaveformRecord] = field(default_factory=list)
    last_error: str | None = None

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "ip": self.ip,
            "idn": self.idn,
            "trigger_index": self.trigger_index,
            "last_error": self.last_error,
            "last_channels": [r.channel_index for r in self.last_records],
        }


def _html(default_ip: str) -> str:
    body = f"""
    <header>
      <h1>Oscilloscope Triggered DAQ</h1>
      <div class="row">
        <span>Device: <span id="deviceStatus" class="ng">disconnected</span></span>
        <span id="idn"></span>
      </div>
    </header>

    <section>
      <h2>Connection</h2>
      <div class="row">
        <label for="ip">IP</label>
        <input id="ip" value="{default_ip}" />
        <label for="backend">VISA backend</label>
        <input id="backend" value="@py" />
        <label for="connectTimeoutMs">VISA timeout [ms]</label>
        <input id="connectTimeoutMs" type="number" min="1000" max="120000" step="1000" value="60000" />
        <button class="primary" onclick="connectScope()">Connect</button>
        <button onclick="disconnectScope()">Disconnect</button>
      </div>
    </section>

    <section>
      <h2>Waveform Setup</h2>
      <div class="row">
        <label for="points">Points</label>
        <input id="points" type="number" min="1" step="1" value="1000" />
        <label for="mode">Mode</label>
        <input id="mode" value="NORMal" />
        <label for="fmt">Format</label>
        <input id="fmt" value="BYTE" />
        <button onclick="setupWaveform()">Apply</button>
      </div>
    </section>

    <section>
      <h2>Acquire</h2>
      <div class="row">
        <label for="channels">Channels</label>
        <input id="channels" value="1 2 3 4" />
        <label for="timeout">Timeout [s]</label>
        <input id="timeout" type="number" min="0.1" step="0.1" value="30" />
        <label for="outputFile">HDF5</label>
        <input id="outputFile" value="scope_data.h5" />
        <label><input id="save" type="checkbox" /> Save</label>
        <button class="safe" id="acquireButton" onclick="acquireOne()">Acquire one trigger</button>
      </div>
    </section>

    <section>
      <h2>Latest Waveforms</h2>
      <canvas id="plot" width="1200" height="520"></canvas>
    </section>

    <section>
      <h2>Status JSON</h2>
      <pre id="json">{{}}</pre>
    </section>
    """
    script = """
let latestRecords = [];

function setStatus(data) {
  const device = document.getElementById("deviceStatus");
  device.textContent = data.connected ? "connected" : "disconnected";
  device.className = data.connected ? "ok" : "ng";
  document.getElementById("idn").textContent = data.idn || "";
  document.getElementById("json").textContent = JSON.stringify(data, null, 2);
}

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

async function refreshStatus() {
  try {
    setStatus(await getJSON("/api/status"));
  } catch (err) {
    document.getElementById("json").textContent = String(err);
  }
}

async function connectScope() {
  try {
    const data = await postJSON("/api/connect", {
      ip: document.getElementById("ip").value,
      backend: document.getElementById("backend").value,
      timeout_ms: Number(document.getElementById("connectTimeoutMs").value),
    });
    setStatus(data);
  } catch (err) {
    alert(String(err));
  }
}

async function disconnectScope() {
  try {
    setStatus(await postJSON("/api/disconnect", {}));
  } catch (err) {
    alert(String(err));
  }
}

async function setupWaveform() {
  try {
    setStatus(await postJSON("/api/setup", {
      points: Number(document.getElementById("points").value),
      mode: document.getElementById("mode").value,
      fmt: document.getElementById("fmt").value,
    }));
  } catch (err) {
    alert(String(err));
  }
}

function parseChannels(value) {
  return value.split(/[ ,]+/).filter(Boolean).map(v => Number(v));
}

async function acquireOne() {
  const button = document.getElementById("acquireButton");
  button.disabled = true;
  try {
    const data = await postJSON("/api/acquire", {
      channels: parseChannels(document.getElementById("channels").value),
      timeout_s: Number(document.getElementById("timeout").value),
      save: document.getElementById("save").checked,
      output_file: document.getElementById("outputFile").value,
    });
    latestRecords = data.records || [];
    drawWaveforms();
    setStatus(data.status);
  } catch (err) {
    alert(String(err));
  } finally {
    button.disabled = false;
  }
}

function extent(values) {
  let min = Infinity;
  let max = -Infinity;
  for (const v of values) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) return [min - 1, max + 1];
  return [min, max];
}

function drawPanel(ctx, record, x, y, w, h, color) {
  const t = record.time_us || [];
  const v = record.voltage_mV || [];
  ctx.strokeStyle = "#d8dde3";
  ctx.strokeRect(x, y, w, h);
  ctx.fillStyle = "#202124";
  ctx.font = "15px system-ui";
  ctx.fillText(`CH${record.channel_index} trigger=${record.trigger_index}`, x + 10, y + 22);

  if (t.length < 2 || v.length < 2) {
    ctx.fillStyle = "#687076";
    ctx.fillText("no data", x + 10, y + 48);
    return;
  }

  const [tMin, tMax] = extent(t);
  const [vMin, vMax] = extent(v);
  const px = (tv) => x + ((tv - tMin) / (tMax - tMin)) * w;
  const py = (vv) => y + h - ((vv - vMin) / (vMax - vMin)) * h;

  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(px(t[0]), py(v[0]));
  for (let i = 1; i < t.length; i += 1) ctx.lineTo(px(t[i]), py(v[i]));
  ctx.stroke();

  ctx.fillStyle = "#687076";
  ctx.font = "12px system-ui";
  ctx.fillText(`${tMin.toFixed(3)} to ${tMax.toFixed(3)} us`, x + 10, y + h - 10);
  ctx.fillText(`${vMin.toFixed(1)} to ${vMax.toFixed(1)} mV`, x + w - 160, y + h - 10);
}

function drawWaveforms() {
  const canvas = document.getElementById("plot");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (latestRecords.length === 0) {
    ctx.fillStyle = "#687076";
    ctx.font = "18px system-ui";
    ctx.fillText("No waveform acquired yet", 24, 44);
    return;
  }

  const colors = ["#1769e0", "#188038", "#d93025", "#7a4cc2"];
  const gap = 20;
  const panelW = (canvas.width - gap * 3) / 2;
  const panelH = (canvas.height - gap * 3) / 2;
  latestRecords.slice(0, 4).forEach((record, index) => {
    const col = index % 2;
    const row = Math.floor(index / 2);
    drawPanel(
      ctx,
      record,
      gap + col * (panelW + gap),
      gap + row * (panelH + gap),
      panelW,
      panelH,
      colors[index % colors.length],
    );
  });
}

refreshStatus();
drawWaveforms();
"""
    return page("Oscilloscope Triggered DAQ", body, script)


def create_app(default_ip: str = "172.16.206.60") -> FastAPI:
    app = FastAPI(title="Oscilloscope Triggered DAQ")
    state = ScopeWebState(ip=default_ip)

    def require_scope() -> RigolScope:
        if state.scope is None or not state.connected:
            raise RuntimeError("Oscilloscope is not connected")
        return state.scope

    def connect_sync(req: ConnectRequest) -> dict:
        with state.lock:
            if state.scope is not None:
                state.scope.close()

            scope = RigolScope(
                ip=req.ip,
                timeout_ms=req.timeout_ms,
                backend=req.backend,
            )
            scope.connect()
            state.scope = scope
            state.ip = req.ip
            state.idn = scope.get_idn()
            state.connected = True
            state.last_error = None
            return state.status()

    def disconnect_sync() -> dict:
        with state.lock:
            if state.scope is not None:
                state.scope.close()
            state.scope = None
            state.connected = False
            return state.status()

    def setup_sync(req: SetupRequest) -> dict:
        with state.lock:
            scope = require_scope()
            scope.setup_waveform_transfer(points=req.points, mode=req.mode, fmt=req.fmt)
            state.last_error = None
            return state.status()

    def acquire_sync(req: AcquireRequest) -> dict:
        with state.lock:
            scope = require_scope()
            records = scope.acquire_one_trigger_all_channels(
                trigger_index=state.trigger_index,
                channels=req.channels,
                timeout_s=req.timeout_s,
            )
            state.trigger_index += 1
            state.last_records = records
            state.last_error = None

            if req.save:
                output_file = req.output_file or "scope_data.h5"
                with ScopeHDF5Writer(Path(output_file), mode="a") as writer:
                    writer.append_many(records)

            return {
                "status": state.status(),
                "records": [record.to_jsonable() for record in records],
            }

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await asyncio.to_thread(disconnect_sync)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _html(default_ip)

    @app.get("/api/status")
    async def status() -> dict:
        return state.status()

    @app.post("/api/connect")
    async def connect(req: ConnectRequest) -> dict:
        try:
            return await asyncio.to_thread(connect_sync, req)
        except Exception as exc:
            state.last_error = str(exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/disconnect")
    async def disconnect() -> dict:
        try:
            return await asyncio.to_thread(disconnect_sync)
        except Exception as exc:
            state.last_error = str(exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/setup")
    async def setup(req: SetupRequest) -> dict:
        try:
            return await asyncio.to_thread(setup_sync, req)
        except Exception as exc:
            state.last_error = str(exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/acquire")
    async def acquire(req: AcquireRequest) -> dict:
        try:
            return await asyncio.to_thread(acquire_sync, req)
        except Exception as exc:
            state.last_error = str(exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run oscilloscope triggered DAQ WebUI")
    parser.add_argument("--ip", default="172.16.206.60", help="Default oscilloscope IP")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8082, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload")
    args = parser.parse_args(argv)

    import uvicorn

    app = create_app(default_ip=args.ip)
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
