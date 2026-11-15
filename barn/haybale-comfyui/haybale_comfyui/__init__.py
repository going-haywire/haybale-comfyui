"""
Local haybale library for the haybale-comfyui project.

Add your custom components in the corresponding folders:
- nodes/      — node definitions
- macros/     — macro documents (.hwm)
- types/      — custom data types
- widgets/    — UI widgets for data types
- skins/      — custom node skins
- adapters/   — type-to-type conversion adapters
- settings/   — library settings definitions
- states/     — library app and session states
- themes/     — workbench and node themes
- panels/     — custom UI panels
- editors/    — custom UI editors
"""

from pathlib import Path

from haywire.api import (
    AdapterRegistry,
    BaseLibrary,
    MacroRegistry,
    NodeRegistry,
    SettingsRegistry,
    SkinRegistry,
    ThemeRegistry,
    TypeRegistry,
    WidgetRegistry,
    library,
)
from haywire.api.workbench import EditorRegistry, PanelRegistry, StateRegistry


@library(
    file_watcher=True,
)
class Library(BaseLibrary):
    """Local project library — add your components in the subfolders."""

    def register_components(self):
        """Register all components with the global registries."""
        base_path = Path(__file__).parent

        self.add_folder_to_registry(
            folder_path=str(base_path / "settings"),
            registry_cls=SettingsRegistry,
        )

        self.add_folder_to_registry(
            folder_path=str(base_path / "states"),
            registry_cls=StateRegistry,
        )

        self.add_folder_to_registry(
            folder_path=str(base_path / "themes"),
            registry_cls=ThemeRegistry,
        )

        self.add_folder_to_registry(
            folder_path=str(base_path / "types"),
            registry_cls=TypeRegistry,
        )

        self.add_folder_to_registry(
            folder_path=str(base_path / "adapters"),
            registry_cls=AdapterRegistry,
        )

        self.add_folder_to_registry(
            folder_path=str(base_path / "widgets"),
            registry_cls=WidgetRegistry,
        )

        self.add_folder_to_registry(
            folder_path=str(base_path / "skins"),
            registry_cls=SkinRegistry,
        )

        self.add_folder_to_registry(
            folder_path=str(base_path / "nodes"),
            registry_cls=NodeRegistry,
        )

        self.add_folder_to_registry(
            folder_path=str(base_path / "macros"),
            registry_cls=MacroRegistry,
        )

        self.add_folder_to_registry(
            folder_path=str(base_path / "panels"),
            registry_cls=PanelRegistry,
        )

        self.add_folder_to_registry(
            folder_path=str(base_path / "editors"),
            registry_cls=EditorRegistry,
        )

    def validate(self) -> bool:
        """Validate library structure."""
        return True
