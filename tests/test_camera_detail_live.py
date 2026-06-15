"""Tests for the camera_detail Live-Stream plumbing (Phase D).

Covers the WebRTC-preferred / snapshot-fallback decision in ``_setup_live`` and
the ``_stream_name`` slug helper. The page builds a ``ui.timer`` that runs
``_setup_live`` — the fake nicegui doesn't fire timers, so we capture the
callback and await it directly under mocked go2rtc + bridge.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

_TOKEN = "header.payload.signature"
_CAM = {
    "id": "11111111-2222-3333-4444-555555555555",
    "name": "Terrasse",
    "has_light": False,
    "pan_limit": 0,
}


def _cfg() -> dict[str, Any]:
    return {"account": {"bearer_token": _TOKEN}, "cameras": {"Terrasse": _CAM}}


class TestStreamName:
    def test_simple_no_id(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages.camera_detail import _stream_name

        assert _stream_name("Terrasse") == "bosch_terrasse"

    def test_spaces_and_symbols(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages.camera_detail import _stream_name

        assert _stream_name("Eyes Outdoor II!") == "bosch_eyes_outdoor_ii"

    def test_empty_falls_back(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages.camera_detail import _stream_name

        assert _stream_name("") == "bosch_cam"
        assert _stream_name("!!!") == "bosch_cam"

    def test_id_suffix_appended(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages.camera_detail import _stream_name

        # last 8 alnum chars of the id are appended
        name = _stream_name("Terrasse", "11111111-2222-3333-4444-5566778899aa")
        assert name == "bosch_terrasse_778899aa"

    def test_colliding_names_disambiguated_by_id(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.pages.camera_detail import _stream_name

        a = _stream_name("Eyes Outdoor", "AAAAAAAA-0000")
        b = _stream_name("Eyes-Outdoor", "BBBBBBBB-0000")
        assert a != b  # same slug, different id → different go2rtc key


async def _run_setup_live(
    fake_nicegui: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    manager: MagicMock,
    stream_info: dict[str, Any] | None,
    resolve_raises: bool = False,
) -> None:
    """Invoke camera_detail_page, capture the _setup_live timer cb, and await it."""
    from nicegui import app

    from bosch_camera_frontend.pages import camera_detail

    app.storage.general.clear()
    app.storage.general["cfg"] = _cfg()
    app.storage.general["token"] = _TOKEN

    bridge = MagicMock()
    bridge.make_session.return_value = MagicMock()

    async def _resolve(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"Terrasse": _CAM}

    async def _snap(*_a: Any, **_k: Any) -> bytes | None:
        return None

    async def _snap_events(*_a: Any, **_k: Any) -> tuple[bytes | None, str]:
        return None, ""

    async def _privacy(*_a: Any, **_k: Any) -> str | None:
        return "OFF"

    async def _events(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return []

    async def _get_stream_url(*_a: Any, **_k: Any) -> dict[str, Any] | None:
        if resolve_raises:
            raise RuntimeError("boom")
        return stream_info

    bridge.async_resolve_cam = _resolve
    bridge.async_snap_from_proxy = _snap
    bridge.async_snap_from_events = _snap_events
    bridge.async_get_privacy_mode = _privacy
    bridge.async_api_get_events = _events
    bridge.async_get_stream_url = _get_stream_url
    monkeypatch.setattr(camera_detail, "cli_bridge", bridge)
    monkeypatch.setattr(camera_detail, "get_manager", lambda: manager)

    # Capture timer callbacks (fake nicegui never fires them).
    captured: list[Any] = []
    orig_timer = fake_nicegui.ui.timer

    def _timer(interval: float, cb: Any = None, **kw: Any) -> Any:
        if cb is not None:
            captured.append(cb)
        return orig_timer(interval, cb, **kw)

    monkeypatch.setattr(fake_nicegui.ui, "timer", _timer)

    await camera_detail.camera_detail_page("Terrasse")

    # Find and run the _setup_live coroutine-callback.
    for cb in captured:
        if getattr(cb, "__name__", "") == "_setup_live":
            await cb()
            return
    raise AssertionError("_setup_live timer callback was not registered")


class TestSetupLive:
    async def test_go2rtc_unavailable_falls_back_to_snapshot(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mgr = MagicMock()
        mgr.available = False
        await _run_setup_live(
            fake_nicegui, monkeypatch, manager=mgr, stream_info=None
        )
        # never tried to register a stream
        mgr.async_add_stream.assert_not_called()

    async def test_stream_url_none_falls_back(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mgr = MagicMock()
        mgr.available = True
        await _run_setup_live(
            fake_nicegui, monkeypatch, manager=mgr, stream_info=None
        )
        mgr.async_add_stream.assert_not_called()

    async def test_resolve_raises_falls_back(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mgr = MagicMock()
        mgr.available = True
        await _run_setup_live(
            fake_nicegui, monkeypatch, manager=mgr, stream_info=None, resolve_raises=True
        )
        mgr.async_add_stream.assert_not_called()

    async def test_add_stream_fails_falls_back(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mgr = MagicMock()
        mgr.available = True

        async def _add(*_a: Any, **_k: Any) -> bool:
            return False

        mgr.async_add_stream = MagicMock(side_effect=_add)
        await _run_setup_live(
            fake_nicegui,
            monkeypatch,
            manager=mgr,
            stream_info={"url": "rtsps://h:443/x/rtsp_tunnel", "type": "REMOTE"},
        )
        mgr.async_add_stream.assert_called_once()

    async def test_happy_path_registers_and_mounts(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mgr = MagicMock()
        mgr.available = True
        mgr.base_url = "http://127.0.0.1:1984"

        async def _add(name: str, url: str) -> bool:
            # the registered URL is the resolved rtsps URL (with creds) — never
            # exposed to the browser; only base_url + name go to the player
            assert name.startswith("bosch_terrasse_")  # slug + cam_id suffix
            assert url.startswith("rtsps://")
            return True

        mgr.async_add_stream = MagicMock(side_effect=_add)
        await _run_setup_live(
            fake_nicegui,
            monkeypatch,
            manager=mgr,
            stream_info={"url": "rtsps://h:443/x/rtsp_tunnel", "type": "REMOTE"},
        )
        mgr.async_add_stream.assert_called_once()
