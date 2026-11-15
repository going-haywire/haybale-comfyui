"""Library settings panel for the ComfyUI library, on the ``Barns`` surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

from haywire.api.workbench import BarnsSurface, BasePanel, PanelLayout, hui, panel, render_schema

from haybale_comfyui.settings.comfyui_settings import ComfyUISettings

if TYPE_CHECKING:
    from haywire.api.workbench import SessionContext


@panel(
    surface=BarnsSurface,
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
