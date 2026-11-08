"""Library settings panel for the ComfyUI library, on the ``Barns`` surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

from haywire.barn.builtin.surfaces import Barns
from haywire.ui import elements as hui
from haywire.ui.panel import BasePanel, PanelLayout
from haywire.ui.panel.decorator import panel
from haywire.ui.panel.render_utils import render_schema

from haybale_comfyui.settings.comfyui_settings import ComfyUISettings

if TYPE_CHECKING:
    from haywire.core.session.context import SessionContext


@panel(
    surface=Barns,
    label="ComfyUI",
    description="Server address, authentication and timeout for ComfyUI workflows.",
    icon=hui.icon.models,
    order=20,
    default_open=False,
)
class ComfyUISettingsPanel(BasePanel):
    """Server address, authentication and timeout for ComfyUI workflows."""

    def draw(self, ctx: "SessionContext", layout: PanelLayout) -> None:
        registry = ctx.app.library_service.get_settings_registry()
        render_schema(ctx, ComfyUISettings, registry)
