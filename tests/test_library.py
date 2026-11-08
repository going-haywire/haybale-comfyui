"""The library loads and registers its settings and panel."""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock

import pytest

SETTINGS = "haybale_comfyui.settings.comfyui_settings"
PANEL = "haybale_comfyui.panels.comfyui_settings_panel"


@pytest.mark.integration
def test_library_settings_have_their_defaults(library_system: Any) -> None:
    bag = importlib.import_module(SETTINGS).ComfyUISettings()
    assert bag.server_url == "http://127.0.0.1:8188"
    assert bag.auth_env == ""
    assert bag.timeout == 30.0


@pytest.mark.integration
def test_panel_is_registered_under_barns(library_system: Any) -> None:
    from haywire.barn.builtin.surfaces import Barns
    from haywire.ui.panel.registry import PanelRegistry

    panel_cls = importlib.import_module(PANEL).ComfyUISettingsPanel
    assert panel_cls.class_identity.surface is Barns
    panels = library_system.injector.get(PanelRegistry)
    assert panels.get(panel_cls.class_identity.registry_key) is not None


@pytest.mark.integration
def test_panel_draws_the_comfyui_settings(monkeypatch: pytest.MonkeyPatch, library_system: Any) -> None:
    mod = importlib.import_module(PANEL)
    calls = []
    monkeypatch.setattr(mod, "render_schema", lambda ctx, schema_cls, registry: calls.append(schema_cls))
    panel = mod.ComfyUISettingsPanel.__new__(mod.ComfyUISettingsPanel)
    panel.draw(MagicMock(), MagicMock())
    assert calls == [mod.ComfyUISettings]


def test_no_auth_variable_means_no_header(library_system: Any) -> None:
    assert importlib.import_module(SETTINGS).auth_headers("") == {}
    assert importlib.import_module(SETTINGS).auth_headers("   ") == {}


def test_auth_header_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, library_system: Any
) -> None:
    monkeypatch.setenv("COMFYUI_TEST_AUTH", "Bearer abc")
    assert importlib.import_module(SETTINGS).auth_headers("COMFYUI_TEST_AUTH") == {
        "Authorization": "Bearer abc"
    }


def test_missing_auth_variable_names_it(monkeypatch: pytest.MonkeyPatch, library_system: Any) -> None:
    monkeypatch.delenv("COMFYUI_TEST_AUTH", raising=False)
    with pytest.raises(LookupError, match="COMFYUI_TEST_AUTH"):
        importlib.import_module(SETTINGS).auth_headers("COMFYUI_TEST_AUTH")
