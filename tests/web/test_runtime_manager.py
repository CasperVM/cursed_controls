import asyncio

import pytest

from cursed_controls.app_state import AppState
from cursed_controls.config import AppConfig, RuntimeConfig
from cursed_controls.output import FakeSink
from cursed_controls.web.runtime_manager import RuntimeManager


def _minimal_config():
    return AppConfig(runtime=RuntimeConfig(output_mode="stdout"), devices=[])


def test_start_raises_if_no_config():
    state = AppState()
    mgr = RuntimeManager(state)
    with pytest.raises(ValueError, match="no config"):
        mgr.start(FakeSink())


def test_start_sets_running_status():
    state = AppState()
    state.config = _minimal_config()
    loop = asyncio.new_event_loop()
    state.set_loop(loop)
    mgr = RuntimeManager(state)
    mgr.start(FakeSink())
    try:
        assert state.runtime_status == "running"
    finally:
        mgr.stop()
        loop.close()


def test_stop_sets_stopped_status():
    state = AppState()
    state.config = _minimal_config()
    loop = asyncio.new_event_loop()
    state.set_loop(loop)
    mgr = RuntimeManager(state)
    mgr.start(FakeSink())
    mgr.stop()
    assert state.runtime_status == "stopped"
    loop.close()


def test_start_when_already_running_is_noop():
    state = AppState()
    state.config = _minimal_config()
    loop = asyncio.new_event_loop()
    state.set_loop(loop)
    mgr = RuntimeManager(state)
    mgr.start(FakeSink())
    thread_id = id(mgr._thread)
    mgr.start(FakeSink())  # second call — should not replace thread
    assert id(mgr._thread) == thread_id
    mgr.stop()
    loop.close()


def test_device_event_is_broadcast():
    state = AppState()
    state.config = _minimal_config()
    loop = asyncio.new_event_loop()
    state.set_loop(loop)
    q = asyncio.Queue()
    state.add_ws_queue(q)

    mgr = RuntimeManager(state)
    mgr.start(FakeSink())
    # Fire a device event via the callback
    mgr._on_runtime_event(
        {"type": "device_bound", "profile_id": "x", "path": "/dev/input/event0"}
    )

    loop.run_until_complete(asyncio.sleep(0.05))

    # Drain queue looking for device_bound (runtime_status may arrive first)
    found = None
    while not q.empty():
        msg = q.get_nowait()
        if msg.get("type") == "device_bound":
            found = msg
            break

    assert found is not None, "Expected device_bound message in WS queue"
    assert found["type"] == "device_bound"
    mgr.stop()
    loop.close()
