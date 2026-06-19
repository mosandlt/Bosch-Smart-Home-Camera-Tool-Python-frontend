"""Bosch Smart Home Camera — NiceGUI Frontend.

Makes the Bosch CLI module (``bosch_camera``) importable for the bridge.

Resolution order:
1. Explicit ``--cli-path`` override (dev sibling checkout) — always wins.
2. ``bosch_camera`` already importable — e.g. installed via the
   ``bosch-smart-home-camera-tool`` PyPI dependency. No path injection needed.
3. Default sibling directory (../Bosch-Smart-Home-Camera-Tool-Python) for a
   side-by-side dev layout without a pip install.
"""

from __future__ import annotations

import importlib.util
import os
import sys

# Keep in sync with pyproject.toml [project].version.
__version__ = "0.1.4a0"

# ── CLI path resolution ────────────────────────────────────────────────────────
# The Python CLI repo must be on sys.path for `from bosch_camera import ...` to
# work.  We resolve the path once at import time so all sub-modules can do
# plain `from bosch_camera import ...` after this package is imported.

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CLI_PATH = os.path.normpath(
    os.path.join(
        _THIS_DIR,
        "..",  # src/
        "..",  # Bosch-Smart-Home-Camera-Tool-Python-frontend/
        "..",  # bosch kamera/
        "Bosch-Smart-Home-Camera-Tool-Python",
    )
)

BOSCH_CAMERA_CLI_PATH: str = os.environ.get("BOSCH_CAMERA_CLI_PATH", _DEFAULT_CLI_PATH)


def _inject_cli_path(path: str | None = None) -> None:
    """Insert *path* (or BOSCH_CAMERA_CLI_PATH) into sys.path[0].

    Idempotent — won't add duplicates.

    When *path* is None and ``bosch_camera`` is already importable (installed
    via the bosch-smart-home-camera-tool dependency, or already on sys.path),
    this is a no-op — no sibling directory is required.

    Raises:
        FileNotFoundError: if an explicit/default path does not exist.
        ImportError: if bosch_camera.py is not found inside the path.
    """
    # If the CLI is installed as a package, bosch_camera resolves without any
    # path juggling. Only an explicit override (path) forces the sibling layout.
    if path is None and importlib.util.find_spec("bosch_camera") is not None:
        return
    resolved = os.path.abspath(path or BOSCH_CAMERA_CLI_PATH)
    if not os.path.isdir(resolved):
        raise FileNotFoundError(
            f"Bosch CLI path not found: {resolved!r}\n"
            "Set BOSCH_CAMERA_CLI_PATH env or pass --cli-path to app.py."
        )
    bosch_camera_file = os.path.join(resolved, "bosch_camera.py")
    if not os.path.isfile(bosch_camera_file):
        raise ImportError(
            f"bosch_camera.py not found in {resolved!r}\n"
            "Check that BOSCH_CAMERA_CLI_PATH points to the Python CLI repo root."
        )
    # An explicit override must win even if a pip-installed bosch_camera was
    # already imported: evict it so the next import resolves from *resolved*.
    if path is not None:
        sys.modules.pop("bosch_camera", None)
    if resolved not in sys.path:
        sys.path.insert(0, resolved)


# Perform injection at package-import time using the default/env path.
# app.py may call _inject_cli_path() again with --cli-path override before
# any page module is imported.
try:
    _inject_cli_path()
except (FileNotFoundError, ImportError):
    # Don't crash on import — the adapter will surface a clear error at runtime.
    pass
