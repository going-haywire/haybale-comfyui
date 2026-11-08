"""The workflows ComfyUI pages have published, kept current by one background subscriber per server.

Every ComfyUI Workflow node of a server shares one :class:`WorkflowDirectory`. It subscribes to
the comfyui-haywire exchange on its own thread, reconnects when the connection drops (design
note §3.3), and keeps the latest workflow per name. Nodes read it to fill their picker and
register a listener to hear about new versions.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from haybale_comfyui.runtime.client import ComfyClient, ComfyError
from haybale_comfyui.runtime.placeholders import HAYWIRE, Pack

logger = logging.getLogger(__name__)

#: Seconds between reconnect attempts, growing to the maximum.
RETRY_FIRST, RETRY_MAX = 2.0, 30.0

Listener = Callable[["Entry"], None]


@dataclass(frozen=True)
class Entry:
    """The latest workflow published under one name."""

    name: str
    publisher_id: str
    workflow: dict[str, Any]
    received: float


class WorkflowDirectory:
    """Published workflows of one server, by name."""

    def __init__(self, base_url: str, headers: dict[str, str] | None = None, pack: Pack = HAYWIRE):
        self.base_url = base_url
        self.headers = dict(headers or {})
        self.pack = pack
        self.error: str | None = None
        self._entries: dict[str, Entry] = {}
        self._listeners: list[Listener] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── reading ───────────────────────────────────────────────────────────

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._entries)

    def get(self, name: str) -> Entry | None:
        with self._lock:
            return self._entries.get(name)

    # ── listening ─────────────────────────────────────────────────────────

    def add_listener(self, listener: Listener) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def receive(self, name: str, publisher_id: str, workflow: dict[str, Any]) -> None:
        """Record a published workflow and tell the listeners; the thread calls it, tests may too."""
        entry = Entry(name, publisher_id, workflow, time.time())
        with self._lock:
            old = self._entries.get(name)
            if old is not None and old.workflow == workflow:
                return
            self._entries[name] = entry
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(entry)
            except Exception:  # a broken node must not stop the directory
                logger.exception("ComfyUI workflow listener failed")

    # ── the subscriber thread ─────────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="comfyui-directory", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        delay = RETRY_FIRST
        while not self._stop.is_set():
            try:
                with ComfyClient(self.base_url, headers=self.headers) as client:
                    client.subscribe(self.pack)
                    self.error, delay = None, RETRY_FIRST
                    for msg in client.messages(timeout=0.5):
                        if self._stop.is_set():
                            return
                        if isinstance(msg, str):
                            self._take(msg)
            except ComfyError as exc:
                self.error = str(exc)
            except Exception as exc:  # keep the thread alive; report on the cards
                logger.exception("ComfyUI directory failed")
                self.error = str(exc)
            self._stop.wait(delay)
            delay = min(delay * 2, RETRY_MAX)

    def _take(self, text: str) -> None:
        data = json.loads(text)
        if data.get("type") != self.pack.published_message:
            return
        body = data.get("data") or {}
        publisher, workflow = body.get("publisher") or {}, body.get("workflow")
        if isinstance(workflow, dict):
            self.receive(str(publisher.get("name") or "Untitled"), str(publisher.get("id")), workflow)


_directories: dict[tuple[str, tuple[tuple[str, str], ...]], WorkflowDirectory] = {}
_directories_lock = threading.Lock()


def directory_for(base_url: str, headers: dict[str, str] | None = None) -> WorkflowDirectory:
    """The running directory of *base_url*, started on first use."""
    key = (base_url.rstrip("/"), tuple(sorted((headers or {}).items())))
    with _directories_lock:
        found = _directories.get(key)
        if found is None:
            found = _directories[key] = WorkflowDirectory(key[0], headers)
    found.start()
    return found
