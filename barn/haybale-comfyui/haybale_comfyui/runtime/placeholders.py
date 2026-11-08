"""Placeholder nodes in an API-format ComfyUI workflow: find them, check them, replace them.

Pure functions over plain dicts. Which node classes are placeholders is described by a
:class:`Pack`: ``HAYWIRE`` for our comfyui-haywire pack (the default), ``ETN`` for Acly's
comfyui-tooling-nodes, used in the spike (design note §5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Kind(Enum):
    """What a placeholder becomes on the haywire node."""

    PARAMETER = "parameter"
    IMAGE = "image"
    OUTPUT = "output"


#: Parameter types this library knows, whatever the pack calls them.
PARAMETER_TYPES = ("number", "integer", "toggle", "text", "prompt", "choice", "auto")


@dataclass(frozen=True)
class Pack:
    """The server-side node pack: its placeholder classes, image loader and exchange."""

    placeholders: dict[str, Kind]
    #: Classes of the pack this library does not drive.
    unsupported: frozenset[str]
    #: The node an image placeholder is replaced by, and the input taking a base64 PNG. Its
    #: first output is an IMAGE, like the placeholder's.
    image_loader: str
    image_loader_input: str
    #: The pack's parameter type names → ``PARAMETER_TYPES``.
    parameter_types: dict[str, str]
    #: Route prefix and websocket message type of the workflow exchange.
    exchange_prefix: str
    published_message: str


HAYWIRE = Pack(
    placeholders={
        "HaywireParameter": Kind.PARAMETER,
        "HaywireImage": Kind.IMAGE,
        "HaywireOutput": Kind.OUTPUT,
    },
    unsupported=frozenset(),
    image_loader="HaywireLoadImage",
    image_loader_input="data",
    parameter_types={t: t for t in PARAMETER_TYPES if t != "auto"},
    exchange_prefix="/api/haywire/workflow",
    published_message="haywire_workflow_published",
)

ETN = Pack(
    placeholders={
        "ETN_Parameter": Kind.PARAMETER,
        "ETN_KritaImageLayer": Kind.IMAGE,
        "ETN_KritaOutput": Kind.OUTPUT,
    },
    unsupported=frozenset(
        {
            "ETN_KritaCanvas",
            "ETN_KritaSelection",
            "ETN_KritaMaskLayer",
            "ETN_KritaStyle",
            "ETN_KritaStyleAndPrompt",
            "ETN_KritaSendText",
        }
    ),
    image_loader="ETN_LoadImageBase64",
    image_loader_input="image",
    parameter_types={
        "auto": "auto",
        "number": "number",
        "number (integer)": "integer",
        "toggle": "toggle",
        "choice": "choice",
        "text": "text",
        "prompt (positive)": "prompt",
        "prompt (negative)": "prompt",
    },
    exchange_prefix="/api/etn/workflow",
    published_message="etn_workflow_published",
)


@dataclass(frozen=True)
class Placeholder:
    """One placeholder node, read from the workflow."""

    node_id: str
    kind: Kind
    name: str
    #: One of ``PARAMETER_TYPES``; empty for images and outputs.
    type: str = ""
    default: Any = None
    min: float | None = None
    max: float | None = None
    #: The inputs fed by this placeholder, as (node id, input name).
    consumers: tuple[tuple[str, str], ...] = ()

    @property
    def port_id(self) -> str:
        prefix = {Kind.PARAMETER: "param", Kind.IMAGE: "image", Kind.OUTPUT: "out"}[self.kind]
        return f"{prefix}_{slug(self.name)}"


@dataclass
class Interface:
    """Everything the haywire node needs to build its ports, and what is wrong with the workflow."""

    parameters: list[Placeholder] = field(default_factory=list)
    images: list[Placeholder] = field(default_factory=list)
    outputs: list[Placeholder] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return bool(self.outputs) and not self.problems


def slug(name: str) -> str:
    """A port-id-safe form of a placeholder name: lower case, ``_`` between words."""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "unnamed"


def parse_default(param_type: str, text: Any) -> Any:
    """The typed default of a parameter (one of ``PARAMETER_TYPES``); packs store it as text."""
    raw = "" if text is None else str(text).strip()
    if param_type == "number":
        return float(raw) if raw else 0.0
    if param_type == "integer":
        return int(float(raw)) if raw else 0
    if param_type == "toggle":
        return raw.lower() in ("true", "1", "yes", "on")
    return "" if text is None else str(text)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def consumers_of(workflow: dict[str, Any], node_id: str) -> tuple[tuple[str, str], ...]:
    """The (node id, input name) pairs linked to any output of *node_id*."""
    found = []
    for nid, node in workflow.items():
        for key, value in (node.get("inputs") or {}).items():
            if isinstance(value, list) and len(value) == 2 and str(value[0]) == node_id:
                found.append((nid, key))
    return tuple(found)


def read_interface(workflow: dict[str, Any], pack: Pack = HAYWIRE) -> Interface:
    """Find the placeholders of an API-format *workflow* and report what stops it being used."""
    result = Interface()
    for node_id, node in workflow.items():
        cls, inputs = node.get("class_type", ""), node.get("inputs") or {}
        if cls in pack.unsupported:
            result.problems.append(f"{cls} (node {node_id}) is not supported yet")
            continue
        kind = pack.placeholders.get(cls)
        if kind is None:
            continue
        name = str(inputs.get("name") or "").strip()
        if kind is Kind.OUTPUT:
            result.outputs.append(Placeholder(node_id, kind, name or node_id))
        elif kind is Kind.IMAGE:
            result.images.append(
                Placeholder(node_id, kind, name or node_id, consumers=consumers_of(workflow, node_id))
            )
        else:
            raw_type = str(inputs.get("type") or "")
            ptype = pack.parameter_types.get(raw_type)
            if ptype is None:
                result.problems.append(f"parameter {name!r} (node {node_id}) has unknown type {raw_type!r}")
                continue
            try:
                default = parse_default(ptype, inputs.get("default"))
            except ValueError:
                result.problems.append(
                    f"parameter {name!r}: default {inputs.get('default')!r} is not a {ptype}"
                )
                continue
            result.parameters.append(
                Placeholder(
                    node_id,
                    kind,
                    name or node_id,
                    type=ptype,
                    default=default,
                    min=_number(inputs.get("min")),
                    max=_number(inputs.get("max")),
                    consumers=consumers_of(workflow, node_id),
                )
            )
    if not result.outputs:
        outputs = [c for c, k in pack.placeholders.items() if k is Kind.OUTPUT]
        result.problems.append(f"no output placeholder: add a {' or '.join(outputs)} node")
    for group in (result.parameters + result.images, result.outputs):
        seen: dict[str, str] = {}
        for p in group:
            if p.port_id in seen:
                result.problems.append(
                    f"two placeholders named {p.name!r} (nodes {seen[p.port_id]} and {p.node_id})"
                )
            seen[p.port_id] = p.node_id
    return result


def missing_inputs(workflow: dict[str, Any], object_info: dict[str, Any]) -> list[str]:
    """Problems ComfyUI would reject the workflow for: unknown nodes, required inputs not set.

    A published workflow can be half-built (design note §3.3); check before offering it.
    """
    problems = []
    for node_id, node in workflow.items():
        cls = node.get("class_type", "")
        info = object_info.get(cls)
        if info is None:
            problems.append(f"node {node_id}: {cls or '?'} is not installed on the server")
            continue
        given = node.get("inputs") or {}
        for key in (info.get("input") or {}).get("required", {}):
            if key not in given:
                problems.append(f"node {node_id} ({cls}): required input {key!r} is not connected")
    return problems


def rewrite(
    workflow: dict[str, Any],
    values: dict[str, Any],
    images: dict[str, str],
    pack: Pack = HAYWIRE,
) -> dict[str, Any]:
    """The workflow to submit: placeholders replaced by the haywire node's values.

    Args:
        workflow: API-format workflow holding placeholders.
        values: parameter name → value; a missing name uses the placeholder's default.
        images: image placeholder name → base64-encoded PNG.

    Raises:
        KeyError: an image placeholder has no image.
    """
    interface = read_interface(workflow, pack)
    literal: dict[str, Any] = {}
    for p in interface.parameters:
        literal[p.node_id] = values.get(p.name, p.default)
    loaders: dict[str, dict[str, Any]] = {}
    for p in interface.images:
        if p.name not in images:
            raise KeyError(f"no image for {p.name!r}")
        loaders[p.node_id] = {
            "class_type": pack.image_loader,
            "inputs": {pack.image_loader_input: images[p.name]},
        }

    out: dict[str, Any] = {}
    for node_id, node in workflow.items():
        if node_id in literal:
            continue
        if node_id in loaders:
            out[node_id] = loaders[node_id]
            continue
        inputs = {}
        for key, value in (node.get("inputs") or {}).items():
            linked = isinstance(value, list) and len(value) == 2 and str(value[0]) in literal
            inputs[key] = literal[str(value[0])] if linked else value
        copy = {"class_type": node["class_type"], "inputs": inputs}
        if "_meta" in node:
            copy["_meta"] = node["_meta"]
        out[node_id] = copy
    return out
