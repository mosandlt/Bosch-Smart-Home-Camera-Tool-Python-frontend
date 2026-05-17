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
import sys

logger = logging.getLogger(__name__)


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
) -> tuple[dict, str]:
    """Load bosch_config.json and extract token.

    Returns:
        (cfg dict, bearer token string)

    Raises:
        SystemExit: on fatal config / token error (logged clearly).
    """
    from bosch_camera_frontend.adapters.cli_bridge import (
        load_config,
        get_token,
        make_session,
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

    # Register pages by importing them (side effect: @ui.page decorators register routes)
    import bosch_camera_frontend.pages.dashboard  # noqa: F401
    import bosch_camera_frontend.pages.camera_detail  # noqa: F401
    import bosch_camera_frontend.pages.settings  # noqa: F401

    # Middleware: inject cfg + token into client storage for each new connection
    @ui.middleware
    async def _inject_cfg(request, call_next):
        # NiceGUI middleware signature: (request, call_next)
        # We piggyback on the request cycle to ensure client storage is populated.
        # app.storage.client is per-browser-tab and auto-cleared on disconnect.
        from nicegui import app as _app
        if not _app.storage.client.get("cfg"):
            _app.storage.client["cfg"] = cfg
            _app.storage.client["token"] = token
            _app.storage.client["config_path"] = _config_path or "(CLI default)"
        return await call_next(request)

    # 4. Start NiceGUI server
    ui.run(
        host=args.host,
        port=args.port,
        title="Bosch Camera",
        favicon="📷",
        reload=args.reload,
        show=False,  # Don't auto-open browser (headless-friendly)
        storage_secret="bosch-camera-frontend-dev-secret-CHANGE-ME-PHASE3",
        # TODO Phase 3: replace storage_secret with randomly generated secret
        # stored in config or env var; add proper authentication.
    )


if __name__ == "__main__":
    main()
