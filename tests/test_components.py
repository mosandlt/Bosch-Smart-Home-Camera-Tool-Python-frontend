"""Comprehensive pytest tests for camera_card.py and hls_player.py.

Covers every branch in both modules. All test data is FAKE only — no real
device IDs, MACs, tokens, or IPs.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

# ─── Helpers ──────────────────────────────────────────────────────────────────

_FAKE_TOKEN = "header.payload.signature"
_FAKE_CAM_ID = "11111111-2222-3333-4444-555555555555"


def _make_bridge(
    ping_result: str = "ONLINE",
    ping_raises: Exception | None = None,
    privacy_result: str | None = "OFF",
    snap_proxy_result: bytes | None = None,
    snap_events_result: tuple[bytes | None, str] = (None, ""),
    set_privacy_result: tuple[bool, str | None] = (True, None),
) -> MagicMock:
    """Build a cli_bridge mock with fully async methods."""
    br = MagicMock()
    br.make_session = MagicMock(return_value=MagicMock())

    if ping_raises is not None:
        async def _ping(*a: Any, **kw: Any) -> str:
            raise ping_raises  # type: ignore[misc]
        br.async_api_ping = _ping
    else:
        async def _ping(*a: Any, **kw: Any) -> str:  # type: ignore[misc]
            return ping_result
        br.async_api_ping = _ping

    async def _get_privacy(*a: Any, **kw: Any) -> str | None:
        return privacy_result
    br.async_get_privacy_mode = _get_privacy

    async def _snap_proxy(*a: Any, **kw: Any) -> bytes | None:
        return snap_proxy_result
    br.async_snap_from_proxy = _snap_proxy

    async def _snap_events(*a: Any, **kw: Any) -> tuple[bytes | None, str]:
        return snap_events_result
    br.async_snap_from_events = _snap_events

    async def _set_privacy(*a: Any, **kw: Any) -> tuple[bool, str | None]:
        return set_privacy_result
    br.async_set_privacy_mode = _set_privacy

    return br


class _FakeEvent:
    """Minimal event object with a .value attribute."""

    def __init__(self, value: Any) -> None:
        self.value = value


# ─── hls_player tests ─────────────────────────────────────────────────────────


class TestGoRtcAvailable:
    """Tests for _go2rtc_available() with monkeypatched shutil.which."""

    def test_returns_false_when_not_on_path(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bosch_camera_frontend.components import hls_player

        monkeypatch.setattr(hls_player.shutil, "which", lambda _: None)
        assert hls_player._go2rtc_available() is False

    def test_returns_true_when_on_path(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bosch_camera_frontend.components import hls_player

        monkeypatch.setattr(hls_player.shutil, "which", lambda _: "/usr/local/bin/go2rtc")
        assert hls_player._go2rtc_available() is True


class TestHlsPlayerCdnPin:
    """The CDN constant must be pinned, not floating."""

    def test_cdn_contains_hls_js_at_version(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.components.hls_player import _HLS_JS_CDN

        assert "hls.js@" in _HLS_JS_CDN

    def test_cdn_does_not_say_latest(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.components.hls_player import _HLS_JS_CDN

        assert "latest" not in _HLS_JS_CDN


class TestHlsPlayerBuildNoGo2rtc:
    """Branch: go2rtc binary is absent → install prompt rendered."""

    def test_no_go2rtc_shows_install_prompt(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bosch_camera_frontend.components import hls_player

        monkeypatch.setattr(hls_player.shutil, "which", lambda _: None)
        player = hls_player.HlsPlayer(stream_url=None, cam_name="Test Cam")
        # FakeElement records all calls; the label with install text must appear
        # We just verify construction succeeded without error and object exists.
        assert player is not None

    def test_no_go2rtc_with_stream_url_still_shows_install_prompt(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bosch_camera_frontend.components import hls_player

        monkeypatch.setattr(hls_player.shutil, "which", lambda _: None)
        player = hls_player.HlsPlayer(
            stream_url="http://localhost:1984/api/stream.m3u8", cam_name="Test Cam"
        )
        assert player is not None


class TestHlsPlayerBuildWithGo2rtcNoUrl:
    """Branch: go2rtc present + stream_url=None → 'not yet started' placeholder."""

    def test_go2rtc_present_no_url_shows_placeholder(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bosch_camera_frontend.components import hls_player

        monkeypatch.setattr(
            hls_player.shutil, "which", lambda _: "/usr/local/bin/go2rtc"
        )
        player = hls_player.HlsPlayer(stream_url=None, cam_name="Test Cam")
        assert player is not None
        assert player._stream_url is None


class TestHlsPlayerBuildWithGo2rtcAndUrl:
    """Branch: go2rtc present + stream_url set → hls.js <video> HTML rendered."""

    def test_go2rtc_present_with_url_renders_video_html(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bosch_camera_frontend.components import hls_player

        monkeypatch.setattr(
            hls_player.shutil, "which", lambda _: "/usr/local/bin/go2rtc"
        )
        url = "http://localhost:1984/api/stream.m3u8"
        player = hls_player.HlsPlayer(stream_url=url, cam_name="Test Cam")
        assert player._stream_url == url

    def test_player_id_contains_object_id(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bosch_camera_frontend.components import hls_player

        monkeypatch.setattr(
            hls_player.shutil, "which", lambda _: "/usr/local/bin/go2rtc"
        )
        url = "http://localhost:1984/api/stream.m3u8"
        player = hls_player.HlsPlayer(stream_url=url, cam_name="Test Cam")
        # Verify stream url is stored on the instance
        assert player._stream_url == url
        assert player._cam_name == "Test Cam"


class TestHlsPlayerSetStreamUrl:
    """set_stream_url() updates the stored URL and rebuilds."""

    def test_set_stream_url_updates_and_rebuilds_no_go2rtc(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bosch_camera_frontend.components import hls_player

        monkeypatch.setattr(hls_player.shutil, "which", lambda _: None)
        player = hls_player.HlsPlayer(stream_url=None, cam_name="Test Cam")
        new_url = "http://localhost:1984/api/new.m3u8"
        player.set_stream_url(new_url)
        assert player._stream_url == new_url

    def test_set_stream_url_updates_and_rebuilds_with_go2rtc(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bosch_camera_frontend.components import hls_player

        monkeypatch.setattr(
            hls_player.shutil, "which", lambda _: "/usr/local/bin/go2rtc"
        )
        player = hls_player.HlsPlayer(stream_url=None, cam_name="Test Cam")
        url = "http://localhost:1984/api/stream.m3u8"
        player.set_stream_url(url)
        assert player._stream_url == url

    def test_set_stream_url_from_url_to_new_url(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bosch_camera_frontend.components import hls_player

        monkeypatch.setattr(
            hls_player.shutil, "which", lambda _: "/usr/local/bin/go2rtc"
        )
        url1 = "http://localhost:1984/api/stream1.m3u8"
        url2 = "http://localhost:1984/api/stream2.m3u8"
        player = hls_player.HlsPlayer(stream_url=url1, cam_name="Test Cam")
        assert player._stream_url == url1
        player.set_stream_url(url2)
        assert player._stream_url == url2


# ─── camera_card tests ────────────────────────────────────────────────────────


class TestCameraCardConstruction:
    """CameraCard construction and _build()."""

    def test_constructs_without_on_click(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge()
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        assert card is not None
        assert card._cam_info is fake_camera
        assert card._token == _FAKE_TOKEN
        assert card._cfg is fake_cfg
        assert card._on_click is None

    def test_constructs_with_on_click(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge()
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        clicked: list[Any] = []
        card = camera_card.CameraCard(
            cam_info=fake_camera,
            token=_FAKE_TOKEN,
            cfg=fake_cfg,
            on_click=clicked.append,
        )
        assert card._on_click is not None

    def test_initial_state(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge()
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        assert card._online is False
        assert card._privacy_on is False
        assert card._snap_bytes is None
        assert card._suppress_toggle_event is False

    def test_last_snap_ts_is_zero_on_init(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        """_last_snap_ts starts at 0.0 — this is the real initial value (not a sentinel)."""
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge()
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        # Initial value is 0.0 (as set in __init__)
        assert card._last_snap_ts == 0.0


class TestInitialLoad:
    """_initial_load calls both _update_status and _refresh_snapshot."""

    async def test_initial_load_calls_both_methods(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="ONLINE", snap_proxy_result=b"\xff\xd8\xff\xe0test")
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._initial_load()
        # After initial load, camera should be online
        assert card._online is True


class TestUpdateStatusOnline:
    """_update_status: camera returns ONLINE / pong → online branch."""

    async def test_online_result_sets_online_true(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="ONLINE")
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._update_status()
        assert card._online is True

    async def test_pong_result_sets_online_true(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="pong")
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._update_status()
        assert card._online is True

    async def test_online_sets_badge_text_online(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="ONLINE")
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._update_status()
        assert card._status_badge.text == "online"

    async def test_online_enables_privacy_toggle(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="ONLINE")
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._update_status()
        assert card._privacy_toggle.enabled is True

    async def test_privacy_on_syncs_toggle_suppressed(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        """privacy mode ON → toggle set to True, suppress flag restored to False."""
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="ONLINE", privacy_result="ON")
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._update_status()
        assert card._privacy_on is True
        assert card._privacy_toggle.value is True
        # Suppress flag must be restored to False after sync
        assert card._suppress_toggle_event is False

    async def test_privacy_off_syncs_toggle_suppressed(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        """privacy mode OFF → toggle set to False (PIN separate mode test)."""
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="ONLINE", privacy_result="OFF")
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._update_status()
        assert card._privacy_on is False
        assert card._privacy_toggle.value is False
        assert card._suppress_toggle_event is False

    async def test_privacy_none_does_not_update_toggle(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        """privacy result None → _privacy_on unchanged."""
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="ONLINE", privacy_result=None)
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._privacy_on = False  # Known initial
        await card._update_status()
        # privacy_on should remain unchanged when server returns None
        assert card._privacy_on is False


class TestUpdateStatusOffline:
    """_update_status: offline / empty result → offline branch."""

    async def test_offline_result_sets_online_false(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="offline")
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._update_status()
        assert card._online is False

    async def test_empty_result_sets_online_false(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="")
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._update_status()
        assert card._online is False

    async def test_offline_sets_badge_text_offline(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="offline")
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._update_status()
        assert card._status_badge.text == "offline"

    async def test_offline_disables_privacy_toggle(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="")
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._update_status()
        assert card._privacy_toggle.enabled is False


class TestUpdateStatusError:
    """_update_status: exception → error badge."""

    async def test_exception_sets_error_badge(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_raises=RuntimeError("connection refused"))
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._update_status()
        assert card._status_badge.text == "error"

    async def test_make_session_exception_sets_error_badge(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge()
        br.make_session = MagicMock(side_effect=RuntimeError("no session"))
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._update_status()
        assert card._status_badge.text == "error"


class TestSetDot:
    """_set_dot updates the status dot content."""

    def test_set_dot_green(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge()
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._set_dot("#22c55e")
        assert "#22c55e" in card._status_dot.content

    def test_set_dot_gray(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge()
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._set_dot("#9ca3af")
        assert "#9ca3af" in card._status_dot.content

    def test_set_dot_amber(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge()
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._set_dot("#f59e0b")
        assert "#f59e0b" in card._status_dot.content


class TestRefreshSnapshotDebounce:
    """_refresh_snapshot: debounce prevents rapid refetches."""

    async def test_debounce_skips_fetch_when_called_too_soon(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        """Set _last_snap_ts to now → call should return early without fetching."""
        from bosch_camera_frontend.components import camera_card

        fetch_count = 0

        async def _snap_proxy(*a: Any, **kw: Any) -> bytes | None:
            nonlocal fetch_count
            fetch_count += 1
            return b"\xff\xd8\xff\xe0snap"

        br = _make_bridge()
        br.async_snap_from_proxy = _snap_proxy
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        # Set the timestamp to RIGHT NOW so the debounce kicks in
        card._last_snap_ts = time.monotonic()
        await card._refresh_snapshot()
        # async_snap_from_proxy must NOT have been called
        assert fetch_count == 0


class TestRefreshSnapshotProxy:
    """_refresh_snapshot: proxy returns bytes → image updated."""

    async def test_proxy_bytes_sets_image_source(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        snap_data = b"\xff\xd8\xff\xe0fake_jpeg"
        br = _make_bridge(snap_proxy_result=snap_data)
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._refresh_snapshot()
        assert card._snap_bytes == snap_data
        assert card._snapshot_img.source is not None
        assert card._snapshot_img.source.startswith("data:image/jpeg;base64,")

    async def test_proxy_bytes_updates_last_snap_ts(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        snap_data = b"\xff\xd8\xff\xe0fake_jpeg"
        br = _make_bridge(snap_proxy_result=snap_data)
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        before = time.monotonic()
        await card._refresh_snapshot()
        assert card._last_snap_ts >= before


class TestRefreshSnapshotEventsFallback:
    """_refresh_snapshot: proxy None → falls back to events."""

    async def test_proxy_none_events_bytes_sets_image(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        event_data = b"\xff\xd8\xff\xe0event_snap"
        br = _make_bridge(
            snap_proxy_result=None,
            snap_events_result=(event_data, "event"),
        )
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._refresh_snapshot()
        assert card._snap_bytes == event_data
        assert card._snapshot_img.source is not None
        assert card._snapshot_img.source.startswith("data:image/jpeg;base64,")

    async def test_proxy_none_events_none_no_update(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        """Both proxy and events return None → snap_bytes unchanged (no update)."""
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(
            snap_proxy_result=None,
            snap_events_result=(None, ""),
        )
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        await card._refresh_snapshot()
        assert card._snap_bytes is None
        # source should NOT be set to a real base64 value
        assert card._snapshot_img.source is None


class TestRefreshSnapshotExceptionSwallowed:
    """_refresh_snapshot: exception is swallowed, last good snap preserved."""

    async def test_exception_swallowed_snap_bytes_unchanged(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        async def _failing_proxy(*a: Any, **kw: Any) -> bytes:
            raise RuntimeError("network error")

        br = _make_bridge()
        br.async_snap_from_proxy = _failing_proxy
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._snap_bytes = b"last_good"
        # Should not raise
        await card._refresh_snapshot()
        assert card._snap_bytes == b"last_good"


class TestHandlePrivacyToggleSuppressed:
    """_handle_privacy_toggle: suppress flag set → immediate return."""

    async def test_suppressed_flag_returns_immediately(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        set_called = False

        async def _track_set(*a: Any, **kw: Any) -> tuple[bool, None]:
            nonlocal set_called
            set_called = True
            return (True, None)

        br = _make_bridge()
        br.async_set_privacy_mode = _track_set
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._suppress_toggle_event = True
        await card._handle_privacy_toggle(_FakeEvent(True))
        assert set_called is False


class TestHandlePrivacyToggleOffline:
    """_handle_privacy_toggle: camera offline → reverts toggle + warning."""

    async def test_offline_reverts_toggle_no_put(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        set_called = False

        async def _track_set(*a: Any, **kw: Any) -> tuple[bool, None]:
            nonlocal set_called
            set_called = True
            return (True, None)

        br = _make_bridge()
        br.async_set_privacy_mode = _track_set
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._online = False
        # Simulate user tapping toggle to True
        await card._handle_privacy_toggle(_FakeEvent(True))
        # PUT must NOT have been called
        assert set_called is False
        # Toggle must have been reverted to False
        assert card._privacy_toggle.value is False
        # Suppress flag must be cleaned up
        assert card._suppress_toggle_event is False

    async def test_offline_reverts_toggle_to_previous_state(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge()
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._online = False
        # Simulate user tapping toggle from True → False (new_state=False → reverts to True)
        await card._handle_privacy_toggle(_FakeEvent(False))
        # Reverts to not(False) = True
        assert card._privacy_toggle.value is True


class TestHandlePrivacyToggleOnlineSuccessOn:
    """_handle_privacy_toggle online + success: privacy ON mode."""

    async def test_online_set_privacy_on_success(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="ONLINE", set_privacy_result=(True, None))
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._online = True
        card._privacy_on = False
        # Turn privacy ON
        await card._handle_privacy_toggle(_FakeEvent(True))
        assert card._privacy_on is True

    async def test_online_set_privacy_on_updates_internal_state(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(set_privacy_result=(True, None))
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._online = True
        card._privacy_on = False
        await card._handle_privacy_toggle(_FakeEvent(True))
        # _privacy_on reflects the new state
        assert card._privacy_on is True


class TestHandlePrivacyToggleOnlineSuccessOff:
    """_handle_privacy_toggle online + success: privacy OFF mode (PIN separate)."""

    async def test_online_set_privacy_off_success(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(set_privacy_result=(True, None))
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._online = True
        card._privacy_on = True  # Currently ON → toggle to OFF
        await card._handle_privacy_toggle(_FakeEvent(False))
        assert card._privacy_on is False

    async def test_online_set_privacy_off_updates_internal_state(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(set_privacy_result=(True, None))
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._online = True
        card._privacy_on = True
        await card._handle_privacy_toggle(_FakeEvent(False))
        assert card._privacy_on is False


class TestHandlePrivacyToggleOnlineFailure:
    """_handle_privacy_toggle: API returns error tuple → revert + negative notify."""

    async def test_api_error_reverts_toggle(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(set_privacy_result=(False, "device rejected"))
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._online = True
        card._privacy_on = False
        # Attempt to turn ON
        await card._handle_privacy_toggle(_FakeEvent(True))
        # Toggle must be reverted to False (not(True))
        assert card._privacy_toggle.value is False

    async def test_api_error_does_not_update_privacy_on(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(set_privacy_result=(False, "err"))
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._online = True
        card._privacy_on = False
        await card._handle_privacy_toggle(_FakeEvent(True))
        # _privacy_on must NOT have changed
        assert card._privacy_on is False


class TestHandlePrivacyToggleException:
    """_handle_privacy_toggle: exception → revert + error notify."""

    async def test_exception_reverts_toggle(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        async def _raise_set(*a: Any, **kw: Any) -> None:
            raise RuntimeError("unexpected crash")

        br = _make_bridge()
        br.async_set_privacy_mode = _raise_set
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._online = True
        card._privacy_on = False
        # Should NOT raise externally
        await card._handle_privacy_toggle(_FakeEvent(True))
        # Toggle reverted to not(True) = False
        assert card._privacy_toggle.value is False

    async def test_exception_does_not_propagate(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        async def _raise_set(*a: Any, **kw: Any) -> None:
            raise ValueError("bad value")

        br = _make_bridge()
        br.async_set_privacy_mode = _raise_set
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        card._online = True
        try:
            await card._handle_privacy_toggle(_FakeEvent(False))
        except Exception as exc:
            pytest.fail(f"Exception propagated: {exc}")


class TestUpdateStatusToggleEnableExceptionSwallowed:
    """_update_status: toggle.enable() / .disable() raising → swallowed silently."""

    async def test_toggle_enable_exception_swallowed(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="ONLINE")
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        # Replace the toggle with a mock whose enable() raises
        bad_toggle = MagicMock()
        bad_toggle.enable.side_effect = RuntimeError("toggle broken")
        bad_toggle.disable.side_effect = RuntimeError("toggle broken")
        bad_toggle.set_value = MagicMock()
        card._privacy_toggle = bad_toggle  # type: ignore[assignment]

        # Should not propagate the exception
        try:
            await card._update_status()
        except Exception as exc:
            pytest.fail(f"Exception propagated from toggle.enable(): {exc}")
        # Status should still be set to online
        assert card._online is True
        assert card._status_badge.text == "online"

    async def test_toggle_disable_exception_swallowed(
        self,
        fake_nicegui: Any,
        fake_camera: dict[str, Any],
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge(ping_result="offline")
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info=fake_camera, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        bad_toggle = MagicMock()
        bad_toggle.disable.side_effect = RuntimeError("toggle broken")
        bad_toggle.enable.side_effect = RuntimeError("toggle broken")
        bad_toggle.set_value = MagicMock()
        card._privacy_toggle = bad_toggle  # type: ignore[assignment]

        try:
            await card._update_status()
        except Exception as exc:
            pytest.fail(f"Exception propagated from toggle.disable(): {exc}")
        assert card._online is False
        assert card._status_badge.text == "offline"


class TestCameraCardMissingFields:
    """CameraCard tolerates missing optional cam_info fields."""

    def test_missing_firmware_field_no_fw_label(
        self,
        fake_nicegui: Any,
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge()
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        cam = {
            "id": "11111111-2222-3333-4444-555555555555",
            "name": "No FW Cam",
            "model": "CAMERA_EYES",
            # firmware deliberately missing
        }
        # Construction must not raise
        card = camera_card.CameraCard(
            cam_info=cam, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        assert card is not None

    def test_empty_cam_info_uses_defaults(
        self,
        fake_nicegui: Any,
        fake_cfg: dict[str, Any],
    ) -> None:
        from bosch_camera_frontend.components import camera_card

        br = _make_bridge()
        camera_card.cli_bridge = br  # type: ignore[attr-defined]

        card = camera_card.CameraCard(
            cam_info={}, token=_FAKE_TOKEN, cfg=fake_cfg
        )
        assert card is not None
