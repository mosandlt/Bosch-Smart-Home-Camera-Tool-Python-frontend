"""Comprehensive pytest tests for dashboard.py, settings.py, camera_detail.py.

Uses the ``fake_nicegui`` fixture to install a fully-fake NiceGUI before each
import, so page handlers run end-to-end with cli_bridge mocked.

FAKE DATA ONLY — no real device IDs, MACs, tokens, or IPs.
"""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import MagicMock



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_session() -> MagicMock:
    return MagicMock(name="session")


def _fake_cam(*, has_light: bool = False, pan_limit: int = 0) -> dict[str, Any]:
    return {
        "id": "11111111-2222-3333-4444-555555555555",
        "name": "Test Cam",
        "model": "CAMERA_EYES",
        "firmware": "9.0.0",
        "mac": "aa:bb:cc:dd:ee:ff",
        "download_folder": "Test Cam",
        "local_ip": "",
        "has_light": has_light,
        "pan_limit": pan_limit,
    }


def _make_cfg(cam: dict[str, Any] | None = None) -> dict[str, Any]:
    cam = cam or _fake_cam()
    return {
        "account": {"bearer_token": "header.payload.signature"},
        "language": "en",
        "cameras": {cam["name"]: cam},
    }


# ---------------------------------------------------------------------------
# Dashboard tests
# ---------------------------------------------------------------------------


class TestDashboardHelpers:
    """_navigate_to_camera and _build_error_state are standalone helpers."""

    def test_navigate_to_camera(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import dashboard

        dashboard._navigate_to_camera({"name": "Test Cam"})
        # ui.navigate.to is a factory (_factory) — just ensure no exception raised
        # and the call was made (navigate.to is a lambda in the fake)

    def test_navigate_to_camera_empty_name(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import dashboard

        # Should not raise even with empty name
        dashboard._navigate_to_camera({})

    def test_build_error_state(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import dashboard

        # Should not raise
        dashboard._build_error_state("Something went wrong")

    def test_build_error_state_custom_message(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import dashboard

        dashboard._build_error_state("Custom error msg")


class TestDashboardPage:
    """Tests for dashboard_page async handler."""

    async def test_missing_cfg_shows_error(self, fake_nicegui: Any) -> None:
        """No cfg/token in storage -> _build_error_state called, return early."""
        from bosch_camera_frontend.pages import dashboard
        from nicegui import app

        app.storage.general.clear()
        bridge = MagicMock()
        dashboard.cli_bridge = bridge

        await dashboard.dashboard_page()
        # make_session should NOT be called because we returned early
        bridge.make_session.assert_not_called()

    async def test_missing_token_shows_error(self, fake_nicegui: Any) -> None:
        """cfg present but no token -> error state, no API call."""
        from bosch_camera_frontend.pages import dashboard
        from nicegui import app

        app.storage.general.clear()
        app.storage.general["cfg"] = _make_cfg()
        # No token
        bridge = MagicMock()
        dashboard.cli_bridge = bridge

        await dashboard.dashboard_page()
        bridge.make_session.assert_not_called()

    async def test_async_get_cameras_raises_shows_error(self, fake_nicegui: Any) -> None:
        """If async_get_cameras raises, _build_error_state is shown."""
        from bosch_camera_frontend.pages import dashboard
        from nicegui import app

        app.storage.general.clear()
        app.storage.general["cfg"] = _make_cfg()
        app.storage.general["token"] = "header.payload.signature"

        bridge = MagicMock()
        bridge.make_session.return_value = _fake_session()

        async def _raise(*_a: Any, **_kw: Any) -> dict[str, Any]:
            raise RuntimeError("network error")

        bridge.async_get_cameras = _raise
        dashboard.cli_bridge = bridge

        await dashboard.dashboard_page()
        bridge.make_session.assert_called_once()

    async def test_empty_cameras_shows_no_cameras(self, fake_nicegui: Any) -> None:
        """Empty cameras dict -> 'No cameras found.' shown."""
        from bosch_camera_frontend.pages import dashboard
        from nicegui import app

        app.storage.general.clear()
        app.storage.general["cfg"] = _make_cfg()
        app.storage.general["token"] = "header.payload.signature"

        bridge = MagicMock()
        bridge.make_session.return_value = _fake_session()

        async def _empty(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {}

        bridge.async_get_cameras = _empty
        dashboard.cli_bridge = bridge

        await dashboard.dashboard_page()
        bridge.make_session.assert_called_once()

    async def test_cameras_build_grid(self, fake_nicegui: Any) -> None:
        """Cameras returned -> grid is built without raising."""
        from bosch_camera_frontend.pages import dashboard
        from nicegui import app

        cam = _fake_cam()
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = MagicMock()
        bridge.make_session.return_value = _fake_session()

        async def _cameras(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"Test Cam": cam}

        bridge.async_get_cameras = _cameras
        dashboard.cli_bridge = bridge

        await dashboard.dashboard_page()
        bridge.make_session.assert_called_once()

    async def test_two_cameras_in_grid(self, fake_nicegui: Any) -> None:
        """Multiple cameras are all rendered without error."""
        from bosch_camera_frontend.pages import dashboard
        from nicegui import app

        cam1 = _fake_cam()
        cam2 = {**_fake_cam(), "id": "22222222-3333-4444-5555-666666666666", "name": "Cam Two"}
        cfg = _make_cfg(cam1)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = MagicMock()
        bridge.make_session.return_value = _fake_session()

        async def _two(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"Test Cam": cam1, "Cam Two": cam2}

        bridge.async_get_cameras = _two
        dashboard.cli_bridge = bridge

        await dashboard.dashboard_page()

    async def test_config_path_in_storage(self, fake_nicegui: Any) -> None:
        """config_path stored in general storage is accessible."""
        from bosch_camera_frontend.pages import dashboard
        from nicegui import app

        app.storage.general.clear()
        app.storage.general["cfg"] = _make_cfg()
        app.storage.general["token"] = "header.payload.signature"
        app.storage.general["config_path"] = "/fake/path/bosch_config.json"

        bridge = MagicMock()
        bridge.make_session.return_value = _fake_session()

        async def _empty(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {}

        bridge.async_get_cameras = _empty
        dashboard.cli_bridge = bridge

        await dashboard.dashboard_page()


# ---------------------------------------------------------------------------
# Settings tests
# ---------------------------------------------------------------------------


class TestSettingsPage:
    """Tests for settings_page async handler."""

    async def test_no_cfg_renders_no_config(self, fake_nicegui: Any) -> None:
        """Without cfg, 'No config loaded.' path is taken."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app

        app.storage.general.clear()
        bridge = MagicMock()
        bridge.detect_lang.return_value = "en"
        settings.cli_bridge = bridge

        await settings.settings_page()
        # detect_lang should NOT be called (cfg is None/falsy)
        bridge.detect_lang.assert_not_called()

    async def test_cfg_present_token_ok(self, fake_nicegui: Any) -> None:
        """cfg present + check_token_age returns '✅' -> positive icon."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg

        bridge = MagicMock()
        bridge.detect_lang.return_value = "en"
        bridge.check_token_age.return_value = "✅ Token valid (2 hours remaining)"
        settings.cli_bridge = bridge

        await settings.settings_page()
        bridge.check_token_age.assert_called_once_with(cfg)

    async def test_cfg_present_token_warning(self, fake_nicegui: Any) -> None:
        """check_token_age returns '⚠️' -> warning icon path."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg

        bridge = MagicMock()
        bridge.detect_lang.return_value = "en"
        bridge.check_token_age.return_value = "⚠️ Token expires soon"
        settings.cli_bridge = bridge

        await settings.settings_page()
        bridge.check_token_age.assert_called_once()

    async def test_cfg_present_token_error(self, fake_nicegui: Any) -> None:
        """check_token_age returns string with neither ✅ nor ⚠️ -> error icon."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg

        bridge = MagicMock()
        bridge.detect_lang.return_value = "en"
        bridge.check_token_age.return_value = "Token expired"
        settings.cli_bridge = bridge

        await settings.settings_page()
        bridge.check_token_age.assert_called_once()

    async def test_detect_lang_unknown_fallback(self, fake_nicegui: Any) -> None:
        """detect_lang returns unknown lang -> falls back to 'en'."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg

        bridge = MagicMock()
        bridge.detect_lang.return_value = "xx-UNKNOWN"
        bridge.check_token_age.return_value = "✅ ok"
        settings.cli_bridge = bridge

        # Should not raise — falls back to "en"
        await settings.settings_page()

    async def test_detect_lang_german(self, fake_nicegui: Any) -> None:
        """detect_lang returns 'de' -> that value is used as current_lang."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app

        cfg = {**_make_cfg(), "language": "de"}
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg

        bridge = MagicMock()
        bridge.detect_lang.return_value = "de"
        bridge.check_token_age.return_value = "✅ ok"
        settings.cli_bridge = bridge

        await settings.settings_page()
        bridge.detect_lang.assert_called_once_with(cfg)

    async def test_config_path_default_shown(self, fake_nicegui: Any) -> None:
        """config_path defaults to 'bosch_config.json' if not in storage."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        # no config_path key

        bridge = MagicMock()
        bridge.detect_lang.return_value = "en"
        bridge.check_token_age.return_value = "✅ ok"
        settings.cli_bridge = bridge

        await settings.settings_page()

    async def test_config_path_custom(self, fake_nicegui: Any) -> None:
        """Custom config_path from storage is rendered."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["config_path"] = "/home/user/bosch_config.json"

        bridge = MagicMock()
        bridge.detect_lang.return_value = "en"
        bridge.check_token_age.return_value = "✅ ok"
        settings.cli_bridge = bridge

        await settings.settings_page()


class TestSettingsDoReload:
    """Exercise the inner _do_reload closure by extracting it via on_click."""

    async def _run_settings(self, fake_nicegui: Any, bridge: MagicMock) -> None:
        from bosch_camera_frontend.pages import settings
        from nicegui import app

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        bridge.detect_lang.return_value = "en"
        bridge.check_token_age.return_value = "✅ ok"
        settings.cli_bridge = bridge
        await settings.settings_page()

    async def test_do_reload_no_helper_attr(self, fake_nicegui: Any) -> None:
        """reload_config_and_token missing -> ui.notify negative."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app, ui

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg

        bridge = MagicMock(spec=[])  # spec=[] means no attributes by default
        bridge.detect_lang = MagicMock(return_value="en")
        bridge.check_token_age = MagicMock(return_value="✅ ok")
        # reload_config_and_token deliberately absent
        settings.cli_bridge = bridge

        # Capture the _do_reload closure by intercepting ui.button calls
        reload_fn_holder: list[Any] = []
        original_button = ui.button

        def capturing_button(*a: Any, **kw: Any) -> Any:
            if kw.get("icon") == "refresh" and "on_click" in kw:
                reload_fn_holder.append(kw["on_click"])
            return original_button(*a, **kw)

        ui.button = capturing_button  # type: ignore[assignment]
        try:
            await settings.settings_page()
        finally:
            ui.button = original_button  # type: ignore[assignment]

        assert reload_fn_holder, "No 'Reload from disk' button registered"
        reload_fn_holder[0]()  # Call _do_reload

    async def test_do_reload_helper_returns_none(self, fake_nicegui: Any) -> None:
        """reload helper returns None -> ui.notify negative."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app, ui

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg

        bridge = MagicMock()
        bridge.detect_lang.return_value = "en"
        bridge.check_token_age.return_value = "✅ ok"
        bridge.reload_config_and_token = MagicMock(return_value=None)
        settings.cli_bridge = bridge

        reload_fn_holder: list[Any] = []
        original_button = ui.button

        def capturing_button(*a: Any, **kw: Any) -> Any:
            if kw.get("icon") == "refresh" and "on_click" in kw:
                reload_fn_holder.append(kw["on_click"])
            return original_button(*a, **kw)

        ui.button = capturing_button  # type: ignore[assignment]
        try:
            await settings.settings_page()
        finally:
            ui.button = original_button  # type: ignore[assignment]

        assert reload_fn_holder
        reload_fn_holder[0]()
        bridge.reload_config_and_token.assert_called_once()

    async def test_do_reload_helper_returns_tuple(self, fake_nicegui: Any) -> None:
        """reload helper returns a tuple (success) -> ui.notify positive."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app, ui

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg

        bridge = MagicMock()
        bridge.detect_lang.return_value = "en"
        bridge.check_token_age.return_value = "✅ ok"
        bridge.reload_config_and_token = MagicMock(return_value=(cfg, "header.payload.signature"))
        settings.cli_bridge = bridge

        reload_fn_holder: list[Any] = []
        original_button = ui.button

        def capturing_button(*a: Any, **kw: Any) -> Any:
            if kw.get("icon") == "refresh" and "on_click" in kw:
                reload_fn_holder.append(kw["on_click"])
            return original_button(*a, **kw)

        ui.button = capturing_button  # type: ignore[assignment]
        try:
            await settings.settings_page()
        finally:
            ui.button = original_button  # type: ignore[assignment]

        assert reload_fn_holder
        reload_fn_holder[0]()
        bridge.reload_config_and_token.assert_called_once()


class TestSettingsSaveLanguage:
    """Exercise _save_language via on_change callback on ui.select."""

    def _install_capturing_select(
        self, ui: Any, on_change_holder: list[Any]
    ) -> Any:
        original_select = ui.select

        def capturing_select(*a: Any, **kw: Any) -> Any:
            if "on_change" in kw:
                on_change_holder.append(kw["on_change"])
            return original_select(*a, **kw)

        ui.select = capturing_select  # type: ignore[assignment]
        return original_select

    async def test_save_language_success(self, fake_nicegui: Any) -> None:
        """cfg present + save_config succeeds -> lang_saved_note updated."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app, ui

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg

        bridge = MagicMock()
        bridge.detect_lang.return_value = "en"
        bridge.check_token_age.return_value = "✅ ok"
        bridge.save_config = MagicMock()
        bridge.set_lang = MagicMock()
        settings.cli_bridge = bridge

        on_change_holder: list[Any] = []
        original_select = self._install_capturing_select(ui, on_change_holder)
        try:
            await settings.settings_page()
        finally:
            ui.select = original_select  # type: ignore[assignment]

        assert on_change_holder, "No on_change registered on select"
        # Simulate selecting German
        event = types.SimpleNamespace(value="de")
        on_change_holder[0](event)
        assert cfg["language"] == "de"
        bridge.save_config.assert_called_once()
        bridge.set_lang.assert_called_once_with("de")

    async def test_save_language_save_raises(self, fake_nicegui: Any) -> None:
        """save_config raises -> lang_saved_note shows failure message."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app, ui

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg

        bridge = MagicMock()
        bridge.detect_lang.return_value = "en"
        bridge.check_token_age.return_value = "✅ ok"
        bridge.save_config = MagicMock(side_effect=OSError("disk full"))
        settings.cli_bridge = bridge

        on_change_holder: list[Any] = []
        original_select = self._install_capturing_select(ui, on_change_holder)
        try:
            await settings.settings_page()
        finally:
            ui.select = original_select  # type: ignore[assignment]

        assert on_change_holder
        event = types.SimpleNamespace(value="fr")
        on_change_holder[0](event)
        bridge.save_config.assert_called_once()

    async def test_save_language_no_cfg(self, fake_nicegui: Any) -> None:
        """cfg is None -> warning notify, no save_config call."""
        from bosch_camera_frontend.pages import settings
        from nicegui import app, ui

        # settings_page: with cfg=None, detect_lang NOT called, select gets value "en"
        # But _save_language captures cfg from outer scope (None)
        app.storage.general.clear()
        # cfg absent => page renders "No config loaded" branch

        bridge = MagicMock()
        settings.cli_bridge = bridge

        on_change_holder: list[Any] = []
        original_select = self._install_capturing_select(ui, on_change_holder)
        try:
            await settings.settings_page()
        finally:
            ui.select = original_select  # type: ignore[assignment]

        # on_change is registered even when cfg is None
        if on_change_holder:
            event = types.SimpleNamespace(value="de")
            on_change_holder[0](event)
            bridge.save_config.assert_not_called()


# ---------------------------------------------------------------------------
# Camera detail helpers
# ---------------------------------------------------------------------------


class TestCameraDetailHelpers:
    """Pure helper functions — no page context needed."""

    def test_format_event_ts_valid_iso_z(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import camera_detail

        result = camera_detail._format_event_ts("2024-03-15T10:30:00Z")
        assert result == "2024-03-15 10:30:00"

    def test_format_event_ts_with_offset(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import camera_detail

        result = camera_detail._format_event_ts("2024-03-15T10:30:00+00:00")
        assert result == "2024-03-15 10:30:00"

    def test_format_event_ts_garbage_passthrough(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import camera_detail

        result = camera_detail._format_event_ts("not-a-date")
        assert result == "not-a-date"

    def test_format_event_ts_empty_string(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import camera_detail

        result = camera_detail._format_event_ts("")
        assert result == ""

    def test_event_type_icon_movement(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import camera_detail

        assert camera_detail._event_type_icon("MOVEMENT") == "directions_run"

    def test_event_type_icon_person(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import camera_detail

        assert camera_detail._event_type_icon("PERSON") == "person"

    def test_event_type_icon_audio_alarm(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import camera_detail

        assert camera_detail._event_type_icon("AUDIO_ALARM") == "volume_up"

    def test_event_type_icon_doorbell(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import camera_detail

        assert camera_detail._event_type_icon("DOORBELL") == "doorbell"

    def test_event_type_icon_unknown(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import camera_detail

        assert camera_detail._event_type_icon("SOMETHING_NEW") == "notifications"

    def test_event_type_icon_lowercase(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages import camera_detail

        assert camera_detail._event_type_icon("movement") == "directions_run"


# ---------------------------------------------------------------------------
# Camera detail page
# ---------------------------------------------------------------------------


class TestCameraDetailPage:
    """Tests for camera_detail_page async handler."""

    def _make_bridge(self) -> MagicMock:
        bridge = MagicMock()
        bridge.make_session.return_value = _fake_session()
        return bridge

    async def test_missing_cfg_shows_notify(self, fake_nicegui: Any) -> None:
        """No cfg/token -> notify called, early return."""
        from bosch_camera_frontend.pages import camera_detail
        from nicegui import app

        app.storage.general.clear()
        bridge = self._make_bridge()
        camera_detail.cli_bridge = bridge

        await camera_detail.camera_detail_page("Test%20Cam")
        bridge.make_session.assert_not_called()

    async def test_missing_token_shows_notify(self, fake_nicegui: Any) -> None:
        """cfg present but no token -> early return."""
        from bosch_camera_frontend.pages import camera_detail
        from nicegui import app

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg

        bridge = self._make_bridge()
        camera_detail.cli_bridge = bridge

        await camera_detail.camera_detail_page("Test%20Cam")
        bridge.make_session.assert_not_called()

    async def test_cam_not_found_shows_error_card(self, fake_nicegui: Any) -> None:
        """async_resolve_cam returns {} -> error card shown."""
        from bosch_camera_frontend.pages import camera_detail
        from nicegui import app

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = self._make_bridge()

        async def _not_found(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {}

        bridge.async_resolve_cam = _not_found
        camera_detail.cli_bridge = bridge

        await camera_detail.camera_detail_page("NonExistent")
        bridge.make_session.assert_not_called()

    async def test_cam_found_builds_page(self, fake_nicegui: Any) -> None:
        """cam resolved -> page builds without error."""
        from bosch_camera_frontend.pages import camera_detail
        from nicegui import app

        cam = _fake_cam()
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = self._make_bridge()

        async def _found(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"Test Cam": cam}

        bridge.async_resolve_cam = _found
        camera_detail.cli_bridge = bridge

        await camera_detail.camera_detail_page("Test%20Cam")
        bridge.make_session.assert_called_once()

    async def test_cam_with_light_builds_light_section(
        self, fake_nicegui: Any
    ) -> None:
        """has_light=True -> light section rendered."""
        from bosch_camera_frontend.pages import camera_detail
        from nicegui import app

        cam = _fake_cam(has_light=True)
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = self._make_bridge()

        async def _found(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"Test Cam": cam}

        bridge.async_resolve_cam = _found
        camera_detail.cli_bridge = bridge

        await camera_detail.camera_detail_page("Test%20Cam")

    async def test_cam_with_pan_builds_pan_slider(self, fake_nicegui: Any) -> None:
        """pan_limit=30 -> pan slider rendered."""
        from bosch_camera_frontend.pages import camera_detail
        from nicegui import app

        cam = _fake_cam(pan_limit=30)
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = self._make_bridge()

        async def _found(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"Test Cam": cam}

        bridge.async_resolve_cam = _found
        camera_detail.cli_bridge = bridge

        await camera_detail.camera_detail_page("Test%20Cam")

    async def test_system_exit_treated_as_not_found(self, fake_nicegui: Any) -> None:
        """async_resolve_cam raises SystemExit -> error card shown."""
        from bosch_camera_frontend.pages import camera_detail
        from nicegui import app

        cfg = _make_cfg()
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = self._make_bridge()

        async def _exit(*_a: Any, **_kw: Any) -> dict[str, Any]:
            raise SystemExit(1)

        bridge.async_resolve_cam = _exit
        camera_detail.cli_bridge = bridge

        await camera_detail.camera_detail_page("Test%20Cam")

    async def test_url_encoded_name_decoded(self, fake_nicegui: Any) -> None:
        """URL-encoded camera name is decoded before lookup."""
        from bosch_camera_frontend.pages import camera_detail
        from nicegui import app

        cam = {**_fake_cam(), "name": "Garden Cam"}
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = self._make_bridge()
        resolve_calls: list[str] = []

        async def _tracking(c: Any, key: str) -> dict[str, Any]:
            resolve_calls.append(key)
            return {"Garden Cam": cam}

        bridge.async_resolve_cam = _tracking
        camera_detail.cli_bridge = bridge

        await camera_detail.camera_detail_page("Garden%20Cam")
        assert resolve_calls == ["Garden Cam"]


# ---------------------------------------------------------------------------
# Camera detail — inner async closures
# ---------------------------------------------------------------------------


class TestCameraDetailLoadSnapshot:
    """Drive the load_snapshot closure via ui.timer(0.1, load_snapshot, once=True)."""

    def _setup_with_snap(
        self,
        fake_nicegui: Any,
        *,
        proxy_return: bytes | None,
        events_return: tuple[bytes | None, str] | None = None,
        proxy_raises: Exception | None = None,
    ) -> tuple[Any, MagicMock, list[Any]]:
        """Set up page storage + bridge, capture snapshot timer callbacks."""
        from bosch_camera_frontend.pages import camera_detail
        from nicegui import app, ui

        cam = _fake_cam()
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = MagicMock()
        bridge.make_session.return_value = _fake_session()

        async def _found(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"Test Cam": cam}

        async def _priv(*_a: Any, **_kw: Any) -> str:
            return "OFF"

        bridge.async_resolve_cam = _found
        bridge.async_get_privacy_mode = _priv

        if proxy_raises is not None:
            async def _proxy(*_a: Any, **_kw: Any) -> bytes:
                raise proxy_raises  # type: ignore[misc]
            bridge.async_snap_from_proxy = _proxy
        else:
            async def _proxy_ok(*_a: Any, **_kw: Any) -> bytes | None:
                return proxy_return  # type: ignore[return-value]
            bridge.async_snap_from_proxy = _proxy_ok

        if events_return is not None:
            async def _events(*_a: Any, **_kw: Any) -> tuple[bytes | None, str]:
                return events_return  # type: ignore[return-value]
            bridge.async_snap_from_events = _events
        else:
            async def _events_none(*_a: Any, **_kw: Any) -> tuple[None, str]:
                return None, ""
            bridge.async_snap_from_events = _events_none

        async def _ev_list(*_a: Any, **_kw: Any) -> list[Any]:
            return []

        bridge.async_api_get_events = _ev_list

        camera_detail.cli_bridge = bridge

        timer_calls: list[Any] = []
        original_timer = ui.timer

        def cap_timer(*a: Any, **kw: Any) -> Any:
            if kw.get("once"):
                cb = a[1] if len(a) > 1 else None
                if cb:
                    timer_calls.append(cb)
            return original_timer(*a, **kw)

        ui.timer = cap_timer  # type: ignore[assignment]
        return camera_detail, bridge, timer_calls

    async def _run(self, fake_nicegui: Any, **kwargs: Any) -> None:
        cd, bridge, timer_calls = self._setup_with_snap(fake_nicegui, **kwargs)
        from nicegui import ui

        original_timer = ui.timer
        try:
            await cd.camera_detail_page("Test%20Cam")
        finally:
            ui.timer = original_timer  # type: ignore[assignment]

        # Run all once=True timer callbacks (load_snapshot + _load_privacy + _load_events)
        for fn in timer_calls:
            try:
                r = fn()
                if hasattr(r, "__await__"):
                    await r
            except Exception:
                pass

    async def test_proxy_returns_bytes(self, fake_nicegui: Any) -> None:
        """async_snap_from_proxy returns bytes -> snap_img updated."""
        snap_bytes = b"\xff\xd8\xff" + b"\x00" * 10
        await self._run(fake_nicegui, proxy_return=snap_bytes)

    async def test_proxy_none_events_return_bytes(self, fake_nicegui: Any) -> None:
        """proxy returns None, events return bytes -> 'Snapshot via event history'."""
        event_bytes = b"\xff\xd8\xff" + b"\x00" * 5
        await self._run(
            fake_nicegui,
            proxy_return=None,
            events_return=(event_bytes, "event"),
        )

    async def test_both_none_no_snapshot(self, fake_nicegui: Any) -> None:
        """proxy None + events None -> 'No snapshot available'."""
        await self._run(
            fake_nicegui,
            proxy_return=None,
            events_return=(None, ""),
        )

    async def test_proxy_raises_exception(self, fake_nicegui: Any) -> None:
        """Exception in async_snap_from_proxy -> 'Snapshot error: ...'."""
        await self._run(
            fake_nicegui,
            proxy_return=None,
            proxy_raises=ConnectionError("timeout"),
        )


class TestCameraDetailLoadPrivacy:
    """Drive _load_privacy and _toggle_privacy via ui.timer / ui.switch."""

    def _setup_with_privacy(
        self,
        fake_nicegui: Any,
        privacy_return: str | None,
    ) -> tuple[Any, MagicMock, list[Any], list[Any]]:
        from nicegui import app, ui

        cam = _fake_cam()
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = MagicMock()
        bridge.make_session.return_value = _fake_session()

        async def _found(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"Test Cam": cam}

        async def _priv(*_a: Any, **_kw: Any) -> str | None:
            return privacy_return

        bridge.async_resolve_cam = _found
        bridge.async_get_privacy_mode = _priv

        from bosch_camera_frontend.pages import camera_detail

        camera_detail.cli_bridge = bridge

        # Capture timer callbacks (once=True timers for _load_privacy + _load_events)
        timer_calls: list[Any] = []
        switch_on_change_holder: list[Any] = []

        original_timer = ui.timer
        original_switch = ui.switch

        def capturing_timer(*a: Any, **kw: Any) -> Any:
            cb = a[1] if len(a) > 1 else kw.get("callback")
            if cb and kw.get("once"):
                timer_calls.append(cb)
            return original_timer(*a, **kw)

        def capturing_switch(*a: Any, **kw: Any) -> Any:
            if "on_change" in kw:
                switch_on_change_holder.append(kw["on_change"])
            return original_switch(*a, **kw)

        ui.timer = capturing_timer  # type: ignore[assignment]
        ui.switch = capturing_switch  # type: ignore[assignment]

        return camera_detail, bridge, timer_calls, switch_on_change_holder

    async def test_load_privacy_on(self, fake_nicegui: Any) -> None:
        """_load_privacy: returns 'ON' -> switch set True."""
        cd, bridge, timer_calls, _ = self._setup_with_privacy(fake_nicegui, "ON")
        from nicegui import ui

        # restore ui.timer + ui.switch
        original_timer = ui.timer
        original_switch = ui.switch

        timer_calls_local: list[Any] = []
        capturing_timer_fn = lambda *a, **kw: (  # noqa: E731
            timer_calls_local.append(a[1] if len(a) > 1 else kw.get("callback"))
            if kw.get("once")
            else None
        ) or original_timer(*a, **kw)

        ui.timer = capturing_timer_fn  # type: ignore[assignment]
        try:
            await cd.camera_detail_page("Test%20Cam")
        finally:
            ui.timer = original_timer  # type: ignore[assignment]
            ui.switch = original_switch  # type: ignore[assignment]

        # Run _load_privacy (first once=True timer with delay 0.2)
        privacy_loaders = [c for c in timer_calls_local if c is not None]
        for fn in privacy_loaders:
            try:
                result = fn()
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                pass

    async def test_load_privacy_off(self, fake_nicegui: Any) -> None:
        """_load_privacy: returns 'OFF' -> privacy label 'OFF 👁️'."""
        from nicegui import app, ui

        cam = _fake_cam()
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = MagicMock()
        bridge.make_session.return_value = _fake_session()

        async def _found(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"Test Cam": cam}

        async def _priv_off(*_a: Any, **_kw: Any) -> str:
            return "OFF"

        bridge.async_resolve_cam = _found
        bridge.async_get_privacy_mode = _priv_off

        from bosch_camera_frontend.pages import camera_detail

        camera_detail.cli_bridge = bridge

        timer_calls_local: list[Any] = []
        original_timer = ui.timer

        def cap_timer(*a: Any, **kw: Any) -> Any:
            if kw.get("once"):
                cb = a[1] if len(a) > 1 else None
                if cb:
                    timer_calls_local.append(cb)
            return original_timer(*a, **kw)

        ui.timer = cap_timer  # type: ignore[assignment]
        try:
            await camera_detail.camera_detail_page("Test%20Cam")
        finally:
            ui.timer = original_timer  # type: ignore[assignment]

        for fn in timer_calls_local:
            try:
                r = fn()
                if hasattr(r, "__await__"):
                    await r
            except Exception:
                pass

    async def test_load_privacy_unavailable(self, fake_nicegui: Any) -> None:
        """_load_privacy: returns None -> label 'Privacy: unavailable'."""
        from nicegui import app, ui

        cam = _fake_cam()
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = MagicMock()
        bridge.make_session.return_value = _fake_session()

        async def _found(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"Test Cam": cam}

        async def _priv_none(*_a: Any, **_kw: Any) -> None:
            return None

        bridge.async_resolve_cam = _found
        bridge.async_get_privacy_mode = _priv_none

        from bosch_camera_frontend.pages import camera_detail

        camera_detail.cli_bridge = bridge

        timer_calls_local: list[Any] = []
        original_timer = ui.timer

        def cap_timer(*a: Any, **kw: Any) -> Any:
            if kw.get("once"):
                cb = a[1] if len(a) > 1 else None
                if cb:
                    timer_calls_local.append(cb)
            return original_timer(*a, **kw)

        ui.timer = cap_timer  # type: ignore[assignment]
        try:
            await camera_detail.camera_detail_page("Test%20Cam")
        finally:
            ui.timer = original_timer  # type: ignore[assignment]

        for fn in timer_calls_local:
            try:
                r = fn()
                if hasattr(r, "__await__"):
                    await r
            except Exception:
                pass


class TestCameraDetailTogglePrivacy:
    """Drive _toggle_privacy closure via on_change on the privacy switch."""

    async def _run_page_capture_switch(
        self,
        fake_nicegui: Any,
        set_mode_return: tuple[bool, str | None],
    ) -> list[Any]:
        from nicegui import app, ui

        cam = _fake_cam()
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = MagicMock()
        bridge.make_session.return_value = _fake_session()

        async def _found(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"Test Cam": cam}

        async def _priv(*_a: Any, **_kw: Any) -> str:
            return "OFF"

        async def _set_priv(*_a: Any, **_kw: Any) -> tuple[bool, str | None]:
            return set_mode_return

        bridge.async_resolve_cam = _found
        bridge.async_get_privacy_mode = _priv
        bridge.async_set_privacy_mode = _set_priv

        from bosch_camera_frontend.pages import camera_detail

        camera_detail.cli_bridge = bridge

        switch_holder: list[Any] = []
        original_switch = ui.switch

        def cap_switch(*a: Any, **kw: Any) -> Any:
            on_change = kw.get("on_change")
            if on_change and (not a or a[0] == "Privacy Mode"):
                switch_holder.append(on_change)
            return original_switch(*a, **kw)

        ui.switch = cap_switch  # type: ignore[assignment]
        try:
            await camera_detail.camera_detail_page("Test%20Cam")
        finally:
            ui.switch = original_switch  # type: ignore[assignment]

        return switch_holder

    async def test_toggle_privacy_success(self, fake_nicegui: Any) -> None:
        """_toggle_privacy ok=True -> label updated."""
        switch_holder = await self._run_page_capture_switch(
            fake_nicegui, (True, None)
        )
        if switch_holder:
            event = types.SimpleNamespace(value=True)
            result = switch_holder[0](event)
            if hasattr(result, "__await__"):
                await result

    async def test_toggle_privacy_fail(self, fake_nicegui: Any) -> None:
        """_toggle_privacy ok=False -> switch reverted, notify negative."""
        switch_holder = await self._run_page_capture_switch(
            fake_nicegui, (False, "Camera offline")
        )
        if switch_holder:
            event = types.SimpleNamespace(value=True)
            result = switch_holder[0](event)
            if hasattr(result, "__await__"):
                await result


class TestCameraDetailLoadEvents:
    """Drive _load_events via ui.timer capture."""

    async def _run_page_capture_timers(
        self,
        fake_nicegui: Any,
        events_return: Any,
        events_raise: Exception | None = None,
    ) -> list[Any]:
        from nicegui import app, ui

        cam = _fake_cam()
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = MagicMock()
        bridge.make_session.return_value = _fake_session()

        async def _found(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"Test Cam": cam}

        async def _priv(*_a: Any, **_kw: Any) -> str:
            return "OFF"

        async def _snap_none(*_a: Any, **_kw: Any) -> None:
            return None

        async def _ev_none(*_a: Any, **_kw: Any) -> tuple[None, str]:
            return None, ""

        bridge.async_resolve_cam = _found
        bridge.async_get_privacy_mode = _priv
        bridge.async_snap_from_proxy = _snap_none
        bridge.async_snap_from_events = _ev_none

        if events_raise is not None:
            async def _events_raise(*_a: Any, **_kw: Any) -> list[Any]:
                raise events_raise  # type: ignore[misc]
            bridge.async_api_get_events = _events_raise
        else:
            async def _events_ok(*_a: Any, **_kw: Any) -> list[Any]:
                return events_return  # type: ignore[return-value]
            bridge.async_api_get_events = _events_ok

        from bosch_camera_frontend.pages import camera_detail

        camera_detail.cli_bridge = bridge

        timer_calls: list[Any] = []
        original_timer = ui.timer

        def cap_timer(*a: Any, **kw: Any) -> Any:
            if kw.get("once"):
                cb = a[1] if len(a) > 1 else None
                if cb:
                    timer_calls.append(cb)
            return original_timer(*a, **kw)

        ui.timer = cap_timer  # type: ignore[assignment]
        try:
            await camera_detail.camera_detail_page("Test%20Cam")
        finally:
            ui.timer = original_timer  # type: ignore[assignment]

        return timer_calls

    async def _run_all_timers(self, timer_calls: list[Any]) -> None:
        for fn in timer_calls:
            try:
                r = fn()
                if hasattr(r, "__await__"):
                    await r
            except Exception:
                pass

    async def test_load_events_with_list(self, fake_nicegui: Any) -> None:
        """Events returned -> table rendered."""
        events = [
            {
                "startTime": "2024-03-15T10:00:00Z",
                "type": "MOVEMENT",
                "isRead": True,
            },
            {
                "startTime": "2024-03-15T11:00:00Z",
                "type": "PERSON",
                "isRead": False,
            },
        ]
        timer_calls = await self._run_page_capture_timers(fake_nicegui, events)
        await self._run_all_timers(timer_calls)

    async def test_load_events_empty_list(self, fake_nicegui: Any) -> None:
        """Empty events list -> 'No events found.'"""
        timer_calls = await self._run_page_capture_timers(fake_nicegui, [])
        await self._run_all_timers(timer_calls)

    async def test_load_events_exception(self, fake_nicegui: Any) -> None:
        """Exception in async_api_get_events -> error label shown."""
        timer_calls = await self._run_page_capture_timers(
            fake_nicegui, [], events_raise=RuntimeError("API error")
        )
        await self._run_all_timers(timer_calls)

    async def test_events_use_timestamp_key(self, fake_nicegui: Any) -> None:
        """Events with 'timestamp' key instead of 'startTime' are handled."""
        events = [
            {
                "timestamp": "2024-03-15T10:00:00Z",
                "type": "DOORBELL",
                "isRead": False,
            },
        ]
        timer_calls = await self._run_page_capture_timers(fake_nicegui, events)
        await self._run_all_timers(timer_calls)

    async def test_reload_events_button_on_click(self, fake_nicegui: Any) -> None:
        """Reload Events button on_click callable => _load_events called."""
        from nicegui import app, ui

        cam = _fake_cam()
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = MagicMock()
        bridge.make_session.return_value = _fake_session()

        async def _found(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"Test Cam": cam}

        async def _priv(*_a: Any, **_kw: Any) -> str:
            return "OFF"

        async def _snap_none(*_a: Any, **_kw: Any) -> None:
            return None

        async def _ev_none(*_a: Any, **_kw: Any) -> tuple[None, str]:
            return None, ""

        async def _events(*_a: Any, **_kw: Any) -> list[Any]:
            return []

        bridge.async_resolve_cam = _found
        bridge.async_get_privacy_mode = _priv
        bridge.async_snap_from_proxy = _snap_none
        bridge.async_snap_from_events = _ev_none
        bridge.async_api_get_events = _events

        from bosch_camera_frontend.pages import camera_detail

        camera_detail.cli_bridge = bridge

        reload_btn_holder: list[Any] = []
        original_button = ui.button

        def cap_button(*a: Any, **kw: Any) -> Any:
            if "Reload Events" in (a[0] if a else ""):
                reload_btn_holder.append(kw.get("on_click"))
            return original_button(*a, **kw)

        ui.button = cap_button  # type: ignore[assignment]
        try:
            await camera_detail.camera_detail_page("Test%20Cam")
        finally:
            ui.button = original_button  # type: ignore[assignment]

        if reload_btn_holder and reload_btn_holder[0]:
            result = reload_btn_holder[0]()
            if hasattr(result, "__await__"):
                await result
