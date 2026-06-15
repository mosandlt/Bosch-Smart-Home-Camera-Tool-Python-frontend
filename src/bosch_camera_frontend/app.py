"""Bosch Smart Camera — NiceGUI Frontend Entry Point.

Usage:
    python3 -m bosch_camera_frontend.app [OPTIONS]
    bosch-camera-frontend [OPTIONS]

Options:
    --config PATH       Path to bosch_config.json  [default: auto-detect]
    --port INT          HTTP port                  [default: 8080]
    --host STR          Bind address               [default: 127.0.0.1]
    --cli-path PATH     Path to Python CLI repo    [default: BOSCH_CAMERA_CLI_PATH env / sibling dir]
    --reload            Enable NiceGUI hot-reload  (dev mode)
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import sys
from typing import Any

logger = logging.getLogger(__name__)


def _resolve_storage_secret() -> str:
    """Return a storage secret for NiceGUI's signed session cookies.

    Priority:
    1. BOSCH_FRONTEND_STORAGE_SECRET env var (set this for a stable secret
       across restarts so sessions survive a reload).
    2. A fresh, cryptographically-random secret generated per process. Sessions
       are invalidated on restart, but no weak secret is ever shipped.

    Pre-Phase-4 a hardcoded placeholder secret was baked into the source — any
    reader of the repo could forge session cookies. Never hardcode it again.
    """
    env_secret = os.environ.get("BOSCH_FRONTEND_STORAGE_SECRET", "").strip()
    if env_secret:
        return env_secret
    logger.warning(
        "BOSCH_FRONTEND_STORAGE_SECRET not set — generating a random per-process "
        "secret. Sessions will reset on restart. Set the env var for persistence."
    )
    return secrets.token_urlsafe(32)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bosch-camera-frontend",
        description="NiceGUI browser frontend for Bosch Smart Home cameras",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to bosch_config.json (default: CLI repo default location)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        metavar="PORT",
        help="HTTP port (default: 8080)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        metavar="HOST",
        help="Bind address (default: 127.0.0.1 — localhost only)",
    )
    parser.add_argument(
        "--cli-path",
        dest="cli_path",
        metavar="PATH",
        default=None,
        help="Path to the Python CLI repo root (overrides BOSCH_CAMERA_CLI_PATH env)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable NiceGUI auto-reload (dev mode)",
    )
    return parser.parse_args(argv)


def _setup_cli_path(cli_path: str | None) -> None:
    """Override BOSCH_CAMERA_CLI_PATH env and re-inject path if --cli-path given."""
    if cli_path:
        os.environ["BOSCH_CAMERA_CLI_PATH"] = cli_path
    # Re-run injection with the (possibly updated) path
    from bosch_camera_frontend import _inject_cli_path

    _inject_cli_path(cli_path)


def _load_config_and_session(
    config_path: str | None,
) -> tuple[dict[str, Any], str]:
    """Load bosch_config.json and extract token.

    Returns:
        (cfg dict, bearer token string)

    Raises:
        SystemExit: on fatal config / token error (logged clearly).
    """
    from bosch_camera_frontend.adapters.cli_bridge import (
        load_config,
        get_token,
        set_lang,
        detect_lang,
    )

    try:
        cfg = load_config(config_path)
    except FileNotFoundError:
        logger.error(
            "Config file not found: %s\n"
            "Run: python3 bosch_camera.py  (first-run wizard creates it)",
            config_path or "auto",
        )
        sys.exit(1)
    except Exception as exc:
        logger.error("Failed to load config: %s", exc)
        sys.exit(1)

    # Init i18n
    lang = detect_lang(cfg)
    set_lang(lang)

    try:
        token = get_token(cfg)
    except ValueError as exc:
        logger.warning("No token in config: %s — UI will show token error", exc)
        token = ""

    return cfg, token


def _console_banner_html(version: str) -> str:
    """Return the ``<script>`` snippet that prints the Bosch styled version banner.

    Mirrors the HA card convention (red badge + white version chip).
    The snippet is injected once via ``ui.add_head_html(..., shared=True)`` so
    it fires on every page load without duplication.

    Args:
        version: The frontend version string, e.g. ``"0.1.1a0"``.

    Returns:
        A ``<script>`` HTML string ready for injection.
    """
    # Escape version defensively — it comes from a constant, but be explicit.
    safe_version = version.replace("\\", "\\\\").replace("`", "\\`")
    return (
        "<script>"
        "console.info("
        "`%c BOSCH-CAMERA-FRONTEND %c v{version} `,"
        '"color:#fff;background:#ea0016;font-weight:700;",'
        '"color:#ea0016;background:#fff;font-weight:700;"'
        ");"
        "</script>"
    ).format(version=safe_version)


def main(argv: list[str] | None = None) -> None:
    """Application entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    args = _parse_args(argv)

    # 1. Set up CLI path BEFORE any bosch_camera import
    _setup_cli_path(args.cli_path)

    # 2. Load config (may sys.exit on fatal error)
    cfg, token = _load_config_and_session(args.config)

    # 3. Import NiceGUI and register pages
    #    (import after CLI path is set so page modules can import cli_bridge)
    from nicegui import app as nicegui_app, ui

    # Store config + token in NiceGUI app storage so pages can access them
    # without passing globals.  app.storage.general persists across restarts;
    # we use a startup handler to populate client storage per-session.
    _config_path = args.config or ""

    @nicegui_app.on_startup
    async def _on_startup() -> None:
        logger.info("Bosch Camera Frontend starting on %s:%d", args.host, args.port)
        nicegui_app.storage.general["cfg"] = cfg
        nicegui_app.storage.general["token"] = token
        nicegui_app.storage.general["config_path"] = _config_path or "(CLI default)"

    @nicegui_app.on_shutdown
    def _on_shutdown() -> None:
        # Reap the shared go2rtc subprocess on graceful exit (complements the
        # atexit + SIGTERM hooks wired in go2rtc_manager.get_manager).
        from bosch_camera_frontend.adapters.go2rtc_manager import get_manager

        get_manager().stop()

    def _reload_config_and_token() -> tuple[dict[str, Any], str] | None:
        """Re-read bosch_config.json + refresh token. Updates app storage in
        place so all pages see the new state on next render. Used by the
        Settings "Reload" button when the user has run `token fix` in a
        terminal."""
        try:
            new_cfg, new_token = _load_config_and_session(args.config)
            nicegui_app.storage.general["cfg"] = new_cfg
            nicegui_app.storage.general["token"] = new_token
            return new_cfg, new_token
        except SystemExit:
            return None
        except Exception as exc:
            logger.error("Reload failed: %s", exc)
            return None

    # Expose the reloader so pages can trigger it via app.storage.
    nicegui_app.storage.general["__reload_fn_name__"] = "reload_config_and_token"
    import bosch_camera_frontend.adapters.cli_bridge as _br

    _br.reload_config_and_token = _reload_config_and_token  # type: ignore[attr-defined]

    # Register pages by importing them (side effect: @ui.page decorators register routes)
    import bosch_camera_frontend.pages.dashboard  # noqa: F401
    import bosch_camera_frontend.pages.camera_detail  # noqa: F401
    import bosch_camera_frontend.pages.settings  # noqa: F401

    # Inject styled console banner once for all pages (mirrors HA card convention).
    from bosch_camera_frontend import __version__

    ui.add_head_html(_console_banner_html(__version__), shared=True)

    # 4. Start NiceGUI server
    ui.run(
        host=args.host,
        port=args.port,
        title="Bosch Camera",
        favicon="📷",
        reload=args.reload,
        show=False,  # Don't auto-open browser (headless-friendly)
        storage_secret=_resolve_storage_secret(),
    )


if __name__ == "__main__":
    main()
