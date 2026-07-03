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

    def test_bg_worker_stall_wiring(self, fake_nicegui: Any) -> None:
        """Web-Worker heartbeat reduces PiP-freeze detection from ~60s to ~10s (HA v13.7.5 parity).

        Chrome throttles setInterval in hidden tabs to ~1x/min; a Worker thread is
        un-throttled. The worker ticks every 5s; _liveStallTickFromWorker checks
        visibilityState, ownsPip, and frameFrozen — iOS excluded (thread-suspend
        false-positives). Worker is started with _startStallChecker and stopped with
        _stopStallChecker on every teardown path.
        """
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        js = _PLAYER_JS
        # Worker infrastructure — constructor + three methods
        assert "this._stallWorker = null" in js
        assert "Go2rtcStream.prototype._startLiveStallWorker" in js
        assert "Go2rtcStream.prototype._stopLiveStallWorker" in js
        assert "Go2rtcStream.prototype._liveStallTickFromWorker" in js
        # Worker is spawned with a Blob URL so no external script file is needed
        assert "new Blob(" in js
        assert "URL.createObjectURL" in js
        assert "URL.revokeObjectURL" in js
        assert "new Worker(url)" in js
        # Worker ticks every 5s (matches the stall-checker interval)
        assert "postMessage(0);},5000)" in js
        # Worker started/stopped alongside the setInterval stall checker
        assert "this._startLiveStallWorker();" in js
        assert "this._stopLiveStallWorker();" in js
        # Tick handler guards: hidden tab, live+not-recovering+not-stopping, ownsPip, iOS
        assert 'document.visibilityState !== "hidden"' in js
        assert "document.pictureInPictureElement === videoEl" in js
        assert "/iP(hone|ad|od)/.test(navigator.userAgent)" in js
        assert "no presented frame >10s (bg worker)" in js
        # Recovery uses the shared idempotent _recover — NOT public stop() — and
        # arms the sticky-HLS dead-track flag (parity HA v13.7.9, see
        # TestStickyHlsFallback below).
        assert '_recover("no presented frame >10s (bg worker)", true)' in js

    def test_rvfc_no_seed_before_first_frame(self, fake_nicegui: Any) -> None:
        """_boschLastFrameAt must NOT be seeded with performance.now() before first frame.

        Seeding caused false-positive stall detection during slow reconnects: the
        stall checker fired immediately after start() before any frame arrived,
        kicking off an unnecessary recovery loop. Fix: leave null until first real
        rVFC callback fires. (parity HA v13.7.5 / ioBroker)
        """
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        js = _PLAYER_JS
        # The onFrame callback still stamps the real presentation time
        assert "videoEl._boschLastFrameAt = performance.now();" in js
        # But _startRvfc must NOT seed the value before the first callback —
        # the only assignment must be INSIDE the onFrame closure, not before it.
        # We verify by checking there is exactly one occurrence of this assignment
        # and it is preceded by "var onFrame = function" (inside the closure),
        # not immediately after "this._stopRvfc(videoEl);" (the seed location).
        seed_pattern = "this._stopRvfc(videoEl);\n    var self = this;\n    videoEl._boschLastFrameAt"
        assert seed_pattern not in js, (
            "_startRvfc must NOT seed _boschLastFrameAt before the first real frame"
        )

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


class TestStickyHlsFallback:
    """Sticky-HLS after a dead WebRTC track (parity HA v13.7.9).

    HA symptom this ports: a WebRTC track can arrive (badge "Live") but never
    actually decode frames over CGNAT/5G — every recovery re-tried WebRTC,
    producing an endless VERBINDE<->LIVE flip and never settling on HLS. Fix:
    once a dead track is confirmed (rVFC freeze / bg-worker freeze / the
    track's own `mute` staying set >6s), latch a `_stickyHls` flag for the
    rest of the session so `start()` skips WebRTC and goes straight to HLS on
    every subsequent (re)connect, until the page/detail view is re-opened
    (a fresh Go2rtcStream instance).
    """

    def test_sticky_flag_initialised_false(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        assert "this._stickyHls = false;" in _PLAYER_JS

    def test_start_checks_sticky_before_attempting_webrtc(
        self, fake_nicegui: Any
    ) -> None:
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        js = _PLAYER_JS
        start_idx = js.index("Go2rtcStream.prototype.start = function")
        next_method_idx = js.index("Go2rtcStream.prototype.stop = function")
        start_body = js[start_idx:next_method_idx]
        sticky_check_idx = start_body.index("if (this._stickyHls)")
        webrtc_attempt_idx = start_body.index("this._startWebRTC(videoEl")
        # the sticky check must gate/precede the WebRTC attempt, not follow it
        assert sticky_check_idx < webrtc_attempt_idx
        # when sticky, start() goes straight to _startHLS and returns without
        # ever calling _startWebRTC
        sticky_block = start_body[sticky_check_idx:webrtc_attempt_idx]
        assert "this._startHLS(videoEl" in sticky_block
        assert "return" in sticky_block

    def test_recover_arms_sticky_on_dead_track(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        js = _PLAYER_JS
        assert "Go2rtcStream.prototype._recover = function (reason, deadTrack)" in js
        assert "if (deadTrack && !this._stickyHls) {" in js
        assert "this._stickyHls = true;" in js

    def test_dead_track_signals_pass_sticky_true(self, fake_nicegui: Any) -> None:
        """The three dead-track detections (rVFC stall-checker, bg-worker tick,
        and track-mute >6s) must call `_recover` with `deadTrack=true`."""
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        js = _PLAYER_JS
        assert (
            '_recover(frameFrozen ? "no presented frame >10s" : "stall checker ~15s", frameFrozen)'
            in js
        )
        assert '_recover("no presented frame >10s (bg worker)", true)' in js
        assert '_recover("webrtc video track muted >6s", true)' in js

    def test_generic_connection_failure_is_not_a_sticky_trigger(
        self, fake_nicegui: Any
    ) -> None:
        """A single ICE/connectionState failure alone must NOT latch sticky-HLS —
        only a confirmed dead track should (see test_dead_track_signals_pass_sticky_true)."""
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        js = _PLAYER_JS
        assert """self._recover('webrtc connectionState "failed"');""" in js


class TestHlsFatalErrorRetryCap:
    """Bounded fatal hls.js error recovery (parity HA v14.4.0 P1).

    HA symptom this ports: fatal MEDIA_ERROR recovery was unbounded (unlike
    NETWORK_ERROR, which was already capped at 3 retries) — a stuck decoder
    could retry forever instead of ever doing a full reconnect. This repo had
    NEITHER cap NOR any retry at all (a fatal error just logged a warning and
    left the stream dead) — fix adds bounded in-place retries for both fatal
    types, then a full teardown+reconnect via `_recover()` once exhausted.
    """

    def test_retry_cap_constant_is_three(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        assert "var HLS_FATAL_RETRY_MAX = 3;" in _PLAYER_JS

    def test_both_fatal_types_capped_at_same_limit(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        js = _PLAYER_JS
        assert "HlsClass.ErrorTypes.NETWORK_ERROR" in js
        assert "HlsClass.ErrorTypes.MEDIA_ERROR" in js
        # both counters gated against the SAME cap — MEDIA_ERROR is no longer
        # the unbounded one
        assert js.count("<= HLS_FATAL_RETRY_MAX") == 2
        assert "self._hlsNetworkErrorCount++;" in js
        assert "self._hlsMediaErrorCount++;" in js

    def test_in_place_retry_calls(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        js = _PLAYER_JS
        # NETWORK_ERROR retries via startLoad(), MEDIA_ERROR via recoverMediaError()
        assert "try { hls.startLoad(); } catch (e) {}" in js
        assert "try { hls.recoverMediaError(); } catch (e) {}" in js

    def test_counters_reset_on_every_new_hls_session(self, fake_nicegui: Any) -> None:
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        js = _PLAYER_JS
        start_hls_idx = js.index("Go2rtcStream.prototype._startHLS = async function")
        error_handler_idx = js.index("hls.on(HlsClass.Events.ERROR", start_hls_idx)
        reset_block = js[start_hls_idx:error_handler_idx]
        assert "this._hlsNetworkErrorCount = 0;" in reset_block
        assert "this._hlsMediaErrorCount = 0;" in reset_block

    def test_cap_exhausted_triggers_full_reconnect_not_silent_dropout(
        self, fake_nicegui: Any
    ) -> None:
        """Once retries are exhausted (or for any other fatal error type), the
        fatal error must both surface via onError AND trigger a full
        teardown+reconnect via _recover() — previously it only logged."""
        from bosch_camera_frontend.components.live_player import _PLAYER_JS

        js = _PLAYER_JS
        assert (
            'self._onError(new Error("hls.js fatal: " + data.type + "/" + data.details));'
            in js
        )
        assert 'self._recover("hls fatal " + data.type + " (retry cap reached)");' in js


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
