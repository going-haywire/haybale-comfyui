"""Fixtures for this repo's own suite.

Mirrors the monorepo's ``library_system`` fixture: the installed haywire libraries
(haybale-core, haybale-image, ...) load through their entry points, this repo's
library from ``barn/``. No test needs a ComfyUI server.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# Import haywire's node package first: importing haybale_comfyui (whose __init__ pulls the
# registries) before it trips a circular import inside haywire 0.3.4.
import haywire.core.node  # noqa: F401


@pytest.fixture(scope="session")
def project_root() -> Path:
    """The repo root (the directory holding ``barn/``)."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session", autouse=True)
def _isolated_home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Point HOME at a temp dir so library enables never write into the real ``~/.haywire``."""
    home = tmp_path_factory.mktemp("home")
    previous = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    yield home
    if previous is not None:
        os.environ["HOME"] = previous


@pytest.fixture(scope="session")
def library_system(project_root: Path, _isolated_home: Path) -> Iterator[Any]:
    """A fully initialised library system with this repo's library loaded."""
    from haywire.core.di.config import set_global_injector, set_library_system
    from haywire.core.di.test_config import create_test_library_system

    service = create_test_library_system(
        workspace_root=str(project_root),
        library_paths=[str(project_root / "barn")],
        load_libraries=True,
        enable_file_watching=False,
    )
    set_library_system(service)
    set_global_injector(service.injector)

    yield service

    lib_registry = service.get_library_registry()
    if hasattr(lib_registry, "stop_file_watching"):
        lib_registry.stop_file_watching()
    set_library_system(None)
