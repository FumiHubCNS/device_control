from __future__ import annotations

import argparse
import asyncio
import threading
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from device_control.protocol import decode_escape_sequences
from device_control.webui import page

from .driver import Afg1062


class ConnectRequest(BaseModel):
    resource: str | None = None
    usbtmc: str | None = None
    ip: str | None = None
    backend: str = "@py"
    timeout_ms: int = Field(default=10000, ge=1000, le=120000)
    write_termination: str = "\\n"


class SetChannelRequest(BaseModel):
    channel: int = Field(ge=1, le=2)
    output: bool | None = None
    waveform: str | None = None
    frequency_hz: float | None = Field(default=None, gt=0)
    amplitude_vpp: float | None = Field(default=None, ge=0)
    offset_v: float | None = None
    phase: float | None = None
    phase_unit: str = "RAD"
    duty_cycle_percent: float | None = Field(default=None, ge=0, le=100)


@dataclass
class AfgWebState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    afg: Afg1062 | None = None
    connected: bool = False
    idn: str | None = None
    last_error: str | None = None

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "idn": self.idn,
            "last_error": self.last_error,
        }


def _html(
    default_resource: str | None,
    default_usbtmc: str | None,
    default_ip: str | None,
    default_write_termination: str,
) -> str:
    body = f"""
    <header>
      <h1>Tektronix AFG1062</h1>
      <div class="row">
        <span>Device: <span id="deviceStatus" class="ng">disconnected</span></span>
        <span id="idn"></span>
      </div>
    </header>

    <section>
      <h2>Connection</h2>
      <div class="row">
        <label for="resource">VISA resource</label>
        <input id="resource" value="{default_resource or ''}" placeholder="USB0::...::INSTR" />
        <label for="usbtmc">USB-TMC device</label>
        <input id="usbtmc" value="{default_usbtmc or ''}" placeholder="/dev/usbtmc0" />
        <label for="ip">IP</label>
        <input id="ip" value="{default_ip or ''}" />
        <label for="backend">Backend</label>
        <input id="backend" value="@py" />
        <label for="writeTermination">Write termination</label>
        <input id="writeTermination" value="{default_write_termination}" />
        <button class="primary" onclick="connectDevice()">Connect</button>
        <button onclick="disconnectDevice()">Disconnect</button>
        <button onclick="refreshSettings()">Refresh</button>
      </div>
    </section>

    <section>
      <h2>Channels</h2>
      <div class="grid">
        <div class="metric" id="ch1"></div>
        <div class="metric" id="ch2"></div>
      </div>
    </section>

    <section>
      <h2>Status JSON</h2>
      <pre id="json">{{}}</pre>
    </section>
    """
    script = """
const waveforms = [
  ["SIN", "Sine"],
  ["SQU", "Square"],
  ["RAMP", "Ramp"],
  ["PULS", "Pulse"],
  ["PRN", "Noise"],
  ["DC", "DC"],
];

function setStatus(data) {
  const status = data.status || data;
  const device = document.getElementById("deviceStatus");
  device.textContent = status.connected ? "connected" : "disconnected";
  device.className = status.connected ? "ok" : "ng";
  document.getElementById("idn").textContent = status.idn || "";
  document.getElementById("json").textContent = JSON.stringify(data, null, 2);
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

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

function renderChannel(channel, settings = {}) {
  const root = document.getElementById(`ch${channel}`);
  const waveform = settings.waveform === "PRN" ? "PRN" : (settings.waveform || "SIN");
  root.innerHTML = `
    <h2>CH${channel}</h2>
    <div class="row">
      <label><input id="ch${channel}_output" type="checkbox" ${settings.output ? "checked" : ""} /> Output</label>
      <label>Waveform</label>
      <select id="ch${channel}_waveform">
        ${waveforms.map(([value, label]) => `<option value="${value}" ${value === waveform ? "selected" : ""}>${label}</option>`).join("")}
      </select>
    </div>
    <div class="row">
      <label>Frequency [Hz]</label>
      <input id="ch${channel}_frequency" type="number" min="0" step="any" value="${settings.frequency_hz ?? 1000}" />
    </div>
    <div class="row">
      <label>Amplitude [Vpp]</label>
      <input id="ch${channel}_amplitude" type="number" min="0" step="any" value="${settings.amplitude_vpp ?? 1}" />
    </div>
    <div class="row">
      <label>Offset [V]</label>
      <input id="ch${channel}_offset" type="number" step="any" value="${settings.offset_v ?? 0}" />
    </div>
    <div class="row">
      <label>Phase [deg]</label>
      <input id="ch${channel}_phase" type="number" min="0" max="360" step="any" value="${settings.phase_rad == null ? 0 : settings.phase_rad * 180 / Math.PI}" />
      <label>Duty [%]</label>
      <input id="ch${channel}_duty" type="number" min="0" max="100" step="any" value="${settings.duty_cycle_percent ?? 50}" />
    </div>
    <div class="row">
      <button class="safe" onclick="applyChannel(${channel})">Apply CH${channel}</button>
    </div>
  `;
}

function renderSettings(data) {
  setStatus(data);
  const channels = data.channels || [];
  for (const channel of [1, 2]) {
    const settings = channels.find(item => item.channel === channel) || {};
    renderChannel(channel, settings);
  }
}

async function refreshSettings() {
  try {
    renderSettings(await getJSON("/api/settings"));
  } catch (err) {
    document.getElementById("json").textContent = String(err);
  }
}

async function connectDevice() {
  try {
    const resource = document.getElementById("resource").value.trim();
    const usbtmc = document.getElementById("usbtmc").value.trim();
    const ip = document.getElementById("ip").value.trim();
    const payload = {
      resource: usbtmc ? null : (resource || null),
      usbtmc: usbtmc || null,
      ip: (resource || usbtmc) ? null : (ip || null),
      backend: document.getElementById("backend").value.trim() || "@py",
      write_termination: document.getElementById("writeTermination").value || "\\\\n",
    };
    renderSettings(await postJSON("/api/connect", payload));
    await refreshSettings();
  } catch (err) {
    alert(String(err));
  }
}

async function disconnectDevice() {
  try {
    setStatus(await postJSON("/api/disconnect", {}));
  } catch (err) {
    alert(String(err));
  }
}

async function applyChannel(channel) {
  try {
    const waveform = document.getElementById(`ch${channel}_waveform`).value;
    const payload = {
      channel,
      output: document.getElementById(`ch${channel}_output`).checked,
      waveform,
      offset_v: Number(document.getElementById(`ch${channel}_offset`).value),
      phase: Number(document.getElementById(`ch${channel}_phase`).value),
      phase_unit: "DEG",
    };
    if (waveform !== "DC") {
      payload.frequency_hz = Number(document.getElementById(`ch${channel}_frequency`).value);
      payload.amplitude_vpp = Number(document.getElementById(`ch${channel}_amplitude`).value);
    }
    if (waveform === "PULS") {
      payload.duty_cycle_percent = Number(document.getElementById(`ch${channel}_duty`).value);
    }
    renderSettings(await postJSON("/api/channel", payload));
  } catch (err) {
    alert(String(err));
  }
}

renderChannel(1);
renderChannel(2);
refreshSettings();
"""
    return page("Tektronix AFG1062", body, script)


def create_app(
    default_resource: str | None = None,
    default_usbtmc: str | None = None,
    default_ip: str | None = None,
    default_write_termination: str = "\\n",
    verbose: bool = False,
) -> FastAPI:
    app = FastAPI(title="Tektronix AFG1062")
    state = AfgWebState()

    def require_device() -> Afg1062:
        if state.afg is None or not state.connected:
            raise RuntimeError("AFG1062 is not connected")
        return state.afg

    def settings_sync() -> dict:
        with state.lock:
            channels = []
            if state.connected and state.afg is not None:
                channels = [item.asdict() for item in state.afg.get_all_settings()]
            return {"status": state.status(), "channels": channels}

    def connect_sync(req: ConnectRequest) -> dict:
        with state.lock:
            if state.afg is not None:
                state.afg.close()
            if req.resource is None and req.usbtmc is None and req.ip is None:
                raise RuntimeError("VISA resource, USB-TMC device, or IP is required")
            afg = Afg1062(
                resource=req.resource,
                usbtmc=req.usbtmc,
                ip=req.ip,
                backend=req.backend,
                timeout_ms=req.timeout_ms,
                write_termination=decode_escape_sequences(req.write_termination),
                verbose=verbose,
            )
            afg.connect()
            state.afg = afg
            state.idn = afg.get_idn()
            state.connected = True
            state.last_error = None
            return {"status": state.status(), "channels": []}

    def disconnect_sync() -> dict:
        with state.lock:
            if state.afg is not None:
                state.afg.close()
            state.afg = None
            state.connected = False
            return state.status()

    def apply_sync(req: SetChannelRequest) -> dict:
        with state.lock:
            afg = require_device()
            afg.apply_channel_settings(
                channel=req.channel,
                output=req.output,
                waveform=req.waveform,
                frequency_hz=req.frequency_hz,
                amplitude_vpp=req.amplitude_vpp,
                offset_v=req.offset_v,
                phase=req.phase,
                phase_unit=req.phase_unit,
                duty_cycle_percent=req.duty_cycle_percent,
            )
            channels = [item.asdict() for item in afg.get_all_settings()]
            return {"status": state.status(), "channels": channels}

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await asyncio.to_thread(disconnect_sync)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _html(default_resource, default_usbtmc, default_ip, default_write_termination)

    @app.get("/api/settings")
    async def settings() -> dict:
        try:
            return await asyncio.to_thread(settings_sync)
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
    async def channel(req: SetChannelRequest) -> dict:
        try:
            return await asyncio.to_thread(apply_sync, req)
        except Exception as exc:
            state.last_error = str(exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Tektronix AFG1062 WebUI")
    parser.add_argument("--resource", help="Default VISA resource")
    parser.add_argument("--usbtmc", help="Default Linux USB-TMC device")
    parser.add_argument("--ip", help="Default instrument IP")
    parser.add_argument("--write-termination", default="\\n", help=r"SCPI write termination, e.g. \n or \r\n")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--verbose", action="store_true", help="Print SCPI traffic to the server console")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run(
        create_app(
            default_resource=args.resource,
            default_usbtmc=args.usbtmc,
            default_ip=args.ip,
            default_write_termination=args.write_termination,
            verbose=args.verbose,
        ),
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
