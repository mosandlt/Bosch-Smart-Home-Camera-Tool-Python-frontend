"""Tests for the light / motion / intrusion detection controls added to the
camera detail page (feature-parity wiring — see cli_bridge_controls tests for
the underlying bridge functions). Mirrors the fake_nicegui + capture-callback
pattern established in test_pages.py's TestCameraDetailLoadPrivacy /
TestCameraDetailTogglePrivacy. FAKE DATA ONLY.
"""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import MagicMock


def _fake_session() -> MagicMock:
    return MagicMock(name="session")


def _fake_cam(*, has_light: bool = True) -> dict[str, Any]:
    return {
        "id": "11111111-2222-3333-4444-555555555555",
        "name": "Test Cam",
        "model": "CAMERA_EYES",
        "firmware": "9.0.0",
        "mac": "aa:bb:cc:dd:ee:ff",
        "download_folder": "Test Cam",
        "local_ip": "",
        "has_light": has_light,
        "pan_limit": 0,
    }


def _make_cfg(cam: dict[str, Any]) -> dict[str, Any]:
    return {
        "account": {"bearer_token": "header.payload.signature"},
        "language": "en",
        "cameras": {cam["name"]: cam},
    }


def _base_bridge(cam: dict[str, Any]) -> MagicMock:
    bridge = MagicMock()
    bridge.make_session.return_value = _fake_session()

    async def _found(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {"Test Cam": cam}

    async def _priv(*_a: Any, **_kw: Any) -> str:
        return "OFF"

    async def _ev_list(*_a: Any, **_kw: Any) -> list[Any]:
        return []

    bridge.async_resolve_cam = _found
    bridge.async_get_privacy_mode = _priv
    bridge.async_api_get_events = _ev_list
    return bridge


async def _run_all_timers(
    fake_nicegui: Any, bridge: MagicMock, has_light: bool = True
) -> None:
    """Import camera_detail fresh, wire *bridge*, render the page, then fire
    every once=True ui.timer callback (this triggers _load_privacy,
    _load_light, _load_motion, _load_intrusion, load_snapshot, _load_events)."""
    from nicegui import app, ui

    cam = _fake_cam(has_light=has_light)
    cfg = _make_cfg(cam)
    app.storage.general.clear()
    app.storage.general["cfg"] = cfg
    app.storage.general["token"] = "header.payload.signature"

    from bosch_camera_frontend.pages import camera_detail

    camera_detail.cli_bridge = bridge

    timer_calls: list[Any] = []
    original_timer = ui.timer

    def cap_timer(*a: Any, **kw: Any) -> Any:
        if kw.get("once"):
            cb = a[1] if len(a) > 1 else kw.get("callback")
            if cb:
                timer_calls.append(cb)
        return original_timer(*a, **kw)

    ui.timer = cap_timer  # type: ignore[assignment]
    try:
        await camera_detail.camera_detail_page("Test%20Cam")
    finally:
        ui.timer = original_timer  # type: ignore[assignment]

    for fn in timer_calls:
        try:
            r = fn()
            if hasattr(r, "__await__"):
                await r
        except Exception:
            pass


class TestCameraDetailLightControl:
    async def test_load_light_on(self, fake_nicegui: Any) -> None:
        cam = _fake_cam(has_light=True)
        bridge = _base_bridge(cam)

        async def _get_light(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {
                "frontLightOn": True,
                "wallwasherOn": True,
                "frontLightIntensity": 1.0,
            }

        bridge.async_get_light_override = _get_light
        await _run_all_timers(fake_nicegui, bridge, has_light=True)

    async def test_load_light_unavailable(self, fake_nicegui: Any) -> None:
        cam = _fake_cam(has_light=True)
        bridge = _base_bridge(cam)

        async def _get_light_none(*_a: Any, **_kw: Any) -> None:
            return None

        bridge.async_get_light_override = _get_light_none
        await _run_all_timers(fake_nicegui, bridge, has_light=True)

    async def test_toggle_light_success(self, fake_nicegui: Any) -> None:
        from nicegui import app, ui

        cam = _fake_cam(has_light=True)
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = _base_bridge(cam)

        async def _get_light(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"frontLightOn": False}

        async def _set_light(*_a: Any, **_kw: Any) -> tuple[bool, str | None]:
            return True, None

        bridge.async_get_light_override = _get_light
        bridge.async_set_light_override = _set_light

        from bosch_camera_frontend.pages import camera_detail

        camera_detail.cli_bridge = bridge

        switch_holder: list[Any] = []
        original_switch = ui.switch

        def cap_switch(*a: Any, **kw: Any) -> Any:
            on_change = kw.get("on_change")
            if on_change and a and a[0] == "Camera Light":
                switch_holder.append(on_change)
            return original_switch(*a, **kw)

        ui.switch = cap_switch  # type: ignore[assignment]
        try:
            await camera_detail.camera_detail_page("Test%20Cam")
        finally:
            ui.switch = original_switch  # type: ignore[assignment]

        assert switch_holder
        event = types.SimpleNamespace(value=True)
        result = switch_holder[0](event)
        if hasattr(result, "__await__"):
            await result

    async def test_toggle_light_fail(self, fake_nicegui: Any) -> None:
        from nicegui import app, ui

        cam = _fake_cam(has_light=True)
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = _base_bridge(cam)

        async def _get_light(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"frontLightOn": False}

        async def _set_light_fail(*_a: Any, **_kw: Any) -> tuple[bool, str | None]:
            return False, "Camera offline"

        bridge.async_get_light_override = _get_light
        bridge.async_set_light_override = _set_light_fail

        from bosch_camera_frontend.pages import camera_detail

        camera_detail.cli_bridge = bridge

        switch_holder: list[Any] = []
        original_switch = ui.switch

        def cap_switch(*a: Any, **kw: Any) -> Any:
            on_change = kw.get("on_change")
            if on_change and a and a[0] == "Camera Light":
                switch_holder.append(on_change)
            return original_switch(*a, **kw)

        ui.switch = cap_switch  # type: ignore[assignment]
        try:
            await camera_detail.camera_detail_page("Test%20Cam")
        finally:
            ui.switch = original_switch  # type: ignore[assignment]

        assert switch_holder
        event = types.SimpleNamespace(value=True)
        result = switch_holder[0](event)
        if hasattr(result, "__await__"):
            await result

    async def test_no_light_section_when_unsupported(self, fake_nicegui: Any) -> None:
        cam = _fake_cam(has_light=False)
        bridge = _base_bridge(cam)
        await _run_all_timers(fake_nicegui, bridge, has_light=False)


class TestCameraDetailMotionControl:
    async def test_load_motion_enabled(self, fake_nicegui: Any) -> None:
        cam = _fake_cam(has_light=False)
        bridge = _base_bridge(cam)

        async def _get_motion(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"enabled": True, "motionAlarmConfiguration": "HIGH"}

        bridge.async_get_motion_detection = _get_motion
        await _run_all_timers(fake_nicegui, bridge, has_light=False)

    async def test_load_motion_unknown_sensitivity_ignored(
        self, fake_nicegui: Any
    ) -> None:
        cam = _fake_cam(has_light=False)
        bridge = _base_bridge(cam)

        async def _get_motion(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"enabled": True, "motionAlarmConfiguration": "NOT_A_REAL_VALUE"}

        bridge.async_get_motion_detection = _get_motion
        await _run_all_timers(fake_nicegui, bridge, has_light=False)

    async def test_load_motion_unavailable(self, fake_nicegui: Any) -> None:
        cam = _fake_cam(has_light=False)
        bridge = _base_bridge(cam)

        async def _get_motion_none(*_a: Any, **_kw: Any) -> None:
            return None

        bridge.async_get_motion_detection = _get_motion_none
        await _run_all_timers(fake_nicegui, bridge, has_light=False)

    async def test_apply_motion_success(self, fake_nicegui: Any) -> None:
        from nicegui import app, ui

        cam = _fake_cam(has_light=False)
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = _base_bridge(cam)

        async def _get_motion(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"enabled": False, "motionAlarmConfiguration": "OFF"}

        async def _set_motion(*_a: Any, **_kw: Any) -> tuple[bool, str | None]:
            return True, None

        bridge.async_get_motion_detection = _get_motion
        bridge.async_set_motion_detection = _set_motion

        from bosch_camera_frontend.pages import camera_detail

        camera_detail.cli_bridge = bridge

        button_holder: list[Any] = []
        original_button = ui.button

        def cap_button(*a: Any, **kw: Any) -> Any:
            on_click = kw.get("on_click")
            if on_click and a and a[0] == "Apply":
                button_holder.append(on_click)
            return original_button(*a, **kw)

        ui.button = cap_button  # type: ignore[assignment]
        try:
            await camera_detail.camera_detail_page("Test%20Cam")
        finally:
            ui.button = original_button  # type: ignore[assignment]

        # First "Apply" button belongs to the Motion Detection section.
        assert len(button_holder) >= 1
        result = button_holder[0]()
        if hasattr(result, "__await__"):
            await result

    async def test_apply_motion_fail_resyncs_from_server(
        self, fake_nicegui: Any
    ) -> None:
        """On a failed Apply, _load_motion re-runs so the UI reflects server
        truth instead of the attempted (unconfirmed) values, matching the
        privacy/light toggles' revert-on-failure behavior."""
        from nicegui import app, ui

        cam = _fake_cam(has_light=False)
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = _base_bridge(cam)
        get_calls = 0

        async def _get_motion(*_a: Any, **_kw: Any) -> dict[str, Any]:
            nonlocal get_calls
            get_calls += 1
            return {"enabled": False, "motionAlarmConfiguration": "OFF"}

        async def _set_motion_fail(*_a: Any, **_kw: Any) -> tuple[bool, str | None]:
            return False, "Auth expired — refresh token"

        bridge.async_get_motion_detection = _get_motion
        bridge.async_set_motion_detection = _set_motion_fail

        from bosch_camera_frontend.pages import camera_detail

        camera_detail.cli_bridge = bridge

        button_holder: list[Any] = []
        original_button = ui.button

        def cap_button(*a: Any, **kw: Any) -> Any:
            on_click = kw.get("on_click")
            if on_click and a and a[0] == "Apply":
                button_holder.append(on_click)
            return original_button(*a, **kw)

        ui.button = cap_button  # type: ignore[assignment]
        try:
            await camera_detail.camera_detail_page("Test%20Cam")
        finally:
            ui.button = original_button  # type: ignore[assignment]

        assert len(button_holder) >= 1
        calls_before_apply = get_calls  # includes the initial page-load fetch
        result = button_holder[0]()
        if hasattr(result, "__await__"):
            await result

        assert get_calls > calls_before_apply


class TestCameraDetailIntrusionControl:
    async def test_load_intrusion_enabled(self, fake_nicegui: Any) -> None:
        cam = _fake_cam(has_light=False)
        bridge = _base_bridge(cam)

        async def _get_intrusion(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {
                "enabled": True,
                "detectionMode": "ZONES",
                "sensitivity": 4,
                "distance": 6,
            }

        bridge.async_get_intrusion_detection = _get_intrusion
        await _run_all_timers(fake_nicegui, bridge, has_light=False)

    async def test_load_intrusion_unsupported(self, fake_nicegui: Any) -> None:
        cam = _fake_cam(has_light=False)
        bridge = _base_bridge(cam)

        async def _get_intrusion_none(*_a: Any, **_kw: Any) -> None:
            return None

        bridge.async_get_intrusion_detection = _get_intrusion_none
        await _run_all_timers(fake_nicegui, bridge, has_light=False)

    async def test_apply_intrusion_success_forwards_detection_mode(
        self, fake_nicegui: Any
    ) -> None:
        """Regression test (bug-hunt 2026-07): _apply_intrusion must forward
        detection_mode — this is a full-object PUT (like light/motion), so a
        prior version that omitted it risked the server silently resetting
        the zone/all-motions mode on every Apply."""
        from nicegui import app, ui

        cam = _fake_cam(has_light=False)
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = _base_bridge(cam)
        set_calls: list[tuple[Any, ...]] = []

        async def _get_intrusion(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {
                "enabled": False,
                "detectionMode": "ZONES",
                "sensitivity": 3,
                "distance": 5,
            }

        async def _set_intrusion(*a: Any, **kw: Any) -> tuple[bool, str | None]:
            set_calls.append((a, kw))
            return True, None

        bridge.async_get_intrusion_detection = _get_intrusion
        bridge.async_set_intrusion_detection = _set_intrusion

        from bosch_camera_frontend.pages import camera_detail

        camera_detail.cli_bridge = bridge

        button_holder: list[Any] = []
        original_button = ui.button

        def cap_button(*a: Any, **kw: Any) -> Any:
            on_click = kw.get("on_click")
            if on_click and a and a[0] == "Apply":
                button_holder.append(on_click)
            return original_button(*a, **kw)

        ui.button = cap_button  # type: ignore[assignment]
        try:
            await camera_detail.camera_detail_page("Test%20Cam")
        finally:
            ui.button = original_button  # type: ignore[assignment]

        # Second "Apply" button belongs to the Intrusion Detection section.
        assert len(button_holder) >= 2
        result = button_holder[1]()
        if hasattr(result, "__await__"):
            await result

        assert set_calls, "async_set_intrusion_detection was never called"
        _, kwargs = set_calls[-1]
        assert kwargs.get("detection_mode") is not None, (
            "detection_mode must always be forwarded on Apply "
            "(full-object PUT — omitting it can reset server-side state)"
        )

    async def test_apply_intrusion_fail_resyncs_from_server(
        self, fake_nicegui: Any
    ) -> None:
        """On a failed Apply, the UI must not keep showing the attempted
        (unconfirmed) values — _load_intrusion re-runs to reflect server
        truth, matching the privacy/light toggles' revert-on-failure."""
        from nicegui import app, ui

        cam = _fake_cam(has_light=False)
        cfg = _make_cfg(cam)
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        app.storage.general["token"] = "header.payload.signature"

        bridge = _base_bridge(cam)
        get_calls = 0

        async def _get_intrusion(*_a: Any, **_kw: Any) -> dict[str, Any]:
            nonlocal get_calls
            get_calls += 1
            return {"enabled": False, "sensitivity": 3, "distance": 5}

        async def _set_intrusion_fail(*_a: Any, **_kw: Any) -> tuple[bool, str | None]:
            return False, "Not supported on this camera model"

        bridge.async_get_intrusion_detection = _get_intrusion
        bridge.async_set_intrusion_detection = _set_intrusion_fail

        from bosch_camera_frontend.pages import camera_detail

        camera_detail.cli_bridge = bridge

        button_holder: list[Any] = []
        original_button = ui.button

        def cap_button(*a: Any, **kw: Any) -> Any:
            on_click = kw.get("on_click")
            if on_click and a and a[0] == "Apply":
                button_holder.append(on_click)
            return original_button(*a, **kw)

        ui.button = cap_button  # type: ignore[assignment]
        try:
            await camera_detail.camera_detail_page("Test%20Cam")
        finally:
            ui.button = original_button  # type: ignore[assignment]

        assert len(button_holder) >= 2
        calls_before_apply = get_calls  # includes the initial page-load fetch
        result = button_holder[1]()
        if hasattr(result, "__await__"):
            await result

        # _apply_intrusion must have re-fetched on failure.
        assert get_calls > calls_before_apply
