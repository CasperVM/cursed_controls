from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from cursed_controls.app_state import AppState
from cursed_controls.web.runtime_manager import RuntimeManager

_STATIC = Path(__file__).parent / "static"


def create_app(state: AppState) -> FastAPI:
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        state.set_loop(asyncio.get_running_loop())
        # Autostart: if a config was preloaded, start the runtime immediately.
        rm: RuntimeManager = app.state.runtime_manager
        if state.config is not None:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, rm.start)
        yield
        # Shutdown: stop runtime and close the gadget sink cleanly.
        # close_sink() is blocking (kills ep0/ep_out_N then calls x360_close).
        # Run it in a thread executor with a timeout so uvicorn can exit even
        # if the Rust close blocks longer than expected.
        rm.stop()
        # x360_close() can block up to ~7s waiting for internal gadget threads.
        # Run in executor with timeout so uvicorn exits cleanly even if it stalls.
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, rm.close_sink), timeout=8.0
            )
        except asyncio.TimeoutError:
            print("[lifespan] close_sink timed out", flush=True)

    app = FastAPI(title="cursed-controls", lifespan=_lifespan)
    app.state.app_state = state
    app.state.runtime_manager = RuntimeManager(state)

    # Routes (imported here to avoid circular imports at module load)
    from cursed_controls.web.routes import devices, config, bluetooth, runtime, presets

    app.include_router(devices.router, prefix="/api")
    app.include_router(config.router, prefix="/api")
    app.include_router(bluetooth.router, prefix="/api")
    app.include_router(runtime.router, prefix="/api")
    app.include_router(presets.router, prefix="/api")

    # Static files (serves index.html at /)
    if _STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

        @app.get("/")
        async def index():
            from fastapi.responses import FileResponse, Response

            index_path = _STATIC / "index.html"
            if not index_path.exists():
                return Response(status_code=404)
            return FileResponse(str(index_path))

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        queue: asyncio.Queue = asyncio.Queue()
        state.add_ws_queue(queue)
        # Send current state immediately
        await ws.send_json({"type": "runtime_status", "status": state.runtime_status})
        try:
            receiver = asyncio.create_task(_ws_receive(ws, state, queue))
            sender = asyncio.create_task(_ws_send(ws, queue))
            done, pending = await asyncio.wait(
                [receiver, sender], return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
        except WebSocketDisconnect:
            pass
        finally:
            state.remove_ws_queue(queue)

    return app


async def _ws_send(ws: WebSocket, queue: asyncio.Queue) -> None:
    """Forward queued messages to the WebSocket client."""
    while True:
        msg = await queue.get()
        try:
            await ws.send_json(msg)
        except (WebSocketDisconnect, asyncio.CancelledError):
            break
        except Exception as exc:
            print(f"[ws_send] error sending message: {exc!r}", flush=True)
            break


async def _ws_receive(ws: WebSocket, state: AppState, queue: asyncio.Queue) -> None:
    """Handle client -> server WebSocket messages (subscribe_input, unsubscribe_input, reset_axis_range)."""
    input_task: asyncio.Task | None = None
    observed: dict[int, tuple[int, int]] = {}

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await queue.put({"type": "error", "message": "invalid JSON"})
                continue
            msg_type = msg.get("type")

            if msg_type == "subscribe_input":
                device_path = msg.get("device_path")
                if input_task is not None:
                    input_task.cancel()
                    input_task = None
                    observed.clear()
                if device_path:
                    input_task = asyncio.create_task(
                        _stream_input(device_path, queue, observed)
                    )

            elif msg_type == "unsubscribe_input":
                if input_task is not None:
                    input_task.cancel()
                    input_task = None
                    observed.clear()

            elif msg_type == "reset_axis_range":
                observed.clear()

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        if input_task is not None:
            input_task.cancel()


async def _stream_input(
    device_path: str, queue: asyncio.Queue, observed: dict[int, tuple[int, int]]
) -> None:
    """Open an evdev device and stream axis/button events to the WS queue."""
    import evdev
    from evdev import ecodes

    try:
        dev = evdev.InputDevice(device_path)
    except OSError:
        await queue.put(
            {"type": "input_error", "message": f"Cannot open {device_path}"}
        )
        return

    grabbed = False
    try:
        dev.grab()
        grabbed = True
    except IOError:
        pass

    # Build initial axis info from capabilities
    axes_info: dict[int, evdev.AbsInfo] = {}
    caps = dev.capabilities()
    for code, info in caps.get(ecodes.EV_ABS, []):
        if isinstance(info, evdev.AbsInfo):
            axes_info[code] = info
            if code not in observed:
                observed[code] = (info.value, info.value)

    try:
        async for event in dev.async_read_loop():
            if event.type == ecodes.EV_ABS and event.code in axes_info:
                lo, hi = observed.get(event.code, (event.value, event.value))
                observed[event.code] = (min(lo, event.value), max(hi, event.value))
                info = axes_info[event.code]
                name = ecodes.ABS.get(event.code, f"ABS_{event.code}")
                obs_lo, obs_hi = observed[event.code]
                await queue.put(
                    {
                        "type": "axis_update",
                        "device_path": device_path,
                        "axes": [
                            {
                                "code": event.code,
                                "name": name,
                                "value": event.value,
                                "min": info.min,
                                "max": info.max,
                                "observed_min": obs_lo,
                                "observed_max": obs_hi,
                            }
                        ],
                    }
                )
            elif event.type == ecodes.EV_KEY and event.value == 1:
                name = ecodes.KEY.get(
                    event.code, ecodes.BTN.get(event.code, str(event.code))
                )
                await queue.put(
                    {
                        "type": "button_detected",
                        "device_path": device_path,
                        "ev_type": event.type,
                        "ev_code": event.code,
                        "name": name,
                    }
                )
    except (OSError, asyncio.CancelledError):
        pass
    finally:
        if grabbed:
            try:
                dev.ungrab()
            except Exception:
                pass
        dev.close()
