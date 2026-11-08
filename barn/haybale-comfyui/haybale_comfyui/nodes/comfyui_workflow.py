"""ComfyUI Workflow — run a workflow published from ComfyUI, with ports from its placeholders."""

from __future__ import annotations

import threading
from typing import Any

from haywire.barn.builtin.progress import ProgressSettings, progress_field
from haywire.barn.builtin.types import BOOL, CHOICES
from haywire.barn.builtin.widget_keys import BUTTON_WIDGET
from haywire.core.execution.execution_context import ExecutionContext
from haywire.core.node import BaseNode, NodeType, node
from haywire.core.node.node_warning import NodeWarning
from haywire.core.settings import NodeSettings, Promotable, bag, setting
from haywire.core.types.enums import PortType

from haybale_comfyui.runtime.client import Cancelled, ComfyClient, ComfyError
from haybale_comfyui.runtime.directory import Entry, directory_for
from haybale_comfyui.runtime.placeholders import Interface, Placeholder, read_interface, rewrite
from haybale_comfyui.settings.comfyui_settings import ComfyUISettings, auth_headers

#: Warning kinds on the card.
KIND_WORKFLOW = "comfyui-workflow"
KIND_UPDATE = "comfyui-update"
KIND_RUN = "comfyui-run"

#: Ids of the ports built from placeholders; nothing else is touched when they are rebuilt.
DYNAMIC_PORTS = r"^(param|image|out)_"


def _server() -> tuple[str, dict[str, str], float]:
    """URL, auth headers and timeout from the library settings.

    Raises:
        ValueError: the auth variable is named but not set.
    """
    settings = ComfyUISettings()
    try:
        headers = auth_headers(str(settings.auth_env))
    except LookupError as exc:
        raise ValueError(str(exc)) from exc
    return str(settings.server_url), headers, float(settings.timeout)


def workflow_names() -> list[str]:
    """Picker options: the workflows published on the configured server."""
    try:
        url, headers, _ = _server()
    except ValueError:
        return []
    return directory_for(url, headers).names()


def combo_options(object_info: dict[str, Any], class_type: str, input_name: str) -> list[str]:
    """The options of a COMBO input in ``/object_info``, or ``[]`` when it is not one."""
    inputs = (object_info.get(class_type) or {}).get("input") or {}
    spec = (inputs.get("required") or {}).get(input_name) or (inputs.get("optional") or {}).get(input_name)
    if not spec:
        return []
    head = spec[0]
    if isinstance(head, list):  # older format: the option list itself
        return [str(o) for o in head]
    if head == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        return [str(o) for o in spec[1].get("options", [])]
    return []


class WorkflowSource(NodeSettings):
    """Which published workflow the node runs."""

    workflow = setting[CHOICES](
        "",
        label="Workflow",
        description=(
            "A workflow open in ComfyUI that holds a Haywire Output, by its file name. "
            "Picking one rebuilds the node's inlets and outlets from its Haywire nodes"
        ),
        widget_config={"options": workflow_names, "new_value_mode": "add-unique"},
        promotable=Promotable.CONFIG,
        promote_default=PortType.CONFIG,
    )
    reload = setting[BOOL](
        False,
        label="Reload",
        description="Take the workflow's latest version from ComfyUI",
        promotable=Promotable.CONFIG,
        promote_default=PortType.CONFIG,
        widget={"key": BUTTON_WIDGET, "config": {"properties": {"text": "Reload", "icon": "refresh"}}},
    )


class WorkflowProgress(ProgressSettings):
    """Progress of the running workflow."""

    main = progress_field("Progress")


@node(
    label="ComfyUI Workflow",
    description="Runs a workflow on a ComfyUI server and returns its images",
    menu="image/comfyui",
    search_tags=["comfyui", "comfy", "workflow", "diffusion", "stable diffusion", "generate", "remote"],
    node_type=NodeType.DATA,
)
class ComfyUIWorkflowNode(BaseNode):
    """Runs a workflow on a ComfyUI server and returns its images.

    Build the workflow in ComfyUI (server address: *ComfyUI* library settings) with the
    comfyui-haywire nodes installed, and mark what haywire controls:

    - *Haywire Parameter* becomes an inlet (number, integer, toggle, text, prompt, choice).
    - *Haywire Image* becomes an IMAGE inlet.
    - *Haywire Output* becomes an IMAGE outlet.

    While the workflow is open in ComfyUI it appears under `Workflow` by its file name.
    Picking it copies it into this node, so the graph runs later without ComfyUI's page
    open. When the workflow changes in ComfyUI the card says so; press `Reload` to take
    the new version.

    The node runs again when an inlet changes. To get a new image from the same inputs,
    expose the seed as a Haywire Parameter and change it.
    """

    source = bag(WorkflowSource)
    progress = bag(WorkflowProgress)

    def init(self) -> None:
        pass  # every port comes from the picked workflow

    def post_init(self) -> None:
        self._lock = threading.Lock()
        self.source._subscribe_field("workflow", self._on_pick)
        self.source._subscribe_field("reload", self._on_reload)
        self._directory = None
        self._watch()

    # ── picking and reloading ─────────────────────────────────────────────

    def _watch(self) -> None:
        """Listen to the configured server's directory for new versions."""
        try:
            url, headers, _ = _server()
        except ValueError:
            return
        directory = directory_for(url, headers)
        if directory is not self._directory:
            if self._directory is not None:
                self._directory.remove_listener(self._on_published)
            directory.add_listener(self._on_published)
            self._directory = directory

    def _on_pick(self, value: Any, _old: Any) -> None:
        name = str(value or "")
        if not name or name == self.store.get("workflow_name"):
            return  # a load restores the saved name: keep the saved workflow
        self._take_latest(name)

    def _on_reload(self, value: Any, _old: Any) -> None:
        if value is not True:
            return
        name = str(self.store.get("workflow_name") or self.source.workflow or "")
        if name:
            self._take_latest(name)
        self.post_value("source.reload", False)

    def _take_latest(self, name: str) -> None:
        self._watch()
        entry = self._directory.get(name) if self._directory is not None else None
        if entry is None:
            self.wrapper.replace_warnings(
                KIND_WORKFLOW,
                [
                    NodeWarning(
                        f"{name!r} is not published: open it in ComfyUI",
                        source_version=None,
                        kind=KIND_WORKFLOW,
                    )
                ],
            )
            return
        self.apply_workflow(name, entry.workflow)

    def _on_published(self, entry: Entry) -> None:
        """A new version arrived (directory thread); only flag it."""
        with self._lock:
            mine = entry.name == self.store.get("workflow_name") and entry.workflow != self.store.get(
                "workflow"
            )
        if mine:
            self.wrapper.replace_warnings(
                KIND_UPDATE,
                [
                    NodeWarning(
                        "changed in ComfyUI: press Reload to use it", source_version=None, kind=KIND_UPDATE
                    )
                ],
            )

    def apply_workflow(self, name: str, workflow: dict[str, Any]) -> Interface:
        """Store *workflow* in the node and rebuild the ports from its placeholders."""
        interface = read_interface(workflow)
        options = self._choice_options(workflow, interface)
        with self._lock:
            self.store.workflow = workflow
            self.store.workflow_name = name
        with self.rejig(include=DYNAMIC_PORTS):
            for p in interface.parameters:
                self.add(self._parameter_spec(p, options.get(p.node_id, [])))
            for p in interface.images:
                self.add(self._image_spec(p))
            for p in interface.outputs:
                self.add(self._output_spec(p))
        if self.source.workflow != name:
            self.source.workflow = name
        self.wrapper.replace_warnings(KIND_UPDATE, [])
        self.wrapper.replace_warnings(
            KIND_WORKFLOW,
            [NodeWarning(m, source_version=None, kind=KIND_WORKFLOW) for m in interface.problems],
        )
        self.run_again()
        return interface

    def _choice_options(self, workflow: dict[str, Any], interface: Interface) -> dict[str, list[str]]:
        """For each choice parameter, the options of the first COMBO input it feeds."""
        wanted = [p for p in interface.parameters if p.type == "choice" and p.consumers]
        if not wanted:
            return {}
        try:
            url, headers, timeout = _server()
            with ComfyClient(url, headers=headers, timeout=timeout) as client:
                info = client.object_info()
        except (ValueError, ComfyError):
            return {}
        found = {}
        for p in wanted:
            node_id, input_name = p.consumers[0]
            found[p.node_id] = combo_options(info, workflow[node_id]["class_type"], input_name)
        return found

    @staticmethod
    def _parameter_spec(p: Placeholder, options: list[str]) -> Any:
        from haywire.barn.builtin.types import FLOAT, INT, STRING
        from haywire.barn.builtin.widgets import SelectWidget

        common = {"label": p.name, "description": f"Haywire Parameter {p.name!r} ({p.type})"}
        if p.type == "number":
            return FLOAT.as_inlet(p.port_id, default=float(p.default), **common)
        if p.type == "integer":
            return INT.as_inlet(p.port_id, default=int(p.default), **common)
        if p.type == "toggle":
            return BOOL.as_inlet(p.port_id, default=bool(p.default), **common)
        if p.type == "choice" and options:
            widget = SelectWidget.config(properties={"options": options, "new_value_mode": "add-unique"})
            return STRING.as_inlet(p.port_id, default=str(p.default or options[0]), widget=widget, **common)
        return STRING.as_inlet(p.port_id, default=str(p.default or ""), **common)

    @staticmethod
    def _image_spec(p: Placeholder) -> Any:
        from haybale_image.types.image import IMAGE

        return IMAGE.as_inlet(p.port_id, label=p.name, description=f"Haywire Image {p.name!r}")

    @staticmethod
    def _output_spec(p: Placeholder) -> Any:
        from haybale_image.types.image import IMAGE

        return IMAGE.as_outlet(p.port_id, label=p.name, description=f"Haywire Output {p.name!r}")

    # ── running ───────────────────────────────────────────────────────────

    def on_shutdown(self, context: ExecutionContext) -> None:
        client = getattr(self.cache, "client", None)
        if client is not None:
            client.close()
            self.cache.client = None

    def on_teardown(self) -> None:
        if getattr(self, "_directory", None) is not None:
            self._directory.remove_listener(self._on_published)
        client = getattr(self.cache, "client", None)
        if client is not None:
            client.close()

    def _client(self) -> ComfyClient:
        url, headers, timeout = _server()
        client = getattr(self.cache, "client", None)
        if client is None or client.base_url != url.rstrip("/") or client.headers != headers:
            if client is not None:
                client.close()
            client = self.cache.client = ComfyClient(url, headers=headers, timeout=timeout)
        return client

    def worker(self, context: ExecutionContext) -> None:
        from haybale_comfyui.runtime.images import decode_png, encode_png

        with self._lock:
            workflow = self.store.get("workflow")
        if not workflow:
            raise ValueError("no workflow: pick one under Workflow")
        interface = read_interface(workflow)
        if interface.problems:
            raise ValueError("; ".join(interface.problems))

        values = {p.name: self.value(p.port_id) for p in interface.parameters}
        images = {}
        for p in interface.images:
            image = self.value(p.port_id)
            if image is None or image.is_empty:
                raise ValueError(f"no image on {p.name}")
            images[p.name] = encode_png(image)
        prompt = rewrite(workflow, values, images)

        cancel = context.cancel.is_set if context.cancel is not None else None
        with self.progress.busy("main", "queued") as span:

            def report(tracker: Any) -> None:
                prog = tracker.progress
                if prog is not None and prog.max > 0:
                    span.step(prog.value / prog.max, f"node {prog.node}: {prog.value}/{prog.max}")

            try:
                tracker = self._client().run(prompt, on_progress=report, cancel=cancel)
            except Cancelled:
                return None
            except ComfyError as exc:
                raise RuntimeError(str(exc)) from exc

        notes = []
        for p in interface.outputs:
            pngs = tracker.images.get(p.name) or []
            if not pngs:
                notes.append(f"{p.name}: ComfyUI sent no image")
                continue
            if len(pngs) > 1:
                notes.append(f"{p.name}: {len(pngs)} images, the first is used")
            self.out(p.port_id, decode_png(pngs[0]))
        self.wrapper.replace_warnings(
            KIND_RUN, [NodeWarning(n, source_version=None, kind=KIND_RUN) for n in notes]
        )
        return None
