"""A small synchronous client for one ComfyUI server: HTTP calls plus the client websocket.

Synchronous on purpose: a haywire worker runs on its own thread and blocks until the run ends.
One client has one ``client_id``; ComfyUI sends progress and image frames of the prompts
submitted under that id to that id's websocket only.
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import ExitStack
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

from haybale_comfyui.runtime.placeholders import HAYWIRE, Pack
from haybale_comfyui.runtime.tracker import Outcome, RunTracker

#: How long one websocket wait lasts before the cancel flag is checked again.
POLL_SECONDS = 0.1


class ComfyError(RuntimeError):
    """The server could not be reached or answered with an error."""


class PromptRejected(ComfyError):
    """``POST /prompt`` refused the workflow; ``node_errors`` names the failing inputs."""

    def __init__(self, error: dict, node_errors: dict) -> None:
        self.error = error
        self.node_errors = node_errors
        super().__init__(describe_rejection(error, node_errors))


class Cancelled(Exception):
    """The run was cancelled from haywire and interrupted on the server."""


@dataclass
class Published:
    """One workflow from the exchange: who published it, and the API-format graph."""

    publisher_name: str
    publisher_id: str
    workflow: dict[str, Any]


def describe_rejection(error: dict, node_errors: dict) -> str:
    """One readable line per failing input, from a ``POST /prompt`` 400 answer."""
    lines = [str(error.get("message") or "workflow rejected")]
    for node_id, entry in (node_errors or {}).items():
        for err in entry.get("errors", []):
            message, details = err.get("message", ""), err.get("details", "")
            detail = f"{message}: {details}" if message and details else message or details
            lines.append(f"node {node_id} ({entry.get('class_type', '?')}): {detail}")
    return "\n".join(lines)


def websocket_url(base_url: str, client_id: str) -> str:
    """``http(s)://host:port`` → ``ws(s)://host:port/ws?clientId=…``."""
    base = base_url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    else:
        base = "ws://" + base
    return f"{base}/ws?clientId={client_id}"


class ComfyClient:
    """HTTP and websocket access to one ComfyUI server under one client id."""

    def __init__(self, base_url: str, *, headers: dict[str, str] | None = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.client_id = uuid.uuid4().hex
        self.headers = dict(headers or {})
        self.timeout = timeout
        self._http = httpx.Client(base_url=self.base_url, headers=self.headers, timeout=timeout)
        self._ws: ClientConnection | None = None
        self._ws_stack = ExitStack()

    # ── lifecycle ─────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Open the websocket; ComfyUI only reports to a client id that is connected."""
        if self._ws is not None:
            return
        try:
            self._ws = self._ws_stack.enter_context(
                connect(
                    websocket_url(self.base_url, self.client_id),
                    additional_headers=self.headers or None,
                    open_timeout=self.timeout,
                    max_size=None,
                )
            )
        except (OSError, TimeoutError) as exc:
            raise ComfyError(f"cannot reach ComfyUI at {self.base_url}: {exc}") from exc

    def close(self) -> None:
        self._ws_stack.close()
        self._ws = None
        self._http.close()

    def __enter__(self) -> ComfyClient:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── HTTP ──────────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ComfyError(f"ComfyUI at {self.base_url}: {exc}") from exc

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        r = self._request(method, path, **kwargs)
        if r.status_code >= 400:
            raise ComfyError(f"ComfyUI {method} {path}: HTTP {r.status_code} {r.text[:200]}")
        return r.json() if r.content else None

    def system_stats(self) -> dict:
        return self._json("GET", "/system_stats")

    def object_info(self, class_type: str | None = None) -> dict:
        return self._json("GET", f"/object_info/{class_type}" if class_type else "/object_info")

    def submit(self, prompt: dict[str, Any]) -> str:
        """Queue an API-format workflow; return its ``prompt_id``.

        Raises:
            PromptRejected: the server's validation failed.
        """
        r = self._request("POST", "/prompt", json={"prompt": prompt, "client_id": self.client_id})
        body = r.json() if r.content else {}
        if r.status_code == 400 and "node_errors" in body:
            raise PromptRejected(body.get("error") or {}, body.get("node_errors") or {})
        if r.status_code >= 400:
            raise ComfyError(f"ComfyUI POST /prompt: HTTP {r.status_code} {r.text[:200]}")
        return str(body["prompt_id"])

    def interrupt(self, prompt_id: str) -> None:
        """Stop *prompt_id* if it runs, and drop it from the queue if it waits."""
        self._request("POST", "/interrupt", json={"prompt_id": prompt_id})
        self._request("POST", "/queue", json={"delete": [prompt_id]})

    def protocol(self) -> int | None:
        """The comfyui-haywire protocol version, or ``None`` when the pack is not installed."""
        r = self._request("GET", "/api/haywire/version")
        return int(r.json()["protocol"]) if r.status_code == 200 else None

    def subscribe(self, pack: Pack = HAYWIRE) -> None:
        self._json("POST", f"{pack.exchange_prefix}/subscribe", json={"client_id": self.client_id})

    def unsubscribe(self, pack: Pack = HAYWIRE) -> None:
        self._json("POST", f"{pack.exchange_prefix}/unsubscribe", json={"client_id": self.client_id})

    def withdraw(self, pack: Pack = HAYWIRE) -> None:
        """Remove this client's published workflow (comfyui-haywire only)."""
        self._json("POST", f"{pack.exchange_prefix}/withdraw", json={"client_id": self.client_id})

    def publish(self, name: str, workflow: dict[str, Any], pack: Pack = HAYWIRE) -> None:
        """Publish a workflow under this client's id (tests and tools; ComfyUI's page does it too)."""
        body = {"name": name, "client_id": self.client_id, "workflow": workflow}
        self._json("POST", f"{pack.exchange_prefix}/publish", json=body)

    # ── websocket ─────────────────────────────────────────────────────────

    def messages(self, timeout: float = POLL_SECONDS) -> Iterator[str | bytes | None]:
        """Yield websocket messages; ``None`` when *timeout* passes with none, so callers can poll."""
        if self._ws is None:
            raise ComfyError("not connected")
        while True:
            try:
                yield self._ws.recv(timeout=timeout)
            except TimeoutError:
                yield None
            except ConnectionClosed as exc:
                raise ComfyError(f"ComfyUI closed the connection: {exc}") from exc

    def wait_published(self, timeout: float, pack: Pack = HAYWIRE) -> list[Published]:
        """Collect the pack's published-workflow messages until *timeout* passes with none."""
        found: list[Published] = []
        for msg in self.messages(timeout=timeout):
            if msg is None:
                return found
            if isinstance(msg, str):
                data = json.loads(msg)
                if data.get("type") == pack.published_message:
                    d, pub = data["data"], data["data"].get("publisher") or {}
                    found.append(Published(str(pub.get("name")), str(pub.get("id")), d["workflow"]))
        return found

    def run(
        self,
        prompt: dict[str, Any],
        *,
        on_progress: Callable[[RunTracker], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> RunTracker:
        """Submit *prompt* and follow it to its end.

        Raises:
            PromptRejected: the server refused the workflow.
            Cancelled: *cancel* returned true; the prompt was interrupted, and the server
                confirmed it (or did not within the timeout).
            ComfyError: the connection failed, or the run ended in an error.
        """
        self.connect()
        tracker = RunTracker(self.submit(prompt))
        stop_by: float | None = None
        for msg in self.messages():
            if stop_by is None and cancel is not None and cancel():
                self.interrupt(tracker.prompt_id)
                if not tracker.started:
                    raise Cancelled(tracker.prompt_id)  # removed from the queue, never ran
                stop_by = time.monotonic() + self.timeout
            if stop_by is not None and time.monotonic() > stop_by:
                raise Cancelled(tracker.prompt_id)  # the server did not confirm in time
            if msg is None:
                continue
            before = tracker.progress
            tracker.feed(msg)
            if on_progress is not None and stop_by is None and tracker.progress is not before:
                on_progress(tracker)
            if tracker.done:
                break
        if stop_by is not None:
            raise Cancelled(tracker.prompt_id)
        if tracker.outcome is Outcome.ERROR:
            err = tracker.error or {}
            raise ComfyError(
                f"ComfyUI node {err.get('node_id')} ({err.get('node_type')}): "
                f"{err.get('exception_message', 'failed')}".strip()
            )
        if tracker.outcome is Outcome.INTERRUPTED:
            raise Cancelled(tracker.prompt_id)
        return tracker
