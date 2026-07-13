"""Tests for the "Local Recording (Beta)" continuous-NVR section added to the
camera detail page. Mirrors the fake_nicegui + generic-capture-callback
pattern established in test_camera_detail_parity_batch.py, but drives the
switch/input directly by label (rather than the fully-generic fire-everything
helpers) since this section's success/failure paths need distinct
``get_nvr_manager()`` mocks per test. FAKE DATA ONLY (SECRETS_SCAN).
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
    cam: dict[str, Any], bridge: MagicMock, nvr_mgr: MagicMock
) -> tuple[Any, Any, dict[str, Any]]:
    """Render camera_detail_page with ``get_nvr_manager`` swapped for
    *nvr_mgr* and the NVR switch/input captured by label.

    Returns (nvr_switch_instance, nvr_switch_handler, inputs_by_label).
    """
    from nicegui import app, ui

    cfg = _make_cfg(cam)
    app.storage.general.clear()
    app.storage.general["cfg"] = cfg
    app.storage.general["token"] = "header.payload.signature"

    from bosch_camera_frontend.pages import camera_detail

    camera_detail.cli_bridge = bridge
    camera_detail.get_nvr_manager = lambda: nvr_mgr

    switch_instances: list[Any] = []
    original_switch = ui.switch

    def cap_switch(*a: Any, **kw: Any) -> Any:
        instance = original_switch(*a, **kw)
        switch_instances.append(instance)
        return instance

    inputs_by_label: dict[str, Any] = {}
    original_input = ui.input

    def cap_input(*a: Any, **kw: Any) -> Any:
        instance = original_input(*a, **kw)
        label = a[0] if a else str(kw.get("label", ""))
        inputs_by_label[label] = instance
        return instance

    timer_calls: list[Any] = []
    original_timer = ui.timer

    def cap_timer(*a: Any, **kw: Any) -> Any:
        if kw.get("once"):
            cb = a[1] if len(a) > 1 else kw.get("callback")
            if cb:
                timer_calls.append(cb)
        return original_timer(*a, **kw)

    ui.switch = cap_switch  # type: ignore[assignment]
    ui.input = cap_input  # type: ignore[assignment]
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
        ui.switch = original_switch  # type: ignore[assignment]
        ui.input = original_input  # type: ignore[assignment]
        ui.timer = original_timer  # type: ignore[assignment]

    nvr_inst = next(
        inst
        for inst in switch_instances
        if inst.init_args and inst.init_args[0] == "Continuous Recording"
    )
    handler = None
    for call_name, call_args, _kw in nvr_inst.calls:
        if call_name == "on_value_change" and call_args:
            handler = call_args[0]
    assert handler is not None, "Continuous Recording switch has no handler"
    return nvr_inst, handler, inputs_by_label


async def _consume_load_suppress(handler: Any, current_value: bool) -> None:
    """_load_nvr_state() arms a one-shot suppress guard before its own
    set_value() call (same pattern as the pre-existing "Cloud Recording"
    section's ``_recording_suppress_next`` — see
    test_camera_detail_parity_batch.py::test_recording_switch_reverts_on_write_failure).
    The fake nicegui's set_value() does NOT itself invoke on_value_change
    handlers, so that pending suppress flag is still armed here; consume it
    with one throwaway call before the test's real toggle action, exactly
    mirroring what the real client's first genuine change event would do
    right after a load."""
    consume = handler(types.SimpleNamespace(value=current_value))
    if hasattr(consume, "__await__"):
        await consume


class TestNvrSectionRenders:
    async def test_section_renders_with_default_folder(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        mgr = MagicMock()
        mgr.available = True
        mgr.is_recording.return_value = False

        _inst, _handler, inputs = await _render(cam, bridge, mgr)
        assert "Recording folder" in inputs
        assert inputs["Recording folder"].value == "captures/Test Cam/nvr"

    async def test_section_uses_persisted_folder(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        cam["nvr_recording_folder"] = "custom/path"
        bridge = _base_bridge(cam)
        mgr = MagicMock()
        mgr.available = True
        mgr.is_recording.return_value = False

        _inst, _handler, inputs = await _render(cam, bridge, mgr)
        assert inputs["Recording folder"].value == "custom/path"


class TestNvrLoadState:
    async def test_ffmpeg_unavailable_disables_switch(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        mgr = MagicMock()
        mgr.available = False

        inst, _handler, _inputs = await _render(cam, bridge, mgr)
        assert inst.enabled is False

    async def test_already_recording_reflected_on_load(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        mgr = MagicMock()
        mgr.available = True
        mgr.is_recording.return_value = True

        inst, _handler, _inputs = await _render(cam, bridge, mgr)
        assert inst.value is True


class TestNvrToggle:
    async def test_toggle_on_success(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        mgr = MagicMock()
        mgr.available = True
        mgr.is_recording.return_value = False
        mgr.async_start_recording = AsyncMock(return_value=True)
        mgr.async_stop_recording = AsyncMock()

        _inst, handler, _inputs = await _render(cam, bridge, mgr)
        await _consume_load_suppress(handler, False)  # is_recording() was False
        result = handler(types.SimpleNamespace(value=True))
        if hasattr(result, "__await__"):
            await result

        mgr.async_start_recording.assert_called_once()
        call_args = mgr.async_start_recording.call_args
        assert call_args.args[0]  # stream-name key, non-empty
        assert callable(call_args.args[1])  # resolver
        assert call_args.args[2] == "captures/Test Cam/nvr"
        # Config is persisted (folder + enabled flag) on toggle.
        assert cam["nvr_recording_enabled"] is True
        bridge.save_config.assert_called()

        # The resolver passed to the manager must be SYNC and delegate to
        # cli_bridge.get_stream_url (not the async variant) — the watcher
        # thread that calls it is not the event loop.
        resolver = call_args.args[1]
        info = resolver()
        assert info == {"url": "rtsp://u:p@1.2.3.4/rtsp_tunnel", "type": "LOCAL"}
        bridge.get_stream_url.assert_called()

    async def test_toggle_on_failure_reverts_switch(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        mgr = MagicMock()
        mgr.available = True
        mgr.is_recording.return_value = False
        mgr.async_start_recording = AsyncMock(return_value=False)
        mgr.async_stop_recording = AsyncMock()

        inst, handler, _inputs = await _render(cam, bridge, mgr)
        await _consume_load_suppress(handler, False)  # is_recording() was False
        inst.set_value(True)
        result = handler(types.SimpleNamespace(value=True))
        if hasattr(result, "__await__"):
            await result

        assert inst.value is False, "failed start must revert the switch to OFF"

    async def test_toggle_off_stops_recording(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        mgr = MagicMock()
        mgr.available = True
        mgr.is_recording.return_value = True
        mgr.async_start_recording = AsyncMock(return_value=True)
        mgr.async_stop_recording = AsyncMock()

        _inst, handler, _inputs = await _render(cam, bridge, mgr)
        await _consume_load_suppress(handler, True)  # is_recording() was True
        result = handler(types.SimpleNamespace(value=False))
        if hasattr(result, "__await__"):
            await result

        mgr.async_stop_recording.assert_called_once()
        assert cam["nvr_recording_enabled"] is False

    async def test_custom_folder_input_used_on_toggle(self, fake_nicegui: Any) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        mgr = MagicMock()
        mgr.available = True
        mgr.is_recording.return_value = False
        mgr.async_start_recording = AsyncMock(return_value=True)
        mgr.async_stop_recording = AsyncMock()

        _inst, handler, inputs = await _render(cam, bridge, mgr)
        await _consume_load_suppress(handler, False)  # is_recording() was False
        inputs["Recording folder"].set_value("/data/my-recordings")
        result = handler(types.SimpleNamespace(value=True))
        if hasattr(result, "__await__"):
            await result

        call_args = mgr.async_start_recording.call_args
        assert call_args.args[2] == "/data/my-recordings"
        assert cam["nvr_recording_folder"] == "/data/my-recordings"

    async def test_save_config_exception_does_not_crash_toggle(
        self, fake_nicegui: Any
    ) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        bridge.save_config.side_effect = RuntimeError("disk full")
        mgr = MagicMock()
        mgr.available = True
        mgr.is_recording.return_value = False
        mgr.async_start_recording = AsyncMock(return_value=True)
        mgr.async_stop_recording = AsyncMock()

        _inst, handler, _inputs = await _render(cam, bridge, mgr)
        await _consume_load_suppress(handler, False)  # is_recording() was False
        result = handler(types.SimpleNamespace(value=True))
        if hasattr(result, "__await__"):
            await result  # must not raise despite save_config failing

        mgr.async_start_recording.assert_called_once()


class TestNvrLoadDoesNotRefireToggle:
    """Regression coverage for the missing-suppress-guard bug found by an
    adversarial bug-hunt agent (2026-07-13): _load_nvr_state's programmatic
    nvr_switch.set_value(True) — when a recording is already active for this
    camera (e.g. the user revisits the page, since recording is deliberately
    NOT tied to the page lifecycle) — must NOT re-trigger _toggle_nvr's "on"
    branch (which would spuriously call async_start_recording again and
    persist config on every single page load)."""

    async def test_already_recording_does_not_restart_or_resave(
        self, fake_nicegui: Any
    ) -> None:
        cam = _fake_cam()
        bridge = _base_bridge(cam)
        mgr = MagicMock()
        mgr.available = True
        mgr.is_recording.return_value = True  # already running
        mgr.async_start_recording = AsyncMock(return_value=True)
        mgr.async_stop_recording = AsyncMock()

        await _render(cam, bridge, mgr)

        mgr.async_start_recording.assert_not_called()
        bridge.save_config.assert_not_called()


class TestNvrRealSingletonSafety:
    """Confirms the conftest.py safety-net fixture (_no_real_nvr_ffmpeg_spawns)
    actually protects the REAL NVRManager singleton — not just the MagicMock
    stand-in used by every other test in this file. Regression coverage for
    a bug-hunt finding (2026-07-13): the fixture patched a class object that
    fake_nicegui's sys.modules purge then discarded, because it wasn't
    declared to depend on fake_nicegui and autouse fixtures resolve before
    explicitly-requested ones of the same scope."""

    async def test_toggle_on_with_real_manager_spawns_nothing(
        self, fake_nicegui: Any
    ) -> None:
        from bosch_camera_frontend.adapters.nvr_manager import (
            get_manager as get_real_nvr_manager,
        )

        cam = _fake_cam()
        bridge = _base_bridge(cam)
        real_mgr = get_real_nvr_manager()
        assert real_mgr.available is False, (
            "safety-net fixture must make the REAL NVRManager report "
            "unavailable, even though this devbox has ffmpeg on PATH"
        )

        _inst, handler, _inputs = await _render(cam, bridge, real_mgr)
        result = handler(types.SimpleNamespace(value=True))
        if hasattr(result, "__await__"):
            await result

        # start_recording must have declined (no ffmpeg "available") before
        # ever creating a _CameraRecorder/thread, for any stream-name key.
        with real_mgr._lock:
            assert real_mgr._recorders == {}
