"""Dashboard page — /

Shows all cameras as cards with status, snapshot thumbnail, and privacy toggle.
Bottom toolbar: Settings, Logs (stub), Reload Cameras.

TODO Phase 2: async background refresh so card loading doesn't block UI.
TODO Phase 3: unread event badges on each camera card.
"""

from __future__ import annotations

from nicegui import app, ui

from bosch_camera_frontend.adapters import cli_bridge
from bosch_camera_frontend.components.camera_card import CameraCard


def _navigate_to_camera(cam_info: dict) -> None:
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
    cfg = app.storage.client.get("cfg")
    token = app.storage.client.get("token")

    ui.page_title("Bosch Camera Dashboard")

    with ui.header().classes("items-center justify-between px-4"):
        ui.label("Bosch Smart Camera").classes("text-white font-bold text-lg")
        with ui.row().classes("gap-2"):
            # TODO: use t("nav.settings") once CLI key confirmed
            ui.button(
                "Settings", icon="settings", on_click=lambda: ui.navigate.to("/settings")
            ).props("flat color=white dense")

    # Main content
    with ui.column().classes("w-full p-4 gap-4"):

        if not cfg or not token:
            _build_error_state(
                "Configuration not loaded. "
                "Restart the app with --config path/to/bosch_config.json"
            )
            return

        # Camera grid
        cameras: dict = {}
        try:
            session = cli_bridge.make_session(token)
            cameras = cli_bridge.get_cameras(cfg, session)
        except Exception as exc:
            _build_error_state(f"Failed to load cameras: {exc}")
            return

        if not cameras:
            with ui.card().classes("p-4 w-full text-center"):
                ui.icon("videocam_off", size="3rem", color="grey")
                # TODO: use t("cmd.status.no_cameras") if key exists
                ui.label("No cameras found in config.").classes("text-gray-500")
                ui.label(
                    'Run "python3 bosch_camera.py rescan" to discover cameras.'
                ).classes("text-xs text-gray-400 mt-1")
            return

        # Responsive grid: 1 col on mobile, 2 on md, 3 on xl
        with ui.grid(columns=1).classes(
            "w-full sm:grid-cols-2 lg:grid-cols-3 gap-4"
        ):
            for cam_name, cam_info in cameras.items():
                CameraCard(
                    cam_info=cam_info,
                    token=token,
                    cfg=cfg,
                    on_click=_navigate_to_camera,
                )

    # Bottom toolbar
    with ui.footer().classes("px-4 py-2 gap-2 justify-end"):
        ui.button(
            "Reload Cameras",
            icon="refresh",
            on_click=lambda: ui.navigate.to("/"),
        ).props("flat dense")
        ui.button(
            "Settings",
            icon="settings",
            on_click=lambda: ui.navigate.to("/settings"),
        ).props("flat dense")
        # TODO Phase 2: Logs page
        ui.button(
            "Logs",
            icon="article",
            on_click=lambda: ui.notify("Log viewer coming in Phase 2", color="info"),
        ).props("flat dense")
