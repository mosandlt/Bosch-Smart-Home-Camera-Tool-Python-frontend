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
from typing import Any, Callable

from nicegui import ui

from bosch_camera_frontend.adapters import cli_bridge

# Placeholder 1×1 *fully transparent* PNG shown while the real snapshot loads,
# so the card's grey background (#f1f3f5) shows through. The previous value
# decoded to a half-opaque green pixel (0,255,0,127) which object-fit:cover
# stretched into a solid green block for offline / not-yet-loaded cameras.
_PLACEHOLDER_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="
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
        cam_info: dict[str, Any],
        token: str,
        cfg: dict[str, Any],
        on_click: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        super().__init__()
        self._cam_info = cam_info
        self._token = token
        self._cfg = cfg
        self._on_click = on_click
        self._snap_bytes: bytes | None = None
        self._last_snap_ts: float = 0.0
        self._privacy_on: bool = False
        self._online: bool = False
        # Suppress on_change while we programmatically sync the toggle from
        # the server (set_value also fires on_change). Without this guard,
        # every status refresh would issue a PUT and surface "Camera offline"
        # for the OFFLINE cams.
        self._suppress_toggle_event: bool = False

        self._build()

    def _build(self) -> None:
        # HA/Apple-style: rounded-2xl, soft shadow, no Quasar default border,
        # generous padding. Status communicated via a small colored dot, not a
        # filled badge — keeps the card calm visually.
        self.classes(
            "rounded-2xl shadow-md p-0 overflow-hidden bg-white "
            "hover:shadow-lg transition-shadow duration-200"
        )
        self.style("border: none;")
        with self:
            # Snapshot — full-width 16:9 hero area at the top, no margins.
            self._snapshot_img = (
                ui.image(_PLACEHOLDER_SRC)
                .classes("w-full cursor-pointer")
                .style(
                    "aspect-ratio: 16/9; object-fit: cover; background-color: #f1f3f5;"
                )
            )
            if self._on_click:
                self._snapshot_img.on("click", lambda: self._on_click(self._cam_info))

            # Body — name + status dot + meta + controls. Padded.
            with ui.column().classes("p-4 gap-2 w-full"):
                with ui.row().classes("items-center justify-between w-full"):
                    with ui.row().classes("items-center gap-2"):
                        # sanitize=False: static inline-styled markup, no user
                        # input (NiceGUI 3.x sanitizes ui.html by default).
                        self._status_dot = ui.html(
                            '<div style="width:10px;height:10px;border-radius:50%;'
                            'background:#9ca3af;"></div>',
                            sanitize=False,
                        )
                        ui.label(self._cam_info.get("name", "Camera")).classes(
                            "text-base font-semibold text-gray-900"
                        )
                    self._status_badge = ui.label("…").classes(
                        "text-xs text-gray-400 tracking-wide uppercase"
                    )

                # Subtitle: model + firmware
                with ui.row().classes("items-center gap-2 -mt-1"):
                    ui.label(self._cam_info.get("model", "")).classes(
                        "text-xs text-gray-500"
                    )
                    fw = self._cam_info.get("firmware", "")
                    if fw:
                        ui.label("·").classes("text-xs text-gray-400")
                        ui.label(f"FW {fw}").classes("text-xs text-gray-500")

                # Divider + controls
                ui.separator().classes("my-2 opacity-30")
                with ui.row().classes("items-center justify-between w-full"):
                    # Privacy switch — iOS-style pill
                    with ui.row().classes("items-center gap-2"):
                        self._privacy_toggle = ui.switch(
                            on_change=self._handle_privacy_toggle,
                        ).props("color=primary keep-color")
                        ui.label("Privacy").classes("text-sm text-gray-700")
                        ui.tooltip("Privacy mode hides the camera feed")
                    # Right-aligned icon buttons
                    with ui.row().classes("items-center gap-1"):
                        ui.button(
                            icon="refresh",
                            on_click=self._refresh_snapshot,
                        ).props("flat round dense color=grey-7").tooltip(
                            "Refresh snapshot"
                        )
                        if self._on_click:
                            ui.button(
                                icon="arrow_forward_ios",
                                on_click=lambda: self._on_click(self._cam_info),
                            ).props("flat round dense color=grey-7").tooltip(
                                "Open detail"
                            )

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
            result = await cli_bridge.async_api_ping(session, cam_id)
            online = "ONLINE" in result.upper() or result == "pong"
            self._online = online
            # Disable controls visually + functionally when camera is offline.
            try:
                if online:
                    self._privacy_toggle.enable()
                else:
                    self._privacy_toggle.disable()
            except Exception:
                pass
            if online:
                self._status_badge.set_text("online")
                self._status_badge.classes(
                    replace="text-xs text-green-600 tracking-wide uppercase"
                )
                self._set_dot("#22c55e")
            else:
                self._status_badge.set_text("offline")
                self._status_badge.classes(
                    replace="text-xs text-gray-400 tracking-wide uppercase"
                )
                self._set_dot("#9ca3af")

            privacy = await cli_bridge.async_get_privacy_mode(session, cam_id)
            if privacy is not None:
                self._privacy_on = privacy.upper() == "ON"
                self._suppress_toggle_event = True
                try:
                    self._privacy_toggle.set_value(self._privacy_on)
                finally:
                    self._suppress_toggle_event = False
        except Exception:
            self._status_badge.set_text("error")
            self._status_badge.classes(
                replace="text-xs text-amber-600 tracking-wide uppercase"
            )
            self._set_dot("#f59e0b")

    def _set_dot(self, color: str) -> None:
        self._status_dot.set_content(
            f'<div style="width:10px;height:10px;border-radius:50%;background:{color};"></div>'
        )

    async def _refresh_snapshot(self) -> None:
        """Fetch a fresh snapshot and update the image element."""
        now = time.monotonic()
        if now - self._last_snap_ts < 5:
            return  # Debounce: don't fetch more often than every 5 s
        try:
            data = await cli_bridge.async_snap_from_proxy(
                self._cam_info, self._token, hq=False, cfg=self._cfg
            )
            if not data:
                # Fallback to latest event snapshot
                session = cli_bridge.make_session(self._token)
                data, _ = await cli_bridge.async_snap_from_events(
                    session, self._cam_info
                )
            if data:
                self._snap_bytes = data
                self._last_snap_ts = now
                b64 = base64.b64encode(data).decode()
                self._snapshot_img.set_source(f"data:image/jpeg;base64,{b64}")
        except Exception:
            pass  # Keep showing last good snapshot on transient errors

    async def _handle_privacy_toggle(self, e: Any) -> None:
        """Toggle privacy mode on/off via cloud API."""
        if self._suppress_toggle_event:
            return  # Programmatic set_value, not a user click.
        new_state = e.value
        if not self._online:
            # Revert visually and surface the truth without a useless PUT.
            self._suppress_toggle_event = True
            try:
                self._privacy_toggle.set_value(not new_state)
            finally:
                self._suppress_toggle_event = False
            ui.notify("Camera is offline — privacy unchanged", color="warning")
            return
        try:
            session = cli_bridge.make_session(self._token)
            cam_id = self._cam_info.get("id", "")
            ok, err = await cli_bridge.async_set_privacy_mode(
                session, cam_id, on=new_state
            )
            if ok:
                self._privacy_on = new_state
                mode = "ON" if new_state else "OFF"
                ui.notify(
                    f"Privacy {mode} — {self._cam_info.get('name', '')}",
                    color="info",
                )
            else:
                self._privacy_toggle.set_value(not new_state)
                ui.notify(f"Privacy toggle failed: {err}", color="negative")
        except Exception as exc:
            self._privacy_toggle.set_value(not new_state)
            ui.notify(f"Error: {exc}", color="negative")
