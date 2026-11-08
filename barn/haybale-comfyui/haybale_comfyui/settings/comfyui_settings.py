"""ComfyUISettings — which ComfyUI server to use, how to authenticate, how long to wait."""

from __future__ import annotations

import os

from haywire.barn.builtin.types import FLOAT, STRING
from haywire.core.settings import LibrarySettings, setting, settings

#: Address of a ComfyUI started with its defaults.
DEFAULT_URL = "http://127.0.0.1:8188"


@settings(namespace="comfyui", label="ComfyUI", description="Server address, authentication and timeout")
class ComfyUISettings(LibrarySettings):
    """The ComfyUI server that ComfyUI Workflow nodes talk to."""

    server_url = setting[STRING](
        DEFAULT_URL,
        label="Server URL",
        description="Address of the running ComfyUI server, e.g. http://127.0.0.1:8188",
    )
    auth_env = setting[STRING](
        "",
        label="Auth variable",
        description=(
            "Name of an environment variable holding the value of the Authorization header, "
            "e.g. COMFYUI_AUTH. Empty: no authentication. The value itself is never stored "
            "in a haywire file"
        ),
    )
    timeout = setting[FLOAT](
        30.0,
        label="Timeout (s)",
        description="How long one request to the server may take; a running workflow is not limited",
        min=1.0,
        max=3600.0,
    )


def auth_headers(env_name: str) -> dict[str, str]:
    """Return the Authorization header read from the environment variable *env_name*.

    Raises:
        LookupError: *env_name* is set but the variable does not exist or is empty.
    """
    name = (env_name or "").strip()
    if not name:
        return {}
    value = os.environ.get(name, "")
    if not value:
        raise LookupError(f"environment variable {name} is not set (ComfyUI settings, Auth variable)")
    return {"Authorization": value}
