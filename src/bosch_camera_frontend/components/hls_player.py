"""HLS Player component — embeds an hls.js-powered video player in the page.

In Phase 1 this is a stub that shows an info message if go2rtc is not
available.  Phase 2 will wire up the actual FFmpeg→HLS pipeline.

TODO Phase 2: detect go2rtc binary (shutil.which("go2rtc")), start subprocess,
serve .m3u8 + .ts segments, pass URL to hls.js player.
TODO Phase 2: implement proxy-hash refresh loop (PUT /connection every ~50s).
TODO Phase 3: expose audio controls (mute/unmute, volume).
"""

from __future__ import annotations

import shutil

from nicegui import ui

# hls.js CDN pin — update intentionally, don't let bundler auto-update.
# Latest stable: https://github.com/video-dev/hls.js/releases
_HLS_JS_CDN = "https://cdn.jsdelivr.net/npm/hls.js@1.5.7/dist/hls.min.js"


def _go2rtc_available() -> bool:
    """Return True if go2rtc binary is on PATH."""
    return shutil.which("go2rtc") is not None


class HlsPlayer(ui.element):
    """NiceGUI element that wraps an hls.js video player.

    In Phase 1: shows an install prompt if go2rtc is missing, otherwise
    shows a placeholder telling user to enable live stream (Phase 2 impl).

    Args:
        stream_url: HLS manifest URL (.m3u8) served by go2rtc.  None = auto
                    (will be set by app when go2rtc starts).
        cam_name: Camera name for display.
    """

    def __init__(
        self,
        stream_url: str | None = None,
        cam_name: str = "",
    ) -> None:
        super().__init__("div")
        self._stream_url = stream_url
        self._cam_name = cam_name
        self._build()

    def _build(self) -> None:
        with self:
            if not _go2rtc_available():
                with ui.card().classes("bg-yellow-50 border border-yellow-300 p-4"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("warning", color="warning")
                        # TODO: use t("ui.live.go2rtc_missing") once key added
                        ui.label(
                            "Live stream requires go2rtc. "
                            "Install with: brew install go2rtc"
                        ).classes("text-sm")
                    ui.html(
                        '<a href="https://github.com/AlexxIT/go2rtc" target="_blank" '
                        'class="text-blue-600 underline text-xs">go2rtc on GitHub</a>'
                    )
                return

            if self._stream_url is None:
                with ui.card().classes("bg-gray-50 border p-4"):
                    ui.icon("videocam_off", size="2rem", color="grey")
                    # TODO Phase 2: replace with actual stream start button
                    ui.label(
                        "Live stream not yet started. "
                        "(Phase 2 will add FFmpeg→HLS pipeline)"
                    ).classes("text-sm text-gray-500")
                return

            # Actual hls.js player (used in Phase 2+)
            player_id = f"hls_player_{id(self)}"
            ui.html(f"""
<video id="{player_id}" controls muted
       style="width:100%; max-height:360px; background:#000; border-radius:4px;">
</video>
<script src="{_HLS_JS_CDN}"></script>
<script>
(function() {{
  var video = document.getElementById('{player_id}');
  if (Hls.isSupported()) {{
    var hls = new Hls({{ enableWorker: true, lowLatencyMode: true }});
    hls.loadSource('{self._stream_url}');
    hls.attachMedia(video);
  }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
    video.src = '{self._stream_url}';
  }}
}})();
</script>
""")

    def set_stream_url(self, url: str) -> None:
        """Update the stream URL and rebuild the player element."""
        self._stream_url = url
        self.clear()
        self._build()
