"""LiveSnapshotPlayer — a near-live view built on the snapshot pipeline.

The Python CLI has no live RTSP/WebRTC backend (only snapshots + the cloud API),
so a true WebRTC player like the HA card / ioBroker widget is a separate project
(see docs/live-webrtc-plan.md). This component delivers a real "live-ish" view NOW
by refreshing the snapshot every `interval` seconds.

It carries the cross-product lifecycle lesson from HA v13.5.17: a hidden browser
tab must not keep pulling frames — that wastes the camera's limited Bosch session
budget (≈3 concurrent sessions / 60-min cap). So the refresh loop PAUSES while the
tab is hidden and RESUMES when it becomes visible again.

Phase 2 (real WebRTC/HLS via go2rtc) will live in `hls_player.py`; this component
is the snapshot-tier player and stays useful as the no-go2rtc fallback.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable

from nicegui import ui

# One global client-side visibility bridge (reused by every player instance):
# emits a NiceGUI event whenever the tab's visibility flips.
_VISIBILITY_BRIDGE_JS = (
    "<script>if(!window.__boschVisWired){window.__boschVisWired=1;"
    "document.addEventListener('visibilitychange',function(){"
    "emitEvent('bosch_live_visibility',{visible:document.visibilityState==='visible'});"
    "});}</script>"
)


class LiveSnapshotPlayer(ui.element):
    """Near-live snapshot-refresh player.

    Args:
        fetch_fn: async callable returning JPEG bytes (or None on failure) — e.g. a
                  closure over ``cli_bridge.async_snap_from_proxy``.
        cam_name: camera name (display only).
        interval: refresh period in seconds (default 5.0 — matches HA's indoor
                  snapshot cadence; the Bosch session budget is scarce (≈3
                  concurrent / 60-min cap) so don't go below ~5 s, and prefer ~10 s
                  for outdoor cameras).
        autostart: start the loop immediately on build (default False — the user
                   presses play, matching the HA "tap to start" gate).
    """

    def __init__(
        self,
        fetch_fn: Callable[[], Awaitable[bytes | None]],
        cam_name: str = "",
        interval: float = 2.0,
        autostart: bool = False,
    ) -> None:
        super().__init__("div")
        self._fetch = fetch_fn
        self._cam_name = cam_name
        self._interval = max(0.5, float(interval))
        self._playing = False
        self._timer: ui.timer | None = None
        self._in_flight = False  # guard against overlapping fetches on a slow link
        self._img: ui.image | None = None
        self._status: ui.label | None = None
        self._play_btn: ui.button | None = None
        self._build()
        if autostart:
            self.start()

    def _build(self) -> None:
        with self:
            self._img = (
                ui.image("")
                .classes("w-full")
                # isolation:isolate flattens the rounded clip into one layer so the
                # corners don't flicker on repaint (HA v13.5.17 corner-flicker fix).
                .style(
                    "max-height: 360px; object-fit: contain; background: #000;"
                    " border-radius: 8px; isolation: isolate;"
                )
            )
            with ui.row().classes("items-center gap-2 p-1"):
                self._play_btn = ui.button(
                    icon="play_arrow", on_click=self.toggle
                ).props("round dense")
                self._status = ui.label("Snapshot live — press play").classes(
                    "text-xs text-gray-400"
                )
        # Pause the refresh loop while the tab is hidden (saves the camera's Bosch
        # session budget); resume when visible. 2026-06-15 (HA-lifecycle parity).
        ui.add_head_html(_VISIBILITY_BRIDGE_JS)
        ui.on("bosch_live_visibility", self._on_visibility)

    # -- controls ------------------------------------------------------------

    def toggle(self) -> None:
        """Play/pause from the button."""
        if self._playing:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        """Begin the refresh loop (idempotent)."""
        if self._playing:
            return
        self._playing = True
        if self._play_btn:
            self._play_btn.props("icon=pause")
        if self._status:
            self._status.set_text("Live ●")
        # Repeating loop + one immediate frame so play feels instant.
        if self._timer is None:
            self._timer = ui.timer(self._interval, self._tick)
        else:
            self._timer.active = True
        ui.timer(0.05, self._tick, once=True)

    def stop(self) -> None:
        """Pause the refresh loop (idempotent)."""
        self._playing = False
        if self._timer:
            self._timer.active = False
        if self._play_btn:
            self._play_btn.props("icon=play_arrow")
        if self._status:
            self._status.set_text("Paused")

    # -- internals -----------------------------------------------------------

    async def _tick(self) -> None:
        if not self._playing or self._in_flight:
            return
        self._in_flight = True
        try:
            data = await self._fetch()
            if not self._playing:  # stopped while the fetch was in flight
                return
            if data and self._img:
                b64 = base64.b64encode(data).decode()
                self._img.set_source(f"data:image/jpeg;base64,{b64}")
                if self._status:
                    self._status.set_text("Live ●")
            elif self._status:
                self._status.set_text("No frame — retrying…")
        except Exception as exc:  # noqa: BLE001 — surface, never crash the page
            if self._status:
                self._status.set_text(f"Snapshot error: {exc}")
        finally:
            self._in_flight = False

    def _on_visibility(self, e: object) -> None:
        visible = True
        args = getattr(e, "args", None)
        if isinstance(args, dict):
            visible = bool(args.get("visible", True))
        if not self._playing or not self._timer:
            return
        self._timer.active = visible
        if self._status:
            self._status.set_text("Live ●" if visible else "Paused (tab hidden)")
