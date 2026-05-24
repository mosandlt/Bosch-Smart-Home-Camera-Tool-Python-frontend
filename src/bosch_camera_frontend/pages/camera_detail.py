"""Camera detail page — /camera/{name}

Shows full-size snapshot, live stream (if go2rtc available), camera controls,
and a table of recent events.

TODO Phase 2: async snapshot loop; FFmpeg/go2rtc HLS pipeline.
TODO Phase 2: pan slider (CAMERA_360 / pan_limit > 0).
TODO Phase 3: real-time event feed via FCM push WebSocket.
TODO Phase 3: event detail view with clip download.
"""

from __future__ import annotations

import base64
import datetime
from urllib.parse import unquote

from nicegui import app, ui

from bosch_camera_frontend.adapters import cli_bridge
from bosch_camera_frontend.components.hls_player import HlsPlayer


def _format_event_ts(ts_str: str) -> str:
    """Best-effort timestamp formatting for event rows."""
    try:
        dt = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts_str


def _event_type_icon(etype: str) -> str:
    mapping = {
        "MOVEMENT": "directions_run",
        "PERSON": "person",
        "AUDIO_ALARM": "volume_up",
        "DOORBELL": "doorbell",
    }
    return mapping.get(etype.upper(), "notifications")


@ui.page("/camera/{name}")
async def camera_detail_page(name: str) -> None:
    """Detail view for a single camera."""
    cam_name = unquote(name)

    cfg = app.storage.general.get("cfg")
    token = app.storage.general.get("token")

    ui.page_title(f"Camera — {cam_name}")

    with ui.header().classes("items-center px-4 gap-2"):
        ui.button(
            icon="arrow_back",
            on_click=lambda: ui.navigate.to("/"),
        ).props("flat color=white dense")
        ui.label(cam_name).classes("text-white font-bold text-lg")

    with ui.column().classes("w-full p-4 gap-4"):

        if not cfg or not token:
            ui.notify("Config not loaded. Return to dashboard.", color="negative")
            return

        # Resolve camera info
        try:
            cam_info = cli_bridge.resolve_cam(cfg, cam_name).get(cam_name)
        except SystemExit:
            cam_info = None

        if not cam_info:
            with ui.card().classes("p-4"):
                ui.icon("error_outline", color="negative")
                ui.label(f"Camera '{cam_name}' not found in config.")
                ui.button(
                    "Back to Dashboard", on_click=lambda: ui.navigate.to("/")
                ).props("flat")
            return

        cam_id = cam_info.get("id", "")
        session = cli_bridge.make_session(token)

        # ── Snapshot section ───────────────────────────────────────────────
        with ui.card().classes("w-full p-0 overflow-hidden"):
            snap_img = ui.image("").classes("w-full").style(
                "max-height: 400px; object-fit: contain; background: #111;"
            )
            snap_status = ui.label("Loading snapshot…").classes(
                "text-xs text-gray-400 p-2"
            )

        async def load_snapshot() -> None:
            snap_status.set_text("Fetching snapshot…")
            try:
                data = cli_bridge.snap_from_proxy(
                    cam_info, token, hq=True, cfg=cfg
                )
                if not data:
                    data, method = cli_bridge.snap_from_events(session, cam_info)
                    if data:
                        snap_status.set_text(f"Snapshot via event history")
                    else:
                        snap_status.set_text("No snapshot available")
                        return
                else:
                    snap_status.set_text("Live snapshot ✓")
                b64 = base64.b64encode(data).decode()
                snap_img.set_source(f"data:image/jpeg;base64,{b64}")
            except Exception as exc:
                snap_status.set_text(f"Snapshot error: {exc}")

        with ui.row().classes("p-2 gap-2"):
            ui.button(
                "Refresh Snapshot",
                icon="refresh",
                on_click=load_snapshot,
            ).props("dense")
            # Manual snapshot download
            ui.button(
                "Download Snapshot",
                icon="download",
                on_click=lambda: ui.notify(
                    "Download: use CLI — python3 bosch_camera.py snapshot "
                    + cam_name,
                    color="info",
                ),
            ).props("dense flat")

        # Trigger initial snapshot load
        ui.timer(0.1, load_snapshot, once=True)

        # ── Live Stream section ────────────────────────────────────────────
        with ui.expansion("Live Stream", icon="live_tv").classes("w-full"):
            HlsPlayer(stream_url=None, cam_name=cam_name)
            ui.label(
                "Live stream requires go2rtc + FFmpeg (Phase 2). "
                "For now, use the CLI: python3 bosch_camera.py live " + cam_name
            ).classes("text-xs text-gray-400 mt-2")

        # ── Controls section ───────────────────────────────────────────────
        with ui.card().classes("w-full p-4"):
            # TODO: use t("ui.controls.title") once key confirmed
            ui.label("Controls").classes("font-semibold mb-2")

            with ui.grid(columns=2).classes("gap-3"):

                # Privacy toggle
                privacy_state_label = ui.label("Privacy: loading…").classes("text-sm col-span-2")
                privacy_switch = ui.switch(
                    "Privacy Mode",
                    on_change=lambda e: _toggle_privacy(e),
                )

                async def _load_privacy() -> None:
                    p = cli_bridge.get_privacy_mode(session, cam_id)
                    if p is not None:
                        is_on = p.upper() == "ON"
                        privacy_switch.set_value(is_on)
                        privacy_state_label.set_text(
                            f"Privacy: {'ON 🔒' if is_on else 'OFF 👁️'}"
                        )
                    else:
                        privacy_state_label.set_text("Privacy: unavailable")

                async def _toggle_privacy(e) -> None:
                    ok, err = cli_bridge.set_privacy_mode(session, cam_id, on=e.value)
                    if ok:
                        mode = "ON 🔒" if e.value else "OFF 👁️"
                        privacy_state_label.set_text(f"Privacy: {mode}")
                        ui.notify(f"Privacy {mode}", color="info")
                    else:
                        privacy_switch.set_value(not e.value)
                        ui.notify(f"Privacy toggle failed: {err}", color="negative")

                ui.timer(0.2, _load_privacy, once=True)

                # Light toggle (outdoor cameras only)
                if cam_info.get("has_light"):
                    ui.label("Light:").classes("text-sm self-center")
                    ui.switch(
                        "Camera Light",
                        on_change=lambda e: ui.notify(
                            # TODO Phase 2: call cmd_light / cmd_light equivalent
                            f"Light {'ON' if e.value else 'OFF'} — Phase 2",
                            color="info",
                        ),
                    )

                # Notifications toggle
                ui.label("Notifications:").classes("text-sm self-center")
                ui.switch(
                    "Push Notifications",
                    on_change=lambda e: ui.notify(
                        # TODO Phase 2: call cmd_notifications equivalent
                        f"Notifications {'ON' if e.value else 'OFF'} — Phase 2",
                        color="info",
                    ),
                )

                # Pan control (360 cameras only)
                pan_limit = cam_info.get("pan_limit", 0)
                if pan_limit and pan_limit > 0:
                    ui.label(f"Pan (±{pan_limit}°):").classes(
                        "text-sm self-center col-span-2"
                    )
                    ui.slider(
                        min=-pan_limit, max=pan_limit, step=1, value=0,
                        on_change=lambda e: ui.notify(
                            # TODO Phase 2: call cmd_pan equivalent
                            f"Pan to {e.value}° — Phase 2",
                            color="info",
                        ),
                    ).classes("col-span-2")

        # ── Recent Events table ────────────────────────────────────────────
        with ui.card().classes("w-full p-4"):
            # TODO: use t("cmd.events.title") if key exists
            ui.label("Recent Events (last 10)").classes("font-semibold mb-2")

            events_container = ui.column().classes("w-full")

            async def _load_events() -> None:
                with events_container:
                    events_container.clear()
                    try:
                        events = cli_bridge.api_get_events(session, cam_id, limit=10)
                    except Exception as exc:
                        ui.label(f"Could not load events: {exc}").classes(
                            "text-sm text-red-500"
                        )
                        return

                    if not events:
                        ui.label("No events found.").classes("text-sm text-gray-400")
                        return

                    with ui.table(
                        columns=[
                            {"name": "ts", "label": "Time", "field": "ts", "align": "left"},
                            {"name": "type", "label": "Type", "field": "type", "align": "left"},
                            {"name": "read", "label": "Read", "field": "read", "align": "center"},
                        ],
                        rows=[
                            {
                                "ts": _format_event_ts(
                                    ev.get("startTime", ev.get("timestamp", ""))
                                ),
                                "type": ev.get("type", "UNKNOWN"),
                                "read": "✓" if ev.get("isRead") else "●",
                            }
                            for ev in events[:10]
                        ],
                    ).classes("w-full text-sm"):
                        pass

            ui.timer(0.3, _load_events, once=True)
            ui.button(
                "Reload Events",
                icon="refresh",
                on_click=_load_events,
            ).props("dense flat").classes("mt-2")
