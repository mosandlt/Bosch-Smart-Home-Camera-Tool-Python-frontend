"""StreamSession — keeps a go2rtc stream registration fresh (WebRTC Phase E).

Gen2 Bosch cameras ROTATE the Digest credentials on every ``PUT /connection``,
so the ``rtsps://`` URL that go2rtc consumes goes stale after a while and the
producer dies (the same problem HA solves with its local ``tls_proxy.py`` + a
heartbeat). The robust long-term fix is to port that proxy so go2rtc consumes a
stable local ``rtsp://127.0.0.1`` endpoint; that is PARKED (large, and needs a
live Gen2 camera to validate).

This is the pragmatic option (a) from docs/live-webrtc-plan.md: periodically
RE-RESOLVE the stream URL (a fresh ``PUT /connection``, which mints fresh creds
and a fresh session) and RE-REGISTER it with go2rtc under the same stream name,
staying ahead of the camera's session lifetime. go2rtc replaces the source in
place; the browser player's reconnect logic rides over the brief blip.

The resolver is injected (an async callable returning the same dict shape as
``cli_bridge.async_get_stream_url`` — ``{"url": ..., "type": ...}`` or ``None``)
so this stays decoupled from the CLI bridge and trivially unit-testable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from bosch_camera_frontend.adapters.go2rtc_manager import Go2rtcManager

# Bosch live sessions use maxSessionDuration=3600s; refresh comfortably ahead of
# expiry so the source never goes stale under an open live view.
DEFAULT_REFRESH_INTERVAL = 3000.0

StreamResolver = Callable[[], Awaitable[dict[str, object] | None]]


class StreamSession:
    """Owns one camera's go2rtc stream registration and keeps it fresh.

    Args:
        manager: the shared :class:`Go2rtcManager`.
        resolver: async callable returning a stream-info dict (``{"url": ...}``)
            or ``None`` — typically a closure over ``async_get_stream_url``.
        name: the go2rtc stream name (the browser ``?src=`` value).
        refresh_interval: seconds between proactive re-registrations.
    """

    def __init__(
        self,
        manager: Go2rtcManager,
        resolver: StreamResolver,
        name: str,
        refresh_interval: float = DEFAULT_REFRESH_INTERVAL,
    ) -> None:
        self._mgr = manager
        self._resolver = resolver
        self._name = name
        self._refresh_interval = max(60.0, float(refresh_interval))
        self._active = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def active(self) -> bool:
        """True once the stream has been registered and not yet stopped."""
        return self._active

    @property
    def refresh_interval(self) -> float:
        return self._refresh_interval

    async def start(self) -> bool:
        """Resolve + register the stream for the first time. Returns success."""
        ok = await self._resolve_and_register()
        self._active = ok
        return ok

    async def refresh(self) -> bool:
        """Re-resolve + re-register (called on a timer ahead of cred rotation).

        No-op (returns False) once the session has been stopped, so a lingering
        timer can't resurrect a torn-down stream.
        """
        if not self._active:
            return False
        return await self._resolve_and_register()

    async def stop(self) -> None:
        """Deregister the stream from go2rtc. Safe to call once; idempotent."""
        if not self._active:
            return
        self._active = False
        await self._mgr.async_remove_stream(self._name)

    async def _resolve_and_register(self) -> bool:
        try:
            info = await self._resolver()
        except Exception:  # noqa: BLE001 — a failed resolve must not crash callers
            return False
        if not info:
            return False
        url = info.get("url")
        if not isinstance(url, str) or not url:
            return False
        return await self._mgr.async_add_stream(self._name, url)
