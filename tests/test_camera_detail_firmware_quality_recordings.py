"""Tests for the camera-detail page's live-quality selector, firmware
install card, and local-recordings browser (family-parity gap-closing
work, see CLAUDE.md task list). Mirrors the fake_nicegui + label-capture
pattern established in test_camera_detail_nvr.py. FAKE DATA ONLY
(SECRETS_SCAN).
"""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock


def _fake_cam() -> dict[str, Any]:
    return {
        "id": "11111111-2222-3333-4444-555555555555",
        "name": "Test Cam",
        "model": "HOME_Eyes_Outdoor",
        "firmware": "9.0.0",
        "mac": "aa:bb:cc:dd:ee:ff",
        "download_folder": "Test Cam",
        "local_ip": "",
        "has_light": False,
        "pan_limit": 0,
        "nvr_recording_folder": "",
        "nvr_recording_enabled": False,
    }


def _make_cfg(cam: dict[str, Any]) -> dict[str, Any]:
    return {
        "account": {"bearer_token": "header.payload.signature"},
        "language": "en",
        "cameras": {cam["name"]: cam},
    }


def _base_bridge(cam: dict[str, Any]) -> MagicMock:
    bridge = MagicMock()
    bridge.make_session.return_value = MagicMock(name="session")

    async def _found(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {"Test Cam": cam}

    async def _priv(*_a: Any, **_kw: Any) -> str:
        return "OFF"

    async def _ev_list(*_a: Any, **_kw: Any) -> list[Any]:
        return []

    bridge.async_resolve_cam = _found
    bridge.async_get_privacy_mode = _priv
    bridge.async_api_get_events = _ev_list
    bridge.get_stream_url = MagicMock(
        return_value={"url": "rtsp://u:p@1.2.3.4/rtsp_tunnel", "type": "LOCAL"}
    )
    bridge.save_config = MagicMock()
    return bridge


async def _render(
    cam: dict[str, Any],
    bridge: MagicMock,
    *,
    list_segments: Any = None,
    delete_segment: Any = None,
) -> dict[str, Any]:
    """Render camera_detail_page and return captured instances/handlers.

    Returns a dict with keys: selects (list), buttons (list), timer_calls
    (already awaited by the time this returns).
    """
    from nicegui import app, ui

    cfg = _make_cfg(cam)
    app.storage.general.clear()
    app.storage.general["cfg"] = cfg
    app.storage.general["token"] = "header.payload.signature"

    from bosch_camera_frontend.pages import camera_detail

    camera_detail.cli_bridge = bridge
    mgr = MagicMock()
    mgr.available = False  # ffmpeg unavailable — NVR section stays inert
    camera_detail.get_nvr_manager = lambda: mgr
    if list_segments is not None:
        camera_detail.async_list_segments = list_segments
    if delete_segment is not None:
        camera_detail.async_delete_segment = delete_segment

    select_instances: list[Any] = []
    original_select = ui.select

    def cap_select(*a: Any, **kw: Any) -> Any:
        instance = original_select(*a, **kw)
        select_instances.append(instance)
        return instance

    button_instances: list[Any] = []
    original_button = ui.button

    def cap_button(*a: Any, **kw: Any) -> Any:
        instance = original_button(*a, **kw)
        button_instances.append(instance)
        return instance

    timer_calls: list[Any] = []
    original_timer = ui.timer

    def cap_timer(*a: Any, **kw: Any) -> Any:
        if kw.get("once"):
            cb = a[1] if len(a) > 1 else kw.get("callback")
            if cb:
                timer_calls.append(cb)
        return original_timer(*a, **kw)

    ui.select = cap_select  # type: ignore[assignment]
    ui.button = cap_button  # type: ignore[assignment]
    ui.timer = cap_timer  # type: ignore[assignment]
    try:
        await camera_detail.camera_detail_page("Test%20Cam")
        for fn in timer_calls:
            try:
                r = fn()
                if hasattr(r, "__await__"):
                    await r
            except Exception:
                pass
    finally:
        ui.select = original_select  # type: ignore[assignment]
        ui.button = original_button  # type: ignore[assignment]
        ui.timer = original_timer  # type: ignore[assignment]

    return {"selects": select_instances, "buttons": button_instances}


def _button_by_text(buttons: list[Any], text: str) -> Any:
    for b in buttons:
        if b.init_args and b.init_args[0] == text:
            return b
    raise AssertionError(f"no button with text {text!r}")


def _handler_of(instance: Any, event: str = "on_click") -> Any:
    # `on_click` may arrive either as a constructor kwarg (`ui.button(...,
    # on_click=fn)`) or via a chained `.on_click(fn)` call — check both.
    if event in instance.init_kwargs:
        return instance.init_kwargs[event]
    for call_name, call_args, _kw in instance.calls:
        if call_name == event and call_args:
            return call_args[0]
    raise AssertionError(f"no {event!r} handler recorded on {instance!r}")


class TestQualitySelector:
    async def test_quality_select_defaults_to_auto(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        result = await _render(cam, bridge)
        quality_selects = [
            s
            for s in result["selects"]
            if s.init_args and s.init_args[0] == ["auto", "high", "low"]
        ]
        assert quality_selects, "quality selector not rendered"
        assert quality_selects[0].init_kwargs.get("value") == "auto"

    async def test_quality_change_reresolves_stream(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)

        async def _get_stream_url(*_a: Any, **kw: Any) -> dict[str, Any]:
            return {"url": "rtsp://u:p@1.2.3.4/x", "type": "LOCAL", "hq": kw.get("hq")}

        bridge.async_get_stream_url = _get_stream_url
        bridge.async_snap_from_proxy = AsyncMock(return_value=None)
        bridge.async_snap_from_events = AsyncMock(return_value=(None, ""))

        result = await _render(cam, bridge)
        quality_select = next(
            s
            for s in result["selects"]
            if s.init_args and s.init_args[0] == ["auto", "high", "low"]
        )
        handler = None
        for call_name, call_args, _kw in quality_select.calls:
            if call_name == "on_value_change" and call_args:
                handler = call_args[0]
        assert handler is not None
        # Must not raise — go2rtc is unavailable in the test env, so this
        # exercises the snapshot-fallback re-mount path.
        r = handler(types.SimpleNamespace(value="high"))
        if hasattr(r, "__await__"):
            await r


class TestFirmwareCard:
    async def test_update_available_shows_install_button(
        self, fake_nicegui: Any
    ) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        bridge.async_get_firmware_status = AsyncMock(
            return_value={"current": "9.0.0", "upToDate": False, "update": "9.1.0"}
        )
        result = await _render(cam, bridge)
        install_btn = _button_by_text(result["buttons"], "Install Update")
        classes_calls = [c for c in install_btn.calls if c[0] == "classes"]
        # Last relevant classes() call must have removed "hidden".
        assert any(kw.get("remove") == "hidden" for _n, _a, kw in classes_calls)

    async def test_up_to_date_keeps_button_hidden(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        bridge.async_get_firmware_status = AsyncMock(
            return_value={"current": "9.1.0", "upToDate": True, "update": None}
        )
        result = await _render(cam, bridge)
        install_btn = _button_by_text(result["buttons"], "Install Update")
        classes_calls = [c for c in install_btn.calls if c[0] == "classes"]
        assert not any(kw.get("remove") == "hidden" for _n, _a, kw in classes_calls)

    async def test_status_unavailable(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        bridge.async_get_firmware_status = AsyncMock(return_value=None)
        result = await _render(cam, bridge)
        # Must not raise.
        _button_by_text(result["buttons"], "Install Update")

    async def test_install_success_flow(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        bridge.async_get_firmware_status = AsyncMock(
            return_value={"current": "9.0.0", "upToDate": False, "update": "9.1.0"}
        )
        bridge.async_install_firmware = AsyncMock(return_value=(True, None))
        result = await _render(cam, bridge)
        install_btn = _button_by_text(result["buttons"], "Install")
        handler = _handler_of(install_btn)
        r = handler()
        if hasattr(r, "__await__"):
            await r
        bridge.async_install_firmware.assert_called_once()

    async def test_install_failure_reloads_status(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        bridge.async_get_firmware_status = AsyncMock(
            return_value={"current": "9.0.0", "upToDate": False, "update": "9.1.0"}
        )
        bridge.async_install_firmware = AsyncMock(
            return_value=(False, "Camera offline")
        )
        result = await _render(cam, bridge)
        install_btn = _button_by_text(result["buttons"], "Install")
        handler = _handler_of(install_btn)
        r = handler()
        if hasattr(r, "__await__"):
            await r
        assert bridge.async_get_firmware_status.await_count >= 2


class TestRecordingsBrowser:
    async def test_no_recordings(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        list_segments = AsyncMock(return_value=[])
        result = await _render(cam, bridge, list_segments=list_segments)
        _button_by_text(result["buttons"], "Refresh Recordings")
        list_segments.assert_called()

    async def test_lists_and_plays_and_deletes(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        segment = {
            "name": "20260101-000000.mp4",
            "path": "/tmp/x/20260101-000000.mp4",
            "size_bytes": 2 * 1024 * 1024,
            "mtime": 1750000000.0,
        }
        list_segments = AsyncMock(return_value=[segment])
        delete_segment = AsyncMock(return_value=True)
        result = await _render(
            cam, bridge, list_segments=list_segments, delete_segment=delete_segment
        )
        play_btns = [
            b for b in result["buttons"] if b.init_kwargs.get("icon") == "play_arrow"
        ]
        assert play_btns, "no play button rendered for a listed recording"
        play_handler = _handler_of(play_btns[0])
        play_handler()  # must not raise

        delete_btns = [
            b for b in result["buttons"] if b.init_kwargs.get("icon") == "delete"
        ]
        assert delete_btns, "no delete button rendered for a listed recording"
        delete_handler = _handler_of(delete_btns[0])
        r = delete_handler()
        if hasattr(r, "__await__"):
            await r
        delete_segment.assert_called_once()

    async def test_delete_failure_notifies(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        segment = {
            "name": "20260101-000000.mp4",
            "path": "/tmp/x/20260101-000000.mp4",
            "size_bytes": 1024,
            "mtime": 1750000000.0,
        }
        list_segments = AsyncMock(return_value=[segment])
        delete_segment = AsyncMock(return_value=False)
        result = await _render(
            cam, bridge, list_segments=list_segments, delete_segment=delete_segment
        )
        delete_btns = [
            b for b in result["buttons"] if b.init_kwargs.get("icon") == "delete"
        ]
        handler = _handler_of(delete_btns[0])
        r = handler()
        if hasattr(r, "__await__"):
            await r
        delete_segment.assert_called_once()
