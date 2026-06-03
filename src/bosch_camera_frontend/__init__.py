"""Bosch Smart Home Camera — NiceGUI Frontend.

Injects the Bosch CLI repo into sys.path so its modules can be imported
directly without packaging it as a dependency.

Priority order for CLI path:
1. BOSCH_CAMERA_CLI_PATH environment variable
2. Default sibling directory (../Bosch-Smart-Home-Camera-Tool-Python)
"""

from __future__ import annotations

import os
import sys

# Keep in sync with pyproject.toml [project].version (released v0.1.1-alpha).
__version__ = "0.1.1a0"

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

    Raises:
        FileNotFoundError: if the path does not exist.
        ImportError: if bosch_camera.py is not found inside the path.
    """
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
