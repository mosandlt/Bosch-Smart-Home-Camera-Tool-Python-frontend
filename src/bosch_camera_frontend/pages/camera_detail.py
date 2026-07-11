"""Camera detail page — /camera/{name}

Shows full-size snapshot, live stream (if go2rtc available), camera controls,
and a table of recent events.

TODO Phase 2: async snapshot loop; FFmpeg/go2rtc HLS pipeline.
TODO Phase 2: pan slider (CAMERA_360 / pan_limit > 0).
TODO Phase 3: real-time event feed via FCM push WebSocket.
TODO Phase 3: event detail view with clip download.

Camera light, motion detection, and intrusion detection are wired to the
live cloud API via cli_bridge (async_get/set_light_override,
async_get/set_motion_detection, async_get/set_intrusion_detection).
"""

from __future__ import annotations

import base64
import datetime
import re
from typing import Any
from urllib.parse import unquote

from nicegui import app, ui

from bosch_camera_frontend.adapters import cli_bridge
from bosch_camera_frontend.adapters.go2rtc_manager import get_manager
from bosch_camera_frontend.adapters.stream_session import StreamSession
from bosch_camera_frontend.components.live_player import LivePlayer
from bosch_camera_frontend.components.live_snapshot_player import LiveSnapshotPlayer


def _stream_name(cam_name: str, cam_id: str = "") -> str:
    """go2rtc-safe stream key for a camera (lowercase slug, ``bosch_`` prefix).

    A trailing slice of the camera's unique id is appended so two cameras whose
    names slug to the same key (e.g. "Eyes Outdoor" / "Eyes-Outdoor") don't
    collide on one go2rtc stream and cross-wire their video.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", cam_name.lower()).strip("_") or "cam"
    suffix = re.sub(r"[^a-z0-9]+", "", cam_id.lower())[-8:]
    return f"bosch_{slug}_{suffix}" if suffix else f"bosch_{slug}"


def _format_event_ts(ts_str: str) -> str:
    """Best-effort timestamp formatting for event rows.

    Bosch event timestamps are offset-bearing in Java's ZonedDateTime form,
    e.g. "2026-06-18T06:06:30.499+02:00[Europe/Berlin]". `fromisoformat`
    cannot parse the trailing RFC-9557 "[zone]" suffix, so without stripping
    it every event time fell into the except branch and the raw, ugly string
    was shown verbatim. Strip the "[zone]" suffix (and map a "Z" to +00:00)
    before parsing. (Cross-version of HA issue #34.)
    """
    try:
        clean = ts_str.split("[", 1)[0].replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(clean)
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
            cam_info = (await cli_bridge.async_resolve_cam(cfg, cam_name)).get(cam_name)
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
            snap_img = (
                ui.image("")
                .classes("w-full")
                .style("max-height: 400px; object-fit: contain; background: #111;")
            )
            snap_status = ui.label("Loading snapshot…").classes(
                "text-xs text-gray-400 p-2"
            )

        async def load_snapshot() -> None:
            snap_status.set_text("Fetching snapshot…")
            try:
                data = await cli_bridge.async_snap_from_proxy(
                    cam_info, token, hq=True, cfg=cfg
                )
                if not data:
                    data, method = await cli_bridge.async_snap_from_events(
                        session, cam_info
                    )
                    if data:
                        snap_status.set_text("Snapshot via event history")
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
                    "Download: use CLI — python3 bosch_camera.py snapshot " + cam_name,
                    color="info",
                ),
            ).props("dense flat")

        # Trigger initial snapshot load
        ui.timer(0.1, load_snapshot, once=True)

        # ── Live Stream section ────────────────────────────────────────────
        with ui.expansion("Live Stream", icon="live_tv").classes("w-full"):

            async def _live_frame() -> bytes | None:
                # Lower-res for the live loop (lighter + faster than the hq still).
                return await cli_bridge.async_snap_from_proxy(
                    cam_info, token, hq=False, cfg=cfg
                )

            live_container = ui.column().classes("w-full")
            live_status = ui.label("").classes("text-xs text-gray-400 mt-2")

            def _mount_snapshot(reason: str) -> None:
                with live_container:
                    LiveSnapshotPlayer(_live_frame, cam_name=cam_name, interval=5.0)
                live_status.set_text(
                    f"{reason} Showing near-live snapshots (~5 s refresh; pauses "
                    "while the tab is hidden to spare the camera's scarce Bosch "
                    "session budget)."
                )

            async def _resolve_stream() -> dict[str, object] | None:
                return await cli_bridge.async_get_stream_url(
                    cam_info, token, hq=False, cfg=cfg
                )

            async def _setup_live() -> None:
                """Prefer real WebRTC via go2rtc; fall back to snapshot tier.

                The rtsps:// URL (with embedded creds) never leaves the server —
                go2rtc consumes it locally and the browser only gets the go2rtc
                base URL + stream name. A StreamSession keeps the source fresh
                against Gen2 credential rotation while the view is open.
                """
                mgr = get_manager()
                if not mgr.available:
                    _mount_snapshot(
                        "go2rtc not installed (brew install go2rtc for WebRTC + audio)."
                    )
                    return
                src_name = _stream_name(cam_name, cam_id)
                session = StreamSession(mgr, _resolve_stream, src_name)
                if not await session.start():
                    _mount_snapshot("Live stream unavailable.")
                    return
                with live_container:
                    LivePlayer(
                        mgr.base_url, src_name, cam_name=cam_name, audio_default=False
                    )
                live_status.set_text(
                    "WebRTC live (HLS fallback). Audio + Picture-in-Picture appear "
                    "once the stream is playing."
                )
                # Keep the go2rtc source fresh ahead of Bosch session/cred rotation,
                # and free the Bosch session + go2rtc producer when the tab closes.
                ui.timer(session.refresh_interval, session.refresh)
                app.on_disconnect(session.stop)

            ui.timer(0.1, _setup_live, once=True)

        # ── Controls section ───────────────────────────────────────────────
        with ui.card().classes("w-full p-4"):
            # TODO: use t("ui.controls.title") once key confirmed
            ui.label("Controls").classes("font-semibold mb-2")

            with ui.grid(columns=2).classes("gap-3"):
                # Privacy toggle
                privacy_state_label = ui.label("Privacy: loading…").classes(
                    "text-sm col-span-2"
                )
                privacy_switch = ui.switch(
                    "Privacy Mode",
                    on_change=lambda e: _toggle_privacy(e),
                )

                async def _load_privacy() -> None:
                    p = await cli_bridge.async_get_privacy_mode(session, cam_id)
                    if p is not None:
                        is_on = p.upper() == "ON"
                        privacy_switch.set_value(is_on)
                        privacy_state_label.set_text(
                            f"Privacy: {'ON 🔒' if is_on else 'OFF 👁️'}"
                        )
                    else:
                        privacy_state_label.set_text("Privacy: unavailable")

                async def _toggle_privacy(e: Any) -> None:
                    ok, err = await cli_bridge.async_set_privacy_mode(
                        session, cam_id, on=e.value
                    )
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
                    light_state_label = ui.label("Light: loading…").classes(
                        "text-sm col-span-2"
                    )
                    light_switch = ui.switch(
                        "Camera Light",
                        on_change=lambda e: _toggle_light(e),
                    )

                    async def _load_light() -> None:
                        ovr = await cli_bridge.async_get_light_override(session, cam_id)
                        if ovr is not None:
                            is_on = bool(ovr.get("frontLightOn", False))
                            light_switch.set_value(is_on)
                            light_state_label.set_text(
                                f"Light: {'ON 💡' if is_on else 'OFF 🌑'}"
                            )
                        else:
                            light_state_label.set_text("Light: unavailable")

                    async def _toggle_light(e: Any) -> None:
                        ok, err = await cli_bridge.async_set_light_override(
                            session, cam_id, front_on=e.value
                        )
                        if ok:
                            mode = "ON 💡" if e.value else "OFF 🌑"
                            light_state_label.set_text(f"Light: {mode}")
                            ui.notify(f"Light {mode}", color="info")
                        else:
                            light_switch.set_value(not e.value)
                            ui.notify(f"Light toggle failed: {err}", color="negative")

                    ui.timer(0.2, _load_light, once=True)

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
                        min=-pan_limit,
                        max=pan_limit,
                        step=1,
                        value=0,
                        on_change=lambda e: ui.notify(
                            # TODO Phase 2: call cmd_pan equivalent
                            f"Pan to {e.value}° — Phase 2",
                            color="info",
                        ),
                    ).classes("col-span-2")

        # ── Motion Detection section ───────────────────────────────────────
        with ui.card().classes("w-full p-4"):
            ui.label("Motion Detection").classes("font-semibold mb-2")

            _MOTION_SENSITIVITIES = (
                "OFF",
                "LOW",
                "MEDIUM_LOW",
                "MEDIUM_HIGH",
                "HIGH",
                "SUPER_HIGH",
            )
            motion_state_label = ui.label("Loading…").classes("text-sm")
            with ui.row().classes("items-center gap-3"):
                motion_switch = ui.switch("Enabled")
                motion_sensitivity = ui.select(
                    list(_MOTION_SENSITIVITIES),
                    value="MEDIUM_HIGH",
                    label="Sensitivity",
                ).classes("w-48")

            async def _load_motion() -> None:
                data = await cli_bridge.async_get_motion_detection(session, cam_id)
                if data is not None:
                    enabled = bool(data.get("enabled", False))
                    sens = data.get("motionAlarmConfiguration", "MEDIUM_HIGH")
                    motion_switch.set_value(enabled)
                    if sens in _MOTION_SENSITIVITIES:
                        motion_sensitivity.set_value(sens)
                    motion_state_label.set_text(
                        f"Motion: {'ENABLED ✅' if enabled else 'DISABLED ❌'}"
                    )
                else:
                    motion_state_label.set_text("Motion: unavailable")

            async def _apply_motion() -> None:
                ok, err = await cli_bridge.async_set_motion_detection(
                    session,
                    cam_id,
                    enabled=motion_switch.value,
                    sensitivity=motion_sensitivity.value,
                )
                if ok:
                    state = "ENABLED ✅" if motion_switch.value else "DISABLED ❌"
                    motion_state_label.set_text(f"Motion: {state}")
                    ui.notify("Motion settings updated", color="info")
                else:
                    # Re-sync from the server so the UI never claims a state
                    # the write didn't actually achieve (matches the
                    # revert-on-failure behavior of the privacy/light toggles).
                    ui.notify(f"Motion update failed: {err}", color="negative")
                    await _load_motion()

            ui.timer(0.2, _load_motion, once=True)
            ui.button("Apply", icon="check", on_click=_apply_motion).props(
                "dense flat"
            ).classes("mt-2")

        # ── Intrusion Detection section ────────────────────────────────────
        with ui.card().classes("w-full p-4"):
            ui.label("Intrusion Detection").classes("font-semibold mb-2")

            _INTRUSION_MODES = ("ALL_MOTIONS", "ZONES")
            intrusion_state_label = ui.label("Loading…").classes("text-sm")
            with ui.row().classes("items-center gap-3"):
                intrusion_switch = ui.switch("Enabled")
                intrusion_mode = ui.select(
                    list(_INTRUSION_MODES),
                    value="ALL_MOTIONS",
                    label="Mode",
                ).classes("w-40")
                intrusion_sensitivity = ui.number(
                    label="Sensitivity (0-7)", min=0, max=7, value=3, step=1
                ).classes("w-32")
                intrusion_distance = ui.number(
                    label="Distance (1-8)", min=1, max=8, value=5, step=1
                ).classes("w-32")

            async def _load_intrusion() -> None:
                data = await cli_bridge.async_get_intrusion_detection(session, cam_id)
                if data is not None:
                    enabled = bool(data.get("enabled", False))
                    mode = data.get("detectionMode", "ALL_MOTIONS")
                    intrusion_switch.set_value(enabled)
                    if mode in _INTRUSION_MODES:
                        intrusion_mode.set_value(mode)
                    intrusion_sensitivity.set_value(data.get("sensitivity", 3))
                    intrusion_distance.set_value(data.get("distance", 5))
                    intrusion_state_label.set_text(
                        f"Intrusion: {'ENABLED ✅' if enabled else 'DISABLED ❌'}"
                    )
                else:
                    intrusion_state_label.set_text(
                        "Intrusion: unavailable (not supported on this model?)"
                    )

            def _int_or(value: Any, default: int) -> int:
                # `value or default` would silently rewrite a legitimate 0 to
                # `default` (falsy-zero coercion) — only fall back on None.
                return int(value) if value is not None else default

            async def _apply_intrusion() -> None:
                ok, err = await cli_bridge.async_set_intrusion_detection(
                    session,
                    cam_id,
                    enabled=intrusion_switch.value,
                    # Always send detectionMode — this endpoint is a full-object
                    # PUT (like light/motion), so omitting it risks the server
                    # silently resetting the zone/all-motions mode, mirroring
                    # cmd_intrusion's always-send-4-fields behavior.
                    detection_mode=intrusion_mode.value,
                    sensitivity=_int_or(intrusion_sensitivity.value, 0),
                    distance=_int_or(intrusion_distance.value, 1),
                )
                if ok:
                    state = "ENABLED ✅" if intrusion_switch.value else "DISABLED ❌"
                    intrusion_state_label.set_text(f"Intrusion: {state}")
                    ui.notify("Intrusion settings updated", color="info")
                else:
                    ui.notify(f"Intrusion update failed: {err}", color="negative")
                    await _load_intrusion()

            ui.timer(0.2, _load_intrusion, once=True)
            ui.button("Apply", icon="check", on_click=_apply_intrusion).props(
                "dense flat"
            ).classes("mt-2")

        # ── Recent Events table ────────────────────────────────────────────
        with ui.card().classes("w-full p-4"):
            # TODO: use t("cmd.events.title") if key exists
            ui.label("Recent Events (last 10)").classes("font-semibold mb-2")

            events_container = ui.column().classes("w-full")

            async def _load_events() -> None:
                with events_container:
                    events_container.clear()
                    try:
                        events = await cli_bridge.async_api_get_events(
                            session, cam_id, limit=10
                        )
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
                            {
                                "name": "ts",
                                "label": "Time",
                                "field": "ts",
                                "align": "left",
                            },
                            {
                                "name": "type",
                                "label": "Type",
                                "field": "type",
                                "align": "left",
                            },
                            {
                                "name": "read",
                                "label": "Read",
                                "field": "read",
                                "align": "center",
                            },
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
