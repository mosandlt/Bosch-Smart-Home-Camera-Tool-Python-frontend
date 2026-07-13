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
import os
import re
from typing import Any
from urllib.parse import unquote

from nicegui import app, ui

from bosch_camera_frontend.adapters import cli_bridge
from bosch_camera_frontend.adapters.go2rtc_manager import get_manager
from bosch_camera_frontend.adapters.nvr_manager import get_manager as get_nvr_manager
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
                    pan_label = ui.label(f"Pan (±{pan_limit}°): loading…").classes(
                        "text-sm self-center col-span-2"
                    )
                    pan_slider = (
                        ui.slider(
                            min=-pan_limit,
                            max=pan_limit,
                            step=1,
                            value=0,
                        )
                        .classes("col-span-2")
                        .props("label-always")
                    )

                    async def _load_pan() -> None:
                        data = await cli_bridge.async_get_pan(session, cam_id)
                        if data is not None:
                            pos = int(data.get("currentAbsolutePosition", 0))
                            pan_slider.set_value(pos)
                            pan_label.set_text(f"Pan (±{pan_limit}°): {pos}°")
                        else:
                            pan_label.set_text(f"Pan (±{pan_limit}°): unavailable")

                    async def _apply_pan() -> None:
                        target = int(pan_slider.value)
                        ok, err = await cli_bridge.async_set_pan(
                            session, cam_id, target
                        )
                        if ok:
                            pan_label.set_text(f"Pan (±{pan_limit}°): {target}°")
                            ui.notify(f"Pan set to {target}°", color="info")
                        else:
                            ui.notify(f"Pan failed: {err}", color="negative")
                            await _load_pan()

                    ui.timer(0.2, _load_pan, once=True)
                    ui.button("Move", icon="control_camera", on_click=_apply_pan).props(
                        "dense flat"
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

        # ── Sound Detection (glass-break / fire-alarm, Gen2 only) ──────────
        is_gen2 = str(cam_info.get("model", "")).startswith("HOME_")
        if is_gen2:
            with ui.card().classes("w-full p-4"):
                ui.label("Sound Detection").classes("font-semibold mb-2")
                sound_state_label = ui.label("Loading…").classes("text-sm")
                with ui.row().classes("items-center gap-3"):
                    glass_break_switch = ui.switch("Glass Break")
                    fire_alarm_switch = ui.switch("Fire/Smoke Alarm")

                async def _load_sound_detection() -> None:
                    data = await cli_bridge.async_get_audio_detection(session, cam_id)
                    if data is not None:
                        glass_break_switch.set_value(
                            bool(data.get("detectGlassBreak", False))
                        )
                        fire_alarm_switch.set_value(
                            bool(data.get("detectFireAlarm", False))
                        )
                        sound_state_label.set_text("Sound detection loaded")
                    else:
                        sound_state_label.set_text(
                            "Sound detection: unavailable (not supported on this model?)"
                        )

                async def _apply_sound_detection() -> None:
                    ok, err = await cli_bridge.async_set_audio_detection(
                        session,
                        cam_id,
                        glass_break=glass_break_switch.value,
                        fire_alarm=fire_alarm_switch.value,
                    )
                    if ok:
                        sound_state_label.set_text("Sound detection updated")
                        ui.notify("Sound detection updated", color="info")
                    else:
                        ui.notify(
                            f"Sound detection update failed: {err}", color="negative"
                        )
                        await _load_sound_detection()

                ui.timer(0.2, _load_sound_detection, once=True)
                ui.button("Apply", icon="check", on_click=_apply_sound_detection).props(
                    "dense flat"
                ).classes("mt-2")

        # ── WiFi Info (read-only) ───────────────────────────────────────────
        with ui.card().classes("w-full p-4"):
            ui.label("WiFi").classes("font-semibold mb-2")
            wifi_label = ui.label("Loading…").classes("text-sm")

            async def _load_wifi() -> None:
                data = await cli_bridge.async_get_wifi_info(session, cam_id)
                if data is not None:
                    ssid = data.get("ssid", data.get("SSID", "?"))
                    rssi = data.get(
                        "rssi", data.get("RSSI", data.get("signalLevel", "?"))
                    )
                    wifi_label.set_text(f"SSID: {ssid}   RSSI: {rssi}")
                else:
                    wifi_label.set_text("WiFi info unavailable (wired camera?)")

            ui.timer(0.2, _load_wifi, once=True)
            ui.button("Refresh", icon="refresh", on_click=_load_wifi).props(
                "dense flat"
            ).classes("mt-2")

        # ── Lighting Schedule (outdoor Eyes cameras with LED only) ─────────
        if cam_info.get("has_light"):
            with ui.card().classes("w-full p-4"):
                ui.label("Lighting Schedule").classes("font-semibold mb-2")
                lighting_state_label = ui.label("Loading…").classes("text-sm")
                with ui.row().classes("items-center gap-3"):
                    lighting_on_time = ui.input("On time (HH:MM)").classes("w-32")
                    lighting_off_time = ui.input("Off time (HH:MM)").classes("w-32")
                    lighting_motion_switch = ui.switch("Trigger on motion")
                    lighting_threshold = ui.number(
                        label="Darkness threshold (0-1)",
                        min=0.0,
                        max=1.0,
                        step=0.05,
                        value=0.3,
                    ).classes("w-40")

                async def _load_lighting_schedule() -> None:
                    data = await cli_bridge.async_get_lighting_schedule(session, cam_id)
                    if data is not None:
                        lighting_on_time.set_value(
                            str(data.get("generalLightOnTime", ""))[:5]
                        )
                        lighting_off_time.set_value(
                            str(data.get("generalLightOffTime", ""))[:5]
                        )
                        lighting_motion_switch.set_value(
                            bool(data.get("lightOnMotion", False))
                        )
                        lighting_threshold.set_value(data.get("darknessThreshold", 0.3))
                        lighting_state_label.set_text(
                            f"Schedule: {data.get('scheduleStatus', '?')}"
                        )
                    else:
                        lighting_state_label.set_text(
                            "Lighting schedule: unavailable (offline or not supported)"
                        )

                async def _apply_lighting_schedule() -> None:
                    ok, err = await cli_bridge.async_set_lighting_schedule(
                        session,
                        cam_id,
                        on_time=lighting_on_time.value or None,
                        off_time=lighting_off_time.value or None,
                        light_on_motion=lighting_motion_switch.value,
                        darkness_threshold=lighting_threshold.value,
                    )
                    if ok:
                        lighting_state_label.set_text("Lighting schedule updated")
                        ui.notify("Lighting schedule updated", color="info")
                    else:
                        ui.notify(
                            f"Lighting schedule update failed: {err}", color="negative"
                        )
                        await _load_lighting_schedule()

                ui.timer(0.2, _load_lighting_schedule, once=True)
                ui.button(
                    "Apply", icon="check", on_click=_apply_lighting_schedule
                ).props("dense flat").classes("mt-2")

        # ── Recording Options (cloud recording sound) ──────────────────────
        with ui.card().classes("w-full p-4"):
            ui.label("Cloud Recording").classes("font-semibold mb-2")
            recording_state_label = ui.label("Loading…").classes("text-sm")
            recording_switch = ui.switch("Record Sound")
            # Suppress the NEXT on_value_change firing caused by a
            # *programmatic* set_value() (initial load, or the revert-on-
            # failure below) — NiceGUI's ValueElement fires on_value_change
            # for ANY value change regardless of source (verified against
            # nicegui.binding.BindableProperty.__set__: it only skips when
            # the new value equals the current one). Without this guard,
            # (a) the initial load can itself trigger an unwanted API write
            # whenever the server's real value differs from the switch's
            # False default, and (b) a revert-on-failure re-fires the same
            # handler with the opposite value, which — if the outage is
            # ongoing — recurses indefinitely, hammering the API from one
            # failed toggle (bug-hunt finding 2026-07-11).
            _recording_suppress_next = False

            async def _load_recording() -> None:
                nonlocal _recording_suppress_next
                data = await cli_bridge.async_get_recording_options(session, cam_id)
                if data is not None:
                    _recording_suppress_next = True
                    recording_switch.set_value(bool(data.get("recordSound", False)))
                    recording_state_label.set_text("Recording options loaded")
                else:
                    recording_state_label.set_text("Recording options unavailable")

            async def _toggle_recording(e: Any) -> None:
                nonlocal _recording_suppress_next
                if _recording_suppress_next:
                    _recording_suppress_next = False
                    return
                ok, err = await cli_bridge.async_set_recording_options(
                    session, cam_id, sound_on=e.value
                )
                if ok:
                    recording_state_label.set_text(
                        f"Record Sound: {'ON' if e.value else 'OFF'}"
                    )
                    ui.notify("Recording options updated", color="info")
                else:
                    _recording_suppress_next = True
                    recording_switch.set_value(not e.value)
                    ui.notify(f"Recording update failed: {err}", color="negative")

            recording_switch.on_value_change(_toggle_recording)
            ui.timer(0.2, _load_recording, once=True)

        # ── Local NVR Recording (Beta, continuous mode only) ────────────────
        # Phase 1 of a Mini-NVR port (see nvr_manager.py docstring) — one
        # long-running ffmpeg segmenter per camera writing rolling MP4s to
        # disk. Purely local/process-scoped: unlike the "Cloud Recording"
        # toggle above, nothing here calls the Bosch API. Recording is NOT
        # tied to this page being open (no app.on_disconnect teardown) —
        # closing the tab must not stop an in-progress local recording.
        # event_buffered (motion/person-triggered clips) is intentionally
        # NOT implemented — this frontend has no event/FCM consumer yet.
        with ui.card().classes("w-full p-4"):
            ui.label("Local Recording (Beta)").classes("font-semibold mb-2")
            nvr_state_label = ui.label("Loading…").classes("text-sm")

            default_nvr_folder = cam_info.get("nvr_recording_folder") or os.path.join(
                "captures", cam_name, "nvr"
            )
            nvr_folder_input = ui.input(
                "Recording folder", value=default_nvr_folder
            ).classes("w-full")
            nvr_switch = ui.switch("Continuous Recording")
            ui.label(
                "Continuous mode: rolling 5-min MP4 segments (H.264 copy, no "
                "transcode) written straight to the folder above while ON. "
                "Requires ffmpeg. Event-triggered clips (motion/person) are "
                "not implemented yet."
            ).classes("text-xs text-gray-400 mt-1")

            _nvr_stream_name = _stream_name(cam_name, cam_id)
            # Guard against the SAME programmatic-set_value() -> unwanted-write
            # bug the "Cloud Recording" section above already had to fix
            # (bug-hunt finding 2026-07-11): NiceGUI's ValueElement fires
            # on_value_change for ANY change regardless of source, so
            # _load_nvr_state's own set_value(is_rec) below would otherwise
            # re-fire _toggle_nvr and spuriously re-start/persist a recording
            # that's already running every time this page is (re)opened.
            _nvr_suppress_next = False

            def _nvr_resolver() -> dict[str, Any] | None:
                # SYNC on purpose — runs on the NVRManager watcher thread, not
                # the event loop (see nvr_manager.StreamResolver contract).
                return cli_bridge.get_stream_url(cam_info, token, hq=False, cfg=cfg)

            async def _load_nvr_state() -> None:
                nonlocal _nvr_suppress_next
                mgr = get_nvr_manager()
                if not mgr.available:
                    nvr_state_label.set_text(
                        "Local Recording: ffmpeg not installed "
                        "(brew install ffmpeg / apt-get install ffmpeg)"
                    )
                    nvr_switch.disable()
                    return
                is_rec = mgr.is_recording(_nvr_stream_name)
                _nvr_suppress_next = True
                nvr_switch.set_value(is_rec)
                nvr_state_label.set_text(
                    f"Local Recording: {'ON 🔴' if is_rec else 'OFF'}"
                )

            async def _toggle_nvr(e: Any) -> None:
                nonlocal _nvr_suppress_next
                if _nvr_suppress_next:
                    _nvr_suppress_next = False
                    return
                mgr = get_nvr_manager()
                folder = nvr_folder_input.value or default_nvr_folder
                cam_info["nvr_recording_folder"] = folder
                cam_info["nvr_recording_enabled"] = bool(e.value)
                try:
                    cli_bridge.save_config(cfg)
                except Exception:
                    pass  # persistence is best-effort; toggle still applies live

                if e.value:
                    ok = await mgr.async_start_recording(
                        _nvr_stream_name, _nvr_resolver, folder
                    )
                    if ok:
                        nvr_state_label.set_text(f"Local Recording: ON 🔴 ({folder})")
                        ui.notify("Local recording started", color="info")
                    else:
                        nvr_switch.set_value(False)
                        nvr_state_label.set_text(
                            "Local Recording: failed to start (ffmpeg missing?)"
                        )
                        ui.notify("Local recording failed to start", color="negative")
                else:
                    await mgr.async_stop_recording(_nvr_stream_name)
                    nvr_state_label.set_text("Local Recording: OFF")
                    ui.notify("Local recording stopped", color="info")

            nvr_switch.on_value_change(_toggle_nvr)
            ui.timer(0.2, _load_nvr_state, once=True)

        # ── Siren / Alarm (Gen2 Indoor II only) ─────────────────────────────
        if cam_info.get("model") == "HOME_Eyes_Indoor":
            with ui.card().classes("w-full p-4"):
                ui.label("Siren / Alarm").classes("font-semibold mb-2")
                siren_state_label = ui.label("Ready").classes("text-sm")
                with ui.row().classes("items-center gap-3"):
                    siren_duration = ui.number(
                        label="Duration (s, 10-300)", min=10, max=300, step=5, value=30
                    ).classes("w-40")

                    async def _set_siren_duration() -> None:
                        secs = int(siren_duration.value or 30)
                        ok, err = await cli_bridge.async_set_siren_duration(
                            session, cam_id, secs
                        )
                        if ok:
                            siren_state_label.set_text(f"Duration set to {secs}s")
                            ui.notify(f"Siren duration set to {secs}s", color="info")
                        else:
                            ui.notify(f"Set duration failed: {err}", color="negative")

                    ui.button(
                        "Set Duration", icon="timer", on_click=_set_siren_duration
                    ).props("dense flat")

                async def _trigger_siren() -> None:
                    ok, err = await cli_bridge.async_trigger_siren(session, cam_id)
                    if ok:
                        siren_state_label.set_text("Siren TRIGGERED 🔔")
                        ui.notify("Siren triggered", color="warning")
                    else:
                        ui.notify(f"Siren trigger failed: {err}", color="negative")

                async def _stop_siren() -> None:
                    ok, err = await cli_bridge.async_trigger_siren(
                        session, cam_id, stop=True
                    )
                    if ok:
                        siren_state_label.set_text("Siren stopped")
                        ui.notify("Siren stopped", color="info")
                    else:
                        ui.notify(f"Siren stop failed: {err}", color="negative")

                with ui.row().classes("gap-2 mt-2"):
                    ui.button(
                        "Trigger Siren",
                        icon="notifications_active",
                        on_click=_trigger_siren,
                    ).props("color=negative dense")
                    ui.button("Stop", icon="stop", on_click=_stop_siren).props(
                        "dense flat"
                    )

        # ── Automation Rules (per-camera CRUD) ──────────────────────────────
        with ui.card().classes("w-full p-4"):
            ui.label("Automation Rules").classes("font-semibold mb-2")
            rules_container = ui.column().classes("w-full gap-1")

            async def _load_rules() -> None:
                with rules_container:
                    rules_container.clear()
                    rules = await cli_bridge.async_list_rules(session, cam_id)
                    if not rules:
                        ui.label("No rules configured.").classes(
                            "text-sm text-gray-400"
                        )
                        return
                    for rule in rules:
                        rule_id = str(rule.get("id", ""))
                        with ui.row().classes("items-center gap-2 w-full"):
                            ui.icon(
                                "check_circle" if rule.get("isActive") else "cancel",
                                color="positive" if rule.get("isActive") else "grey",
                            )
                            ui.label(
                                f"{rule.get('name', '?')}: "
                                f"{rule.get('startTime', '?')}–{rule.get('endTime', '?')}"
                            ).classes("text-sm flex-grow")

                            async def _delete(rid: str = rule_id) -> None:
                                ok, err = await cli_bridge.async_delete_rule(
                                    session, cam_id, rid
                                )
                                if ok:
                                    ui.notify("Rule deleted", color="info")
                                    await _load_rules()
                                else:
                                    ui.notify(f"Delete failed: {err}", color="negative")

                            ui.button(icon="delete", on_click=_delete).props(
                                "dense flat color=negative"
                            )

            with ui.row().classes("items-center gap-2 mt-2"):
                new_rule_name = ui.input("Name").classes("w-32")
                new_rule_start = ui.input("Start (HH:MM)").classes("w-28")
                new_rule_end = ui.input("End (HH:MM)").classes("w-28")

                async def _add_rule() -> None:
                    if (
                        not new_rule_name.value
                        or not new_rule_start.value
                        or not new_rule_end.value
                    ):
                        ui.notify("Name, start and end are required", color="negative")
                        return
                    ok, err = await cli_bridge.async_add_rule(
                        session,
                        cam_id,
                        name=new_rule_name.value,
                        start=new_rule_start.value,
                        end=new_rule_end.value,
                        weekdays=[0, 1, 2, 3, 4, 5, 6],
                    )
                    if ok:
                        new_rule_name.set_value("")
                        new_rule_start.set_value("")
                        new_rule_end.set_value("")
                        ui.notify("Rule added", color="info")
                        await _load_rules()
                    else:
                        ui.notify(f"Add rule failed: {err}", color="negative")

                ui.button("Add Rule", icon="add", on_click=_add_rule).props(
                    "dense flat"
                )

            ui.timer(0.3, _load_rules, once=True)

        # ── Friends / Camera Sharing (account-level) ────────────────────────
        with ui.card().classes("w-full p-4"):
            ui.label("Friends & Sharing").classes("font-semibold mb-2")
            friends_container = ui.column().classes("w-full gap-1")

            async def _load_friends() -> None:
                with friends_container:
                    friends_container.clear()
                    friends = await cli_bridge.async_list_friends(session)
                    if not friends:
                        ui.label("No friends invited.").classes("text-sm text-gray-400")
                        return
                    for friend in friends:
                        friend_id = str(friend.get("id", ""))
                        shared = friend.get("sharedVideoInputs", [])
                        is_shared = any(
                            str(s.get("videoInputId")) == str(cam_id) for s in shared
                        )
                        with ui.row().classes("items-center gap-2 w-full"):
                            ui.label(
                                f"{friend.get('nickName', friend.get('invitationEmail', '?'))} "
                                f"({friend.get('status', '?')})"
                            ).classes("text-sm flex-grow")
                            share_switch = ui.switch(
                                "Shares this camera", value=is_shared
                            )

                            async def _toggle_share(
                                e: Any,
                                fid: str = friend_id,
                                # Bind the *current* iteration's switch, not
                                # the free variable `share_switch` — without
                                # this default-arg capture, every row's
                                # revert-on-failure would resolve `share_switch`
                                # at call time (late binding) and always hit
                                # the LAST friend's switch instead of the one
                                # actually toggled (bug-hunt finding 2026-07-11).
                                switch: Any = share_switch,
                                # One-element list (not a bare bool) so each
                                # row's closure gets its own independent cell
                                # — evaluated fresh per loop iteration, same
                                # reasoning as the `switch` default above.
                                # Suppresses the re-entrant on_value_change
                                # firing that switch.set_value() below would
                                # otherwise trigger (see the recording-switch
                                # comment for the full NiceGUI mechanism);
                                # without it, a persistent outage would make
                                # a single failed toggle recurse indefinitely.
                                suppress: list[bool] = [False],  # noqa: B006
                            ) -> None:
                                if suppress[0]:
                                    suppress[0] = False
                                    return
                                if e.value:
                                    ok, err = await cli_bridge.async_share_camera(
                                        session, fid, cam_id
                                    )
                                else:
                                    ok, err = await cli_bridge.async_unshare_camera(
                                        session, fid, cam_id
                                    )
                                if ok:
                                    ui.notify("Sharing updated", color="info")
                                else:
                                    suppress[0] = True
                                    switch.set_value(not e.value)
                                    ui.notify(
                                        f"Sharing update failed: {err}",
                                        color="negative",
                                    )

                            share_switch.on_value_change(_toggle_share)

                            async def _remove(fid: str = friend_id) -> None:
                                ok, err = await cli_bridge.async_remove_friend(
                                    session, fid
                                )
                                if ok:
                                    ui.notify("Friend removed", color="info")
                                    await _load_friends()
                                else:
                                    ui.notify(f"Remove failed: {err}", color="negative")

                            ui.button(icon="person_remove", on_click=_remove).props(
                                "dense flat color=negative"
                            )

            with ui.row().classes("items-center gap-2 mt-2"):
                new_friend_email = ui.input("Email").classes("w-48")
                new_friend_nick = ui.input("Nickname").classes("w-32")

                async def _invite() -> None:
                    if not new_friend_email.value:
                        ui.notify("Email is required", color="negative")
                        return
                    ok, err = await cli_bridge.async_invite_friend(
                        session, new_friend_email.value, new_friend_nick.value or ""
                    )
                    if ok:
                        new_friend_email.set_value("")
                        new_friend_nick.set_value("")
                        ui.notify("Invitation sent", color="info")
                        await _load_friends()
                    else:
                        ui.notify(f"Invite failed: {err}", color="negative")

                ui.button("Invite", icon="person_add", on_click=_invite).props(
                    "dense flat"
                )

            ui.timer(0.3, _load_friends, once=True)

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
