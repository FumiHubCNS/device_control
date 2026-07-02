from __future__ import annotations

import argparse
import asyncio
import time
from typing import Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from device_control.webui import page

from .kxs import KxsPowerSupply, find_ft232_port


DEFAULT_POLL_INTERVAL_SEC = 0.5


class SetVoltageRequest(BaseModel):
    voltage_v: float = Field(ge=0.0, le=40.95)


class SetCurrentRequest(BaseModel):
    current_a: float = Field(ge=0.0, le=10.23)


class OutputRequest(BaseModel):
    on: bool


def _html() -> str:
    body = """
    <header>
      <h1>KIKUSUI HV Controller</h1>
      <div class="row">
        <span>WebSocket: <span id="wsStatus" class="ng">disconnected</span></span>
        <span>Device: <span id="deviceStatus" class="ng">unknown</span></span>
      </div>
    </header>

    <section>
      <h2>Measured Values</h2>
      <div class="grid">
        <div class="metric">
          <div class="label">Voltage</div>
          <div class="value"><span id="measV">---</span> V</div>
        </div>
        <div class="metric">
          <div class="label">Current</div>
          <div class="value"><span id="measA">---</span> A</div>
        </div>
      </div>
    </section>

    <section>
      <h2>Settings</h2>
      <div class="row">
        <label for="setV">Voltage [V]</label>
        <input id="setV" type="number" min="0" max="40.95" step="0.01" value="30.00" />
        <button class="primary" onclick="setVoltage()">Set</button>
      </div>
      <div class="row">
        <label for="setA">Current [A]</label>
        <input id="setA" type="number" min="0" max="10.23" step="0.001" value="0.500" />
        <button class="primary" onclick="setCurrent()">Set</button>
      </div>
      <div class="row">
        <span>Output</span>
        <button class="safe" onclick="setOutput(true)">ON</button>
        <button class="danger" onclick="setOutput(false)">OFF</button>
      </div>
    </section>

    <section>
      <h2>Status JSON</h2>
      <pre id="json">{}</pre>
    </section>
    """
    script = """
let ws;
let heartbeat;

function fmt(x, digits = 3) {
  if (x === null || x === undefined) return "---";
  return Number(x).toFixed(digits);
}

function updateUI(data) {
  document.getElementById("measV").textContent = fmt(data.measured_voltage_v, 3);
  document.getElementById("measA").textContent = fmt(data.measured_current_a, 3);

  const device = document.getElementById("deviceStatus");
  device.textContent = data.connected ? "connected" : "disconnected";
  device.className = data.connected ? "ok" : "ng";

  document.getElementById("json").textContent = JSON.stringify(data, null, 2);
}

function connectWS() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${scheme}://${location.host}/ws`);

  ws.onopen = () => {
    const status = document.getElementById("wsStatus");
    status.textContent = "connected";
    status.className = "ok";
    clearInterval(heartbeat);
    heartbeat = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 1000);
  };

  ws.onmessage = event => updateUI(JSON.parse(event.data));
  ws.onclose = () => {
    const status = document.getElementById("wsStatus");
    status.textContent = "disconnected";
    status.className = "ng";
    clearInterval(heartbeat);
    setTimeout(connectWS, 1000);
  };
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    alert(await res.text());
    return;
  }
  updateUI(await res.json());
}

async function setVoltage() {
  await postJSON("/api/voltage", {voltage_v: Number(document.getElementById("setV").value)});
}

async function setCurrent() {
  await postJSON("/api/current", {current_a: Number(document.getElementById("setA").value)});
}

async function setOutput(on) {
  await postJSON("/api/output", {on});
}

connectWS();
"""
    return page("KIKUSUI HV Controller", body, script)


def create_app(
    *,
    port: str | None = None,
    address: str = "A1",
    auto_detect: bool = True,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_SEC,
) -> FastAPI:
    app = FastAPI(title="KIKUSUI HV Controller")
    psu = KxsPowerSupply(port or "/dev/ttyUSB0", address=address)
    websockets: Set[WebSocket] = set()

    def status_json() -> dict:
        return psu.status.asdict()

    async def broadcast_status() -> None:
        dead = []
        payload = status_json()
        for ws in list(websockets):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            websockets.discard(ws)

    async def polling_loop() -> None:
        while True:
            try:
                await asyncio.to_thread(psu.read_measurement)
            except Exception as exc:
                psu.status.connected = False
                psu.status.last_error = str(exc)
                psu.status.updated_at = time.time()
            await broadcast_status()
            await asyncio.sleep(poll_interval_s)

    @app.on_event("startup")
    async def startup() -> None:
        nonlocal psu
        try:
            detected_port = find_ft232_port() if auto_detect and port is None else port
            psu = KxsPowerSupply(detected_port or "/dev/ttyUSB0", address=address)
            await asyncio.to_thread(psu.connect)
        except Exception as exc:
            psu.status.last_error = str(exc)
            psu.status.updated_at = time.time()
        asyncio.create_task(polling_loop())

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await asyncio.to_thread(psu.close)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _html()

    @app.get("/api/status")
    async def get_status() -> dict:
        return status_json()

    @app.post("/api/voltage")
    async def set_voltage(req: SetVoltageRequest) -> dict:
        try:
            await asyncio.to_thread(psu.set_voltage, req.voltage_v)
            await broadcast_status()
            return status_json()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/current")
    async def set_current(req: SetCurrentRequest) -> dict:
        try:
            await asyncio.to_thread(psu.set_current, req.current_a)
            await broadcast_status()
            return status_json()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/output")
    async def set_output(req: OutputRequest) -> dict:
        try:
            await asyncio.to_thread(psu.set_output, req.on)
            await broadcast_status()
            return status_json()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        websockets.add(ws)
        try:
            await ws.send_json(status_json())
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            websockets.discard(ws)

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run KIKUSUI HV WebUI")
    parser.add_argument("--serial-port", default=None, help="Serial device path")
    parser.add_argument("--address", default="A1", help="KIKUSUI device address")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8081, help="Bind port")
    parser.add_argument("--no-auto-detect", action="store_true", help="Disable FT232 detection")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload")
    args = parser.parse_args(argv)

    import uvicorn

    app = create_app(
        port=args.serial_port,
        address=args.address,
        auto_detect=not args.no_auto_detect,
    )
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
