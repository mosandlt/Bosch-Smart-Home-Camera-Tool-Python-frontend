"""Tests for StreamSession — go2rtc registration refresh (WebRTC Phase E)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from bosch_camera_frontend.adapters.stream_session import (
    DEFAULT_REFRESH_INTERVAL,
    StreamSession,
)


def _mgr(add_ok: bool = True) -> MagicMock:
    m = MagicMock()
    m.async_add_stream = AsyncMock(return_value=add_ok)
    m.async_remove_stream = AsyncMock(return_value=True)
    return m


def _resolver(url: str | None = "rtsps://h:443/x/rtsp_tunnel") -> Any:
    info = {"url": url, "type": "REMOTE"} if url is not None else None
    return AsyncMock(return_value=info)


class TestStart:
    async def test_start_registers_and_marks_active(self) -> None:
        mgr = _mgr()
        s = StreamSession(mgr, _resolver(), "bosch_cam_1234")
        assert await s.start() is True
        assert s.active is True
        mgr.async_add_stream.assert_awaited_once_with(
            "bosch_cam_1234", "rtsps://h:443/x/rtsp_tunnel"
        )

    async def test_start_failure_when_resolver_none(self) -> None:
        mgr = _mgr()
        s = StreamSession(mgr, _resolver(url=None), "cam")
        assert await s.start() is False
        assert s.active is False
        mgr.async_add_stream.assert_not_awaited()

    async def test_start_failure_when_url_missing(self) -> None:
        mgr = _mgr()
        resolver = AsyncMock(return_value={"type": "REMOTE"})  # no "url"
        s = StreamSession(mgr, resolver, "cam")
        assert await s.start() is False
        assert s.active is False

    async def test_start_failure_when_add_stream_false(self) -> None:
        mgr = _mgr(add_ok=False)
        s = StreamSession(mgr, _resolver(), "cam")
        assert await s.start() is False
        assert s.active is False

    async def test_start_resolver_raises_returns_false(self) -> None:
        mgr = _mgr()
        resolver = AsyncMock(side_effect=RuntimeError("boom"))
        s = StreamSession(mgr, resolver, "cam")
        assert await s.start() is False
        assert s.active is False


class TestRefresh:
    async def test_refresh_reregisters_while_active(self) -> None:
        mgr = _mgr()
        s = StreamSession(mgr, _resolver(), "cam")
        await s.start()
        mgr.async_add_stream.reset_mock()
        assert await s.refresh() is True
        mgr.async_add_stream.assert_awaited_once()

    async def test_refresh_noop_when_not_started(self) -> None:
        mgr = _mgr()
        s = StreamSession(mgr, _resolver(), "cam")
        assert await s.refresh() is False
        mgr.async_add_stream.assert_not_awaited()

    async def test_refresh_noop_after_stop(self) -> None:
        mgr = _mgr()
        s = StreamSession(mgr, _resolver(), "cam")
        await s.start()
        await s.stop()
        mgr.async_add_stream.reset_mock()
        # a lingering timer must not resurrect a torn-down stream
        assert await s.refresh() is False
        mgr.async_add_stream.assert_not_awaited()


class TestStop:
    async def test_stop_removes_stream(self) -> None:
        mgr = _mgr()
        s = StreamSession(mgr, _resolver(), "cam")
        await s.start()
        await s.stop()
        assert s.active is False
        mgr.async_remove_stream.assert_awaited_once_with("cam")

    async def test_stop_is_idempotent_and_safe_when_never_started(self) -> None:
        mgr = _mgr()
        s = StreamSession(mgr, _resolver(), "cam")
        await s.stop()  # never started
        await s.stop()  # twice
        mgr.async_remove_stream.assert_not_awaited()


class TestConfig:
    def test_refresh_interval_default(self) -> None:
        s = StreamSession(_mgr(), _resolver(), "cam")
        assert s.refresh_interval == DEFAULT_REFRESH_INTERVAL

    def test_refresh_interval_clamped_to_minimum(self) -> None:
        s = StreamSession(_mgr(), _resolver(), "cam", refresh_interval=5.0)
        assert s.refresh_interval == 60.0

    def test_name_exposed(self) -> None:
        s = StreamSession(_mgr(), _resolver(), "bosch_terrasse_abcd")
        assert s.name == "bosch_terrasse_abcd"
