"""CameraCard — NiceGUI card element for a single camera tile on the dashboard.

Displays: camera name, online/offline status badge, privacy mode toggle,
and a snapshot thumbnail that refreshes every 30 s.

TODO Phase 2: convert snapshot refresh to async background task so it doesn't
block the NiceGUI event loop.
TODO Phase 2: add live-stream indicator (go2rtc heartbeat).
TODO Phase 3: show unread event count badge.
"""

from __future__ import annotations

import base64
import time
from typing import Callable

from nicegui import ui

from bosch_camera_frontend.adapters import cli_bridge

# Placeholder 1×1 transparent PNG used while the real snapshot loads.
_PLACEHOLDER_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwAD"
    "hgGAWjR9awAAAABJRU5ErkJgCC=="
)
_PLACEHOLDER_SRC = f"data:image/png;base64,{_PLACEHOLDER_B64}"

_SNAP_REFRESH_INTERVAL = 30  # seconds


class CameraCard(ui.card):
    """A NiceGUI card component representing one Bosch camera.

    Args:
        cam_info: Camera dict from bosch_camera.get_cameras() — must contain
                  keys: name, id, model, firmware.
        token: Current Bosch bearer token.
        cfg: Loaded bosch_config.json dict (needed for token refresh in snap).
        on_click: Optional callable invoked when the card is clicked (navigates
                  to detail page).
    """

    def __init__(
        self,
        cam_info: dict,
        token: str,
        cfg: dict,
        on_click: Callable | None = None,
    ) -> None:
        super().__init__()
        self._cam_info = cam_info
        self._token = token
        self._cfg = cfg
        self._on_click = on_click
        self._snap_bytes: bytes | None = None
        self._last_snap_ts: float = 0.0
        self._privacy_on: bool = False

        self._build()

    def _build(self) -> None:
        with self:
            with ui.row().classes("items-center justify-between w-full"):
                ui.label(self._cam_info.get("name", "Camera")).classes(
                    "text-lg font-bold"
                )
                self._status_badge = ui.badge("…", color="grey").classes("ml-2")

            # Snapshot thumbnail
            self._snapshot_img = ui.image(_PLACEHOLDER_SRC).classes(
                "w-full rounded mt-2 cursor-pointer"
            ).style("max-height: 180px; object-fit: cover;")
            if self._on_click:
                self._snapshot_img.on("click", lambda: self._on_click(self._cam_info))

            # Info row
            with ui.row().classes("text-xs text-gray-500 mt-1 gap-2"):
                model = self._cam_info.get("model", "")
                ui.label(model)
                fw = self._cam_info.get("firmware", "")
                if fw:
                    ui.label(f"FW {fw}")

            # Controls row
            with ui.row().classes("items-center mt-2 gap-2"):
                # Privacy toggle
                self._privacy_toggle = ui.switch(
                    # TODO: use t("cmd.privacy.label") once CLI key confirmed
                    "Privacy",
                    on_change=self._handle_privacy_toggle,
                ).props("dense")
                ui.tooltip("Enable privacy mode (disables camera feed)")

                # Manual snapshot refresh
                ui.button(
                    icon="refresh",
                    on_click=self._refresh_snapshot,
                ).props("flat dense").tooltip("Refresh snapshot now")

                # Navigate to detail
                if self._on_click:
                    ui.button(
                        icon="open_in_new",
                        on_click=lambda: self._on_click(self._cam_info),
                    ).props("flat dense").tooltip("Open camera detail")

        # Kick off initial data load
        ui.timer(0.1, self._initial_load, once=True)
        # Auto-refresh every 30 s
        ui.timer(_SNAP_REFRESH_INTERVAL, self._refresh_snapshot)

    async def _initial_load(self) -> None:
        await self._update_status()
        await self._refresh_snapshot()

    async def _update_status(self) -> None:
        """Ping the camera and update the status badge."""
        try:
            session = cli_bridge.make_session(self._token)
            cam_id = self._cam_info.get("id", "")
            result = cli_bridge.api_ping(session, cam_id)
            if "ONLINE" in result.upper() or result == "pong":
                self._status_badge.set_text("ONLINE")
                self._status_badge.props("color=positive")
            else:
                self._status_badge.set_text("OFFLINE")
                self._status_badge.props("color=negative")

            # Update privacy state from live API
            privacy = cli_bridge.get_privacy_mode(session, cam_id)
            if privacy is not None:
                self._privacy_on = privacy.upper() == "ON"
                self._privacy_toggle.set_value(self._privacy_on)
        except Exception as exc:
            self._status_badge.set_text("ERR")
            self._status_badge.props("color=warning")

    async def _refresh_snapshot(self) -> None:
        """Fetch a fresh snapshot and update the image element."""
        now = time.monotonic()
        if now - self._last_snap_ts < 5:
            return  # Debounce: don't fetch more often than every 5 s
        try:
            data = cli_bridge.snap_from_proxy(
                self._cam_info, self._token, hq=False, cfg=self._cfg
            )
            if not data:
                # Fallback to latest event snapshot
                session = cli_bridge.make_session(self._token)
                data, _ = cli_bridge.snap_from_events(session, self._cam_info)
            if data:
                self._snap_bytes = data
                self._last_snap_ts = now
                b64 = base64.b64encode(data).decode()
                self._snapshot_img.set_source(f"data:image/jpeg;base64,{b64}")
        except Exception:
            pass  # Keep showing last good snapshot on transient errors

    async def _handle_privacy_toggle(self, e) -> None:
        """Toggle privacy mode on/off via cloud API."""
        new_state = e.value
        try:
            session = cli_bridge.make_session(self._token)
            cam_id = self._cam_info.get("id", "")
            ok = cli_bridge.set_privacy_mode(session, cam_id, on=new_state)
            if ok:
                self._privacy_on = new_state
                mode = "ON" if new_state else "OFF"
                ui.notify(
                    f"Privacy {mode} — {self._cam_info.get('name', '')}",
                    color="info",
                )
            else:
                # Revert toggle on failure
                self._privacy_toggle.set_value(not new_state)
                ui.notify("Privacy toggle failed — check token", color="negative")
        except Exception as exc:
            self._privacy_toggle.set_value(not new_state)
            ui.notify(f"Error: {exc}", color="negative")
