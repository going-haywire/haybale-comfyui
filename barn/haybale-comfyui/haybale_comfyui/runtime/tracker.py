"""Follow one prompt through ComfyUI's websocket messages; pure, no I/O.

Feed every message received on the client's websocket to :meth:`RunTracker.feed`, in order.
The tracker keeps only what belongs to its prompt and reports progress, images and the end.

Protocol facts this relies on (captured in ``spike/fixtures``, design note §3):

- Every JSON message about a prompt carries ``data.prompt_id``.
- A binary frame is ``>II`` (event type, format) followed by the image bytes; type 1 with
  format 2 is a PNG. A frame carries no prompt id: it belongs to the prompt of the last
  ``executing`` message, because ComfyUI runs one prompt at a time.
- ``ETN_KritaOutput`` sends its frames and then ``executed`` with ``output.info`` naming them.
  ``SaveImageWebsocket`` sends frames and no ``executed``.
- A cached output node replays ``executed`` but sends no frame.
- A run ends with ``execution_success``, ``execution_error`` or ``execution_interrupted``.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from enum import Enum

#: Binary event type of an image frame, and its PNG format code.
IMAGE_EVENT = 1
PNG_FORMAT = 2


class Outcome(Enum):
    """How a run ended."""

    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    INTERRUPTED = "interrupted"


@dataclass
class Progress:
    """The latest progress of the running prompt."""

    node: str
    value: int
    max: int


@dataclass
class RunTracker:
    """The state of one prompt, built from the messages fed to it."""

    prompt_id: str
    outcome: Outcome = Outcome.RUNNING
    #: Output name → PNG bytes, in the order received.
    images: dict[str, list[bytes]] = field(default_factory=dict)
    #: Output names whose ``executed`` came from ComfyUI's cache, with no frame.
    cached_outputs: list[str] = field(default_factory=list)
    #: Node ids ComfyUI reported as cached for this prompt.
    cached_nodes: list[str] = field(default_factory=list)
    progress: Progress | None = None
    #: The ``data`` of ``execution_error`` or ``execution_interrupted``.
    error: dict | None = None
    #: ComfyUI started executing the prompt (it left the queue).
    started: bool = False
    #: Node id → (value, max, state) from the latest ``progress_state``; state is
    #: ``running`` or ``finished``.
    node_states: dict[str, tuple[float, float, str]] = field(default_factory=dict)
    #: Bumped by every message that changes what a progress display shows.
    revision: int = 0
    _current_prompt: str | None = None
    _current_node: str | None = None
    _pending: list[bytes] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.outcome is not Outcome.RUNNING

    @property
    def running_node(self) -> str | None:
        """The node ComfyUI is executing for this prompt, if any."""
        return self._current_node if self._current_prompt == self.prompt_id else None

    def fraction(self, total_nodes: int) -> float:
        """Share of the run done, counting each of *total_nodes* nodes to execute equally.

        A running node counts by its own progress (a sampler by its steps).
        """
        if total_nodes <= 0:
            return 0.0
        done = 0.0
        for value, maximum, state in self.node_states.values():
            if state == "finished":
                done += 1.0
            elif maximum > 0:
                done += min(value / maximum, 1.0)
        return min(done / total_nodes, 1.0)

    def feed(self, message: str | bytes) -> None:
        """Take one websocket message, text or binary."""
        if isinstance(message, bytes):
            self._feed_frame(message)
        else:
            self._feed_json(json.loads(message))

    def _feed_frame(self, frame: bytes) -> None:
        if self._current_prompt != self.prompt_id or len(frame) < 8:
            return
        event, fmt = struct.unpack(">II", frame[:8])
        if event == IMAGE_EVENT and fmt == PNG_FORMAT:
            self._pending.append(frame[8:])

    def _feed_json(self, msg: dict) -> None:
        kind, data = msg.get("type"), msg.get("data") or {}
        if data.get("prompt_id") != self.prompt_id:
            if kind == "executing":
                self._current_prompt = data.get("prompt_id")
            return
        if kind == "execution_start":
            self.started = True
            self.revision += 1
        elif kind == "executing":
            self._flush_unnamed()
            self._current_prompt = self.prompt_id
            self._current_node = data.get("node")
            self.revision += 1
        elif kind == "execution_cached":
            self.cached_nodes = [str(n) for n in data.get("nodes", [])]
        elif kind == "progress":
            self.progress = Progress(str(data.get("node")), int(data["value"]), int(data["max"]))
            self.revision += 1
        elif kind == "progress_state":
            self.node_states = {
                str(nid): (float(st.get("value", 0)), float(st.get("max", 0)), str(st.get("state", "")))
                for nid, st in (data.get("nodes") or {}).items()
            }
            self.revision += 1
        elif kind == "executed":
            self._take_executed(data)
        elif kind == "execution_success":
            self._flush_unnamed()
            self.outcome = Outcome.SUCCESS
        elif kind == "execution_error":
            self.outcome, self.error = Outcome.ERROR, data
        elif kind == "execution_interrupted":
            self.outcome, self.error = Outcome.INTERRUPTED, data

    def _take_executed(self, data: dict) -> None:
        output = data.get("output") or {}
        infos = output.get("info") or []
        if not infos:
            self._flush_unnamed()
            return
        names = [str(info.get("name") or data.get("node")) for info in infos]
        if not self._pending:
            self.cached_outputs.extend(n for n in names if n not in self.cached_outputs)
            return
        # One info per frame; if the counts differ, the frames go to the first name.
        if len(names) == len(self._pending):
            for name, png in zip(names, self._pending, strict=True):
                self.images.setdefault(name, []).append(png)
        else:
            self.images.setdefault(names[0], []).extend(self._pending)
        self._pending = []

    def _flush_unnamed(self) -> None:
        """Frames with no ``executed`` after them go under their node's id."""
        if self._pending:
            self.images.setdefault(str(self._current_node), []).extend(self._pending)
            self._pending = []
