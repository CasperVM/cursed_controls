from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from cursed_controls.config import AppConfig


@dataclass
class DeviceStatus:
    profile_id: str
    path: str | None
    status: Literal["bound", "pending", "disconnected", "unbound"]


@dataclass
class AppState:
    config: "AppConfig | None" = None
    config_path: str | None = None
    runtime_status: Literal["running", "stopped"] = "stopped"
    device_statuses: dict[str, DeviceStatus] = field(default_factory=dict)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )
    _event_loop: asyncio.AbstractEventLoop | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _ws_queues: list[asyncio.Queue] = field(
        default_factory=list, init=False, repr=False, compare=False
    )

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._event_loop = loop

    def broadcast(self, message: dict) -> None:
        """Thread-safe: enqueue message to all connected WebSocket clients."""
        if self._event_loop is None or self._event_loop.is_closed():
            return
        with self._lock:
            queues = list(self._ws_queues)
        for q in queues:
            self._event_loop.call_soon_threadsafe(q.put_nowait, message)

    def add_ws_queue(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._ws_queues.append(queue)

    def remove_ws_queue(self, queue: asyncio.Queue) -> None:
        with self._lock:
            try:
                self._ws_queues.remove(queue)
            except ValueError:
                pass
