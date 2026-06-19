"""Tests for the LivePlayer WebRTC component (Phase C).

The realtime engine is browser-side JS and cannot be exercised headlessly; these
tests pin the Python boundary (mount wiring + opts) and assert the embedded
engine still carries the live-confirmed v13.5.17 parity markers, so a regression
in the port is caught even without a browser.
"""

from __future__ import annotations

import json
from typing import Any


class TestPlayerJsParity:
    def test_engine_carries_v13517_fixes(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        js = _PLAYER_JS
        # single accumulating MediaStream (no srcObject re-assign flash)
        assert "new MediaStream()" in js
        assert "remoteStream.addTrack" in js
        # only ICE "failed" is terminal
        assert 'iceConnectionState === "failed"' in js
        # reconnect-audio via shared AudioContext + arm-in-gesture
        assert "_sharedAudioCtx" in js
        assert "armAudioUnlock" in js
        # pause-guard never force-unmutes
        assert "_handlePause" in js
        # stall-checker
        assert "_startStallChecker" in js
        # listener cleanup on (re)attach
        assert "_detachVideoListeners" in js
        # corner-flicker fix
        assert "isolation" in js
        # WebRTC SDP exchange endpoint + HLS fallback endpoint
        assert "/api/webrtc?src=" in js
        assert "/api/stream.m3u8?src=" in js

    def test_pip_freeze_recovery_wiring(self, fake_nicegui: Any) -> None:
        """PiP-freeze-on-tab-switch recovery (parity HA v13.7.4 / ioBroker v1.7.2).

        With the live stream in Picture-in-Picture, switching the browser tab froze
        the floating window because the stall-checker setInterval is throttled in a
        hidden tab and the go2rtc WebRTC transport can die in the background. These
        pin the un-throttled, event-driven recovery wiring in the embedded engine.
        """
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        js = _PLAYER_JS
        # rVFC liveness heartbeat — fires for a PiP window even in a hidden tab
        assert "requestVideoFrameCallback" in js
        assert "_boschLastFrameAt = performance.now()" in js
        assert "cancelVideoFrameCallback" in js
        assert "_startRvfc" in js and "_stopRvfc" in js
        # stall checker escalates on a presented-frame freeze, not only .paused
        assert "var frameFrozen" in js
        assert "frozen || pausedWhileLive || frameFrozen" in js
        assert "stallCount >= 3 || frameFrozen" in js
        # WebRTC video-track mute/unmute -> debounced PiP-safe recovery
        assert "evt.track.onmute = function" in js
        assert "evt.track.onunmute = function" in js
        assert 'evt.track.kind === "video"' in js
        assert "webrtc video track muted >6s" in js
        # persistent connectionState=failed recovery (live phase)
        assert "onconnectionstatechange" in js
        assert 'connectionState === "failed"' in js
        # centralised idempotent recovery reusing the SAME <video> element
        assert "Go2rtcStream.prototype._recover" in js
        assert "this._recovering" in js

    def test_hls_pin_exact_version_and_sri(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.components.live_player import (
            _HLS_CDN_URL,
            _HLS_SRI,
            _PLAYER_JS,
        )

        assert "hls.js@1.6.16" in _HLS_CDN_URL
        assert "latest" not in _HLS_CDN_URL
        assert _HLS_SRI.startswith("sha384-")
        # the placeholders were substituted into the engine
        assert _HLS_CDN_URL in _PLAYER_JS
        assert _HLS_SRI in _PLAYER_JS
        assert "%HLS_URL%" not in _PLAYER_JS

    def test_controls_hidden_until_live(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        # audio + PiP + fullscreen are display:none while idle (parity)
        assert "reflectControls" in _PLAYER_JS
        assert 'audioBtn.style.display = live ? "" : "none";' in _PLAYER_JS
        # PiP only when the browser supports it
        assert "document.pictureInPictureEnabled" in _PLAYER_JS


class TestLivePlayerMount:
    def _capture(self, fake_nicegui: Any, monkeypatch: Any) -> dict[str, list[Any]]:
        calls: dict[str, list[Any]] = {"html": [], "head": []}
        monkeypatch.setattr(
            fake_nicegui.ui,
            "html",
            lambda *a, **k: (
                calls["html"].append(a[0] if a else None) or fake_nicegui.ui.label()
            ),
        )
        monkeypatch.setattr(
            fake_nicegui.ui,
            "add_head_html",
            lambda *a, **k: calls["head"].append(a[0] if a else None),
        )
        return calls

    def test_build_injects_engine_and_mounts(
        self, fake_nicegui: Any, monkeypatch: Any
    ) -> None:
        calls = self._capture(fake_nicegui, monkeypatch)
        from bosch_camera_frontend.components.live_player import LivePlayer

        LivePlayer(
            "http://127.0.0.1:1984",
            "bosch_terrasse",
            cam_name="Terrasse",
            audio_default=True,
        )
        # engine injected once into <head>, shared
        assert len(calls["head"]) == 1
        assert "__boschLivePlayer" in calls["head"][0]
        # two html calls: container div + mount script
        assert len(calls["html"]) == 2
        container, mount = calls["html"]
        assert container.startswith("<div id=") and 'class="w-full"' in container
        assert "__boschLivePlayer.mount(" in mount

    def test_mount_opts_carry_base_src_name_audio(
        self, fake_nicegui: Any, monkeypatch: Any
    ) -> None:
        calls = self._capture(fake_nicegui, monkeypatch)
        from bosch_camera_frontend.components.live_player import LivePlayer

        LivePlayer(
            "http://10.0.0.5:1984",
            "bosch_garten",
            cam_name="Garten",
            audio_default=False,
        )
        mount = calls["html"][1]
        # The exact json.dumps(opts) string must be embedded in the mount call.
        expected_opts = json.dumps(
            {
                "base": "http://10.0.0.5:1984",
                "src": "bosch_garten",
                "camName": "Garten",
                "audioDefault": False,
            }
        )
        assert expected_opts in mount
        # root id is json-encoded as the first mount() arg
        assert '"bosch_live_' in mount

    def test_cam_name_defaults_to_camera(
        self, fake_nicegui: Any, monkeypatch: Any
    ) -> None:
        calls = self._capture(fake_nicegui, monkeypatch)
        from bosch_camera_frontend.components.live_player import LivePlayer

        LivePlayer("http://127.0.0.1:1984", "src1")
        mount = calls["html"][1]
        assert '"camName": "Camera"' in mount or '"camName":"Camera"' in mount

    def test_script_breakout_is_escaped(
        self, fake_nicegui: Any, monkeypatch: Any
    ) -> None:
        calls = self._capture(fake_nicegui, monkeypatch)
        from bosch_camera_frontend.components.live_player import LivePlayer

        LivePlayer(
            "http://127.0.0.1:1984",
            "src1",
            cam_name="Cam</script><img src=x onerror=alert(1)>",
        )
        mount = calls["html"][1]
        # the injected break-out payload must NOT survive unescaped (the wrapper's
        # own trailing </script> is fine; the camera-name one must be neutralised)
        assert "</script><img" not in mount
        assert "<\\/script><img" in mount
