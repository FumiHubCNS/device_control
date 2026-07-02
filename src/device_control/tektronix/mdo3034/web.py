from __future__ import annotations

import argparse
import asyncio
import threading
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from device_control.webui import page

from .driver import Mdo3034, timestamped_csv_path, write_waveforms_csv


class ConnectRequest(BaseModel):
    resource: str | None = None
    ip: str | None = None
    socket: bool = False
    socket_port: int = Field(default=4000, ge=1, le=65535)
    backend: str = "@py"
    timeout_ms: int = Field(default=20000, ge=1000, le=120000)


class ChannelRequest(BaseModel):
    channel: int = Field(ge=1, le=4)
    display: bool | None = None
    scale_v: float | None = Field(default=None, gt=0)
    position_div: float | None = None
    offset_v: float | None = None
    coupling: str | None = None
    bandwidth: str | None = None


class TriggerRequest(BaseModel):
    source: str | None = None
    slope: str | None = None
    level_v: float | None = None
    mode: str | None = None


class AcquireRequest(BaseModel):
    channels: list[int] = Field(default_factory=lambda: [1, 2, 3, 4])
    start: int = Field(default=1, ge=1)
    stop: int = Field(default=10000, ge=1)
    single: bool = True
    timeout_s: float = Field(default=30.0, gt=0)
    save: bool = False
    save_directory: str = "."


@dataclass
class MdoWebState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    scope: Mdo3034 | None = None
    connected: bool = False
    idn: str | None = None
    last_error: str | None = None
    last_csv: str | None = None

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "idn": self.idn,
            "last_error": self.last_error,
            "last_csv": self.last_csv,
        }


def _html(default_ip: str | None, default_resource: str | None) -> str:
    body = f"""
    <header>
      <h1>Tektronix MDO3034</h1>
      <div class="row">
        <span>Device: <span id="deviceStatus" class="ng">disconnected</span></span>
        <span id="idn"></span>
        <span id="lastCsv"></span>
      </div>
    </header>

    <section>
      <h2>Connection</h2>
      <div class="row">
        <label for="resource">VISA resource</label>
        <input id="resource" value="{default_resource or ''}" placeholder="TCPIP0::...::INSTR" />
        <label for="ip">IP</label>
        <input id="ip" value="{default_ip or ''}" />
        <label><input id="socket" type="checkbox" /> Socket</label>
        <label for="socketPort">Port</label>
        <input id="socketPort" type="number" min="1" max="65535" value="4000" />
        <button class="primary" onclick="connectScope()">Connect</button>
        <button onclick="disconnectScope()">Disconnect</button>
        <button onclick="refreshConfig()">Refresh</button>
      </div>
    </section>

    <section>
      <h2>Channels</h2>
      <div class="grid" id="channels"></div>
    </section>

    <section>
      <h2>Trigger</h2>
      <div class="row">
        <label for="trigSource">Source</label>
        <select id="trigSource">
          <option>CH1</option><option>CH2</option><option>CH3</option><option>CH4</option>
        </select>
        <label for="trigSlope">Slope</label>
        <select id="trigSlope"><option>RISe</option><option>FALL</option><option>EITher</option></select>
        <label for="trigLevel">Level [V]</label>
        <input id="trigLevel" type="number" step="any" value="0" />
        <label for="trigMode">Mode</label>
        <select id="trigMode"><option>AUTO</option><option>NORMal</option></select>
        <button class="safe" onclick="applyTrigger()">Apply Trigger</button>
      </div>
    </section>

    <section>
      <h2>Acquire</h2>
      <div class="row">
        <label for="acqChannels">Channels</label>
        <input id="acqChannels" value="1 2 3 4" />
        <label for="start">Start</label>
        <input id="start" type="number" min="1" value="1" />
        <label for="stop">Stop</label>
        <input id="stop" type="number" min="1" value="10000" />
        <label for="timeout">Timeout [s]</label>
        <input id="timeout" type="number" min="0.1" step="0.1" value="30" />
        <label><input id="single" type="checkbox" checked /> Single</label>
        <label><input id="save" type="checkbox" /> Save CSV</label>
        <label for="saveDir">Dir</label>
        <input id="saveDir" value="." />
        <button class="primary" id="acquireButton" onclick="acquire()">Acquire</button>
      </div>
    </section>

    <section>
      <h2>Waveforms</h2>
      <canvas id="plot" width="1200" height="560"></canvas>
    </section>

    <section>
      <h2>Status JSON</h2>
      <pre id="json">{{}}</pre>
    </section>
    """
    script = """
let latestWaveforms = [];

function setStatus(data) {
  const status = data.status || data;
  const device = document.getElementById("deviceStatus");
  device.textContent = status.connected ? "connected" : "disconnected";
  device.className = status.connected ? "ok" : "ng";
  document.getElementById("idn").textContent = status.idn || "";
  document.getElementById("lastCsv").textContent = status.last_csv ? `CSV: ${status.last_csv}` : "";
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

function selectOptions(values, selected) {
  return values.map(v => `<option value="${v}" ${String(v).toUpperCase() === String(selected || "").toUpperCase() ? "selected" : ""}>${v}</option>`).join("");
}

function renderChannels(configs = []) {
  const root = document.getElementById("channels");
  root.innerHTML = "";
  for (const channel of [1, 2, 3, 4]) {
    const cfg = configs.find(item => item.channel === channel) || {};
    const item = document.createElement("div");
    item.className = "metric";
    item.innerHTML = `
      <h2>CH${channel}</h2>
      <div class="row">
        <label><input id="ch${channel}_display" type="checkbox" ${cfg.display ? "checked" : ""} /> Display</label>
      </div>
      <div class="row">
        <label>Scale [V/div]</label>
        <input id="ch${channel}_scale" type="number" min="0" step="any" value="${cfg.scale_v ?? 1}" />
      </div>
      <div class="row">
        <label>Position [div]</label>
        <input id="ch${channel}_position" type="number" step="any" value="${cfg.position_div ?? 0}" />
      </div>
      <div class="row">
        <label>Offset [V]</label>
        <input id="ch${channel}_offset" type="number" step="any" value="${cfg.offset_v ?? 0}" />
      </div>
      <div class="row">
        <label>Coupling</label>
        <select id="ch${channel}_coupling">${selectOptions(["DC", "AC", "GND"], cfg.coupling || "DC")}</select>
        <label>BW</label>
        <input id="ch${channel}_bandwidth" value="${cfg.bandwidth ?? ""}" placeholder="FULL or 20E6" />
      </div>
      <div class="row">
        <button class="safe" onclick="applyChannel(${channel})">Apply CH${channel}</button>
      </div>
    `;
    root.appendChild(item);
  }
}

function renderConfig(data) {
  setStatus(data);
  renderChannels(data.channels || []);
  const trig = data.trigger || {};
  if (trig.source) document.getElementById("trigSource").value = trig.source;
  if (trig.slope) document.getElementById("trigSlope").value = trig.slope;
  if (trig.level_v != null) document.getElementById("trigLevel").value = trig.level_v;
  if (trig.mode) document.getElementById("trigMode").value = trig.mode;
}

async function refreshConfig() {
  try {
    renderConfig(await getJSON("/api/config"));
  } catch (err) {
    document.getElementById("json").textContent = String(err);
  }
}

async function connectScope() {
  try {
    const resource = document.getElementById("resource").value.trim();
    const ip = document.getElementById("ip").value.trim();
    const data = await postJSON("/api/connect", {
      resource: resource || null,
      ip: resource ? null : (ip || null),
      socket: document.getElementById("socket").checked,
      socket_port: Number(document.getElementById("socketPort").value),
    });
    renderConfig(data);
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

async function applyChannel(channel) {
  try {
    const bandwidth = document.getElementById(`ch${channel}_bandwidth`).value.trim();
    renderConfig(await postJSON("/api/channel", {
      channel,
      display: document.getElementById(`ch${channel}_display`).checked,
      scale_v: Number(document.getElementById(`ch${channel}_scale`).value),
      position_div: Number(document.getElementById(`ch${channel}_position`).value),
      offset_v: Number(document.getElementById(`ch${channel}_offset`).value),
      coupling: document.getElementById(`ch${channel}_coupling`).value,
      bandwidth: bandwidth || null,
    }));
  } catch (err) {
    alert(String(err));
  }
}

async function applyTrigger() {
  try {
    renderConfig(await postJSON("/api/trigger", {
      source: document.getElementById("trigSource").value,
      slope: document.getElementById("trigSlope").value,
      level_v: Number(document.getElementById("trigLevel").value),
      mode: document.getElementById("trigMode").value,
    }));
  } catch (err) {
    alert(String(err));
  }
}

function parseChannels(value) {
  return value.split(/[ ,]+/).filter(Boolean).map(v => Number(v));
}

async function acquire() {
  const button = document.getElementById("acquireButton");
  button.disabled = true;
  try {
    const data = await postJSON("/api/acquire", {
      channels: parseChannels(document.getElementById("acqChannels").value),
      start: Number(document.getElementById("start").value),
      stop: Number(document.getElementById("stop").value),
      timeout_s: Number(document.getElementById("timeout").value),
      single: document.getElementById("single").checked,
      save: document.getElementById("save").checked,
      save_directory: document.getElementById("saveDir").value,
    });
    latestWaveforms = data.waveforms || [];
    drawWaveforms();
    setStatus(data);
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

function drawPanel(ctx, waveform, x, y, w, h, color) {
  const t = waveform.time_s || [];
  const v = waveform.voltage_v || [];
  ctx.strokeStyle = "#d8dde3";
  ctx.strokeRect(x, y, w, h);
  ctx.fillStyle = "#202124";
  ctx.font = "15px system-ui";
  ctx.fillText(`CH${waveform.channel}`, x + 10, y + 22);
  if (t.length < 2 || v.length < 2) {
    ctx.fillStyle = "#687076";
    ctx.fillText("no data", x + 10, y + 48);
    return;
  }
  const [tMin, tMax] = extent(t);
  const [vMin, vMax] = extent(v);
  const px = tv => x + ((tv - tMin) / (tMax - tMin)) * w;
  const py = vv => y + h - ((vv - vMin) / (vMax - vMin)) * h;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(px(t[0]), py(v[0]));
  for (let i = 1; i < t.length; i += 1) ctx.lineTo(px(t[i]), py(v[i]));
  ctx.stroke();
  ctx.fillStyle = "#687076";
  ctx.font = "12px system-ui";
  ctx.fillText(`${tMin.toExponential(3)} to ${tMax.toExponential(3)} s`, x + 10, y + h - 10);
  ctx.fillText(`${vMin.toFixed(3)} to ${vMax.toFixed(3)} V`, x + w - 160, y + h - 10);
}

function drawWaveforms() {
  const canvas = document.getElementById("plot");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (latestWaveforms.length === 0) {
    ctx.fillStyle = "#687076";
    ctx.font = "18px system-ui";
    ctx.fillText("No waveform acquired yet", 24, 44);
    return;
  }
  const colors = ["#1769e0", "#188038", "#d93025", "#7a4cc2"];
  const gap = 20;
  const panelW = (canvas.width - gap * 3) / 2;
  const panelH = (canvas.height - gap * 3) / 2;
  latestWaveforms.slice(0, 4).forEach((waveform, index) => {
    const col = index % 2;
    const row = Math.floor(index / 2);
    drawPanel(ctx, waveform, gap + col * (panelW + gap), gap + row * (panelH + gap), panelW, panelH, colors[index % colors.length]);
  });
}

renderChannels();
drawWaveforms();
refreshConfig();
"""
    return page("Tektronix MDO3034", body, script)


def create_app(default_ip: str | None = None, default_resource: str | None = None) -> FastAPI:
    app = FastAPI(title="Tektronix MDO3034")
    state = MdoWebState()

    def require_scope() -> Mdo3034:
        if state.scope is None or not state.connected:
            raise RuntimeError("MDO3034 is not connected")
        return state.scope

    def config_sync() -> dict:
        with state.lock:
            channels = []
            trigger = None
            if state.connected and state.scope is not None:
                channels = [item.asdict() for item in state.scope.get_all_channel_configs()]
                trigger = state.scope.get_trigger_config().asdict()
            return {
                "status": state.status(),
                "channels": channels,
                "trigger": trigger,
            }

    def connect_sync(req: ConnectRequest) -> dict:
        with state.lock:
            if state.scope is not None:
                state.scope.close()
            if req.resource is None and req.ip is None:
                raise RuntimeError("VISA resource or IP is required")
            scope = Mdo3034(
                resource=req.resource,
                ip=req.ip,
                socket=req.socket,
                socket_port=req.socket_port,
                backend=req.backend,
                timeout_ms=req.timeout_ms,
            )
            scope.connect()
            state.scope = scope
            state.idn = scope.get_idn()
            state.connected = True
            state.last_error = None
            channels = [item.asdict() for item in scope.get_all_channel_configs()]
            trigger = scope.get_trigger_config().asdict()
            return {"status": state.status(), "channels": channels, "trigger": trigger}

    def disconnect_sync() -> dict:
        with state.lock:
            if state.scope is not None:
                state.scope.close()
            state.scope = None
            state.connected = False
            return state.status()

    def channel_sync(req: ChannelRequest) -> dict:
        with state.lock:
            scope = require_scope()
            scope.apply_channel_config(
                channel=req.channel,
                display=req.display,
                scale_v=req.scale_v,
                position_div=req.position_div,
                offset_v=req.offset_v,
                coupling=req.coupling,
                bandwidth=req.bandwidth,
            )
            channels = [item.asdict() for item in scope.get_all_channel_configs()]
            trigger = scope.get_trigger_config().asdict()
            return {"status": state.status(), "channels": channels, "trigger": trigger}

    def trigger_sync(req: TriggerRequest) -> dict:
        with state.lock:
            scope = require_scope()
            scope.apply_trigger_config(
                source=req.source,
                slope=req.slope,
                level_v=req.level_v,
                mode=req.mode,
            )
            channels = [item.asdict() for item in scope.get_all_channel_configs()]
            trigger = scope.get_trigger_config().asdict()
            return {"status": state.status(), "channels": channels, "trigger": trigger}

    def acquire_sync(req: AcquireRequest) -> dict:
        with state.lock:
            if req.stop < req.start:
                raise RuntimeError("stop must be greater than or equal to start")
            scope = require_scope()
            waveforms = scope.acquire_waveforms(
                channels=req.channels,
                start=req.start,
                stop=req.stop,
                single=req.single,
                timeout_s=req.timeout_s,
            )
            csv_path = None
            if req.save:
                csv_path = timestamped_csv_path(Path(req.save_directory))
                write_waveforms_csv(csv_path, waveforms)
                state.last_csv = str(csv_path)
            state.last_error = None
            return {
                "status": state.status(),
                "waveforms": [waveform.to_jsonable() for waveform in waveforms],
                "csv": str(csv_path) if csv_path else None,
            }

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await asyncio.to_thread(disconnect_sync)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _html(default_ip, default_resource)

    @app.get("/api/config")
    async def config() -> dict:
        try:
            return await asyncio.to_thread(config_sync)
        except Exception as exc:
            state.last_error = str(exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

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

    @app.post("/api/channel")
    async def channel(req: ChannelRequest) -> dict:
        try:
            return await asyncio.to_thread(channel_sync, req)
        except Exception as exc:
            state.last_error = str(exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/trigger")
    async def trigger(req: TriggerRequest) -> dict:
        try:
            return await asyncio.to_thread(trigger_sync, req)
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
    parser = argparse.ArgumentParser(description="Run Tektronix MDO3034 WebUI")
    parser.add_argument("--resource", help="Default VISA resource")
    parser.add_argument("--ip", help="Default oscilloscope IP")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8084)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run(
        create_app(default_ip=args.ip, default_resource=args.resource),
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
