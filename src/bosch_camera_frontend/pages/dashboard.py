"""Dashboard page — /

Shows all cameras as cards with status, snapshot thumbnail, and privacy toggle.
Bottom toolbar: Settings, Logs (stub), Reload Cameras.

TODO Phase 2: async background refresh so card loading doesn't block UI.

Unread event badges are wired on each camera card (see CameraCard).
"""

from __future__ import annotations

from typing import Any

from nicegui import app, ui

from bosch_camera_frontend.adapters import cli_bridge
from bosch_camera_frontend.components.camera_card import CameraCard


def _navigate_to_camera(cam_info: dict[str, Any]) -> None:
    name = cam_info.get("name", "")
    ui.navigate.to(f"/camera/{name}")


def _build_error_state(message: str) -> None:
    with ui.card().classes("bg-red-50 border border-red-300 p-4 w-full"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("error_outline", color="negative")
            ui.label(message).classes("text-sm text-red-700")
        ui.label(
            "Check that bosch_config.json exists and your token is valid."
        ).classes("text-xs text-gray-500 mt-1")


@ui.page("/")
async def dashboard_page() -> None:
    """Main dashboard — camera overview."""
    # Shared state stored per NiceGUI client session via app.storage.client
    cfg = app.storage.general.get("cfg")
    token = app.storage.general.get("token")

    ui.page_title("Bosch Camera")

    # Body background — light neutral, HA/Apple-like
    ui.add_head_html(
        "<style>body{background:#f5f5f7;font-family:-apple-system,BlinkMacSystemFont,"
        '"SF Pro Text","Segoe UI",Roboto,sans-serif;}</style>'
    )

    # Translucent header bar, Apple-style
    with (
        ui.header(elevated=False)
        .classes("items-center justify-between px-6 py-3")
        .style(
            "background:rgba(255,255,255,0.85);backdrop-filter:blur(20px);"
            "border-bottom:1px solid rgba(0,0,0,0.06);color:#111;"
        )
    ):
        with ui.row().classes("items-center gap-2"):
            ui.icon("videocam", color="primary").classes("text-2xl")
            ui.label("Bosch Smart Camera").classes(
                "font-semibold text-lg text-gray-900"
            )
        with ui.row().classes("gap-1"):
            ui.button(
                icon="settings", on_click=lambda: ui.navigate.to("/settings")
            ).props("flat round dense color=grey-8").tooltip("Settings")

    # Main content — generous padding, max-width for desktop comfort
    with ui.column().classes("w-full max-w-7xl mx-auto px-6 py-8 gap-6"):
        if not cfg or not token:
            _build_error_state(
                "Configuration not loaded. "
                "Restart the app with --config path/to/bosch_config.json"
            )
            return

        # Section heading
        with ui.row().classes("items-baseline justify-between w-full"):
            ui.label("Kameras").classes("text-2xl font-semibold text-gray-900")
            ui.label("Live status & quick controls").classes("text-sm text-gray-500")

        # Camera grid
        cameras: dict[str, dict[str, Any]] = {}
        try:
            session = cli_bridge.make_session(token)
            cameras = await cli_bridge.async_get_cameras(cfg, session)
        except Exception as exc:
            _build_error_state(f"Failed to load cameras: {exc}")
            return

        if not cameras:
            with ui.card().classes(
                "rounded-2xl shadow-md p-8 w-full text-center bg-white"
            ):
                ui.icon("videocam_off", size="3rem", color="grey")
                ui.label("No cameras found.").classes("text-gray-500 mt-2")
                ui.label(
                    'Run "python3 bosch_camera.py rescan" to discover cameras.'
                ).classes("text-xs text-gray-400 mt-1")
            return

        with ui.grid(columns=1).classes("w-full sm:grid-cols-2 lg:grid-cols-3 gap-5"):
            for cam_name, cam_info in cameras.items():
                CameraCard(
                    cam_info=cam_info,
                    token=token,
                    cfg=cfg,
                    on_click=_navigate_to_camera,
                )

    # Footer — translucent like the header, minimal
    with (
        ui.footer(elevated=False)
        .classes("items-center justify-center px-6 py-3 gap-4")
        .style(
            "background:rgba(255,255,255,0.85);backdrop-filter:blur(20px);"
            "border-top:1px solid rgba(0,0,0,0.06);color:#666;"
        )
    ):
        ui.button("Reload", icon="refresh", on_click=lambda: ui.navigate.to("/")).props(
            "flat dense color=grey-7"
        )
        ui.button(
            "Settings", icon="settings", on_click=lambda: ui.navigate.to("/settings")
        ).props("flat dense color=grey-7")
