import asyncio
import threading

from cursed_controls.app_state import AppState, DeviceStatus


def test_initial_state():
    s = AppState()
    assert s.config is None
    assert s.runtime_status == "stopped"
    assert s.device_statuses == {}


def test_broadcast_enqueues_to_registered_queue():
    loop = asyncio.new_event_loop()
    try:
        s = AppState()
        s.set_loop(loop)
        q = asyncio.Queue()
        s.add_ws_queue(q)

        s.broadcast({"type": "test", "value": 42})

        loop.run_until_complete(asyncio.sleep(0.01))
        assert not q.empty()
        msg = q.get_nowait()
        assert msg == {"type": "test", "value": 42}
    finally:
        loop.close()


def test_broadcast_no_loop_is_silent():
    s = AppState()
    s.broadcast({"type": "test"})  # must not raise


def test_remove_ws_queue():
    loop = asyncio.new_event_loop()
    try:
        s = AppState()
        s.set_loop(loop)
        q = asyncio.Queue()
        s.add_ws_queue(q)
        s.remove_ws_queue(q)
        s.broadcast({"type": "test"})
        loop.run_until_complete(asyncio.sleep(0.01))
        assert q.empty()
    finally:
        loop.close()


def test_broadcast_from_thread():
    loop = asyncio.new_event_loop()
    try:
        s = AppState()
        s.set_loop(loop)
        q = asyncio.Queue()
        s.add_ws_queue(q)

        t = threading.Thread(target=lambda: s.broadcast({"type": "from_thread"}))
        t.start()
        t.join()

        loop.run_until_complete(asyncio.sleep(0.05))
        assert not q.empty()
        assert q.get_nowait()["type"] == "from_thread"
    finally:
        loop.close()
