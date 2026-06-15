"""LivePlayer — real WebRTC/HLS live video for the NiceGUI frontend (Phase C).

This is the go2rtc-backed player that brings the frontend to HA-card / ioBroker-
widget level: WebRTC first, automatic HLS fallback, audio toggle, Picture-in-
Picture and fullscreen. The browser-side engine is a framework-free port of the
LIVE-CONFIRMED ioBroker ``Go2rtcStream`` (``src-widgets/src/lib/go2rtc.js``) with
every v13.5.17 fix already baked in:

* single accumulating ``pc.ontrack`` MediaStream (no srcObject re-assign flash)
* only ICE ``failed`` is terminal (``disconnected`` is a transient blip)
* reconnect keeps sound via a shared AudioContext unlocked in the first gesture
* pause-guard never sets ``muted=false`` itself (Chrome would re-mute/freeze)
* stall-checker nudges a silently-paused live ``<video>`` back
* listener cleanup on every (re)attach so closures don't leak
* ``isolation: isolate`` + per-child ``border-radius`` (no corner flicker)
* audio + PiP controls hidden until the stream is actually live

The Python side just resolves the go2rtc URLs (via :class:`Go2rtcManager`) and
mounts the player; the browser engine owns the realtime path. Because this
requires a running go2rtc + a reachable camera + a browser, it cannot be
exercised headlessly — it is parity-verified against the live ioBroker player
and unit-tested at the Python boundary (see docs/live-webrtc-plan.md § Testing).
"""

from __future__ import annotations

import json

from nicegui import ui

# hls.js CDN pin (exact version + SRI) — identical to the ioBroker/HA player so
# the fallback path is byte-for-byte the live-confirmed one. Update deliberately.
_HLS_CDN_URL = "https://cdn.jsdelivr.net/npm/hls.js@1.6.16/dist/hls.min.js"
_HLS_SRI = "sha384-5E8B0pTlZZJMabWpC0fyYf6OUpe15jJij34BqBAh4NXoHAlLNOjCPRrwtOXOQFAn"

# The whole browser engine, injected ONCE per page (guarded by a window flag).
# Ported from the live-confirmed ioBroker Go2rtcStream; the trailing
# mountBoschLivePlayer() builds a standalone control bar around it.
_PLAYER_JS = (
    (
        """
<script>
(function () {
  if (window.__boschLivePlayer) { return; }

  var HLS_CDN_URL = "%HLS_URL%";
  var HLS_SRI = "%HLS_SRI%";
  var _hlsLoadPromise = null;
  var _sharedAudioCtx = null;

  function isRemoteSession() {
    var host = window.location.hostname;
    if (host === "localhost" || host === "127.0.0.1") { return false; }
    if (host.endsWith(".local")) { return false; }
    if (/^192\\.168\\./.test(host)) { return false; }
    if (/^10\\./.test(host)) { return false; }
    if (/^172\\.(1[6-9]|2\\d|3[01])\\./.test(host)) { return false; }
    return true;
  }

  function loadHlsJs() {
    if (_hlsLoadPromise) { return _hlsLoadPromise; }
    _hlsLoadPromise = new Promise(function (resolve, reject) {
      if (window.Hls) { resolve(window.Hls); return; }
      var script = document.createElement("script");
      script.src = HLS_CDN_URL;
      script.integrity = HLS_SRI;
      script.crossOrigin = "anonymous";
      script.onload = function () {
        if (window.Hls) { resolve(window.Hls); }
        else { reject(new Error("hls.js loaded but window.Hls undefined")); }
      };
      script.onerror = function () { reject(new Error("Failed to load hls.js")); };
      document.head.appendChild(script);
    });
    return _hlsLoadPromise;
  }

  function armAudioUnlock() {
    if (!_sharedAudioCtx) {
      try { _sharedAudioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
      catch (e) { return; }
    }
    _sharedAudioCtx.resume().catch(function () {});
  }

  // ---- Go2rtcStream (framework-free port of the live-confirmed ioBroker lib) -
  function Go2rtcStream(opts) {
    this._baseUrl = (opts.baseUrl || "").replace(/\\/$/, "");
    this._src = opts.src || "";
    this._onPhase = opts.onPhase || function () {};
    this._onError = opts.onError || function () {};
    this._transport = null;
    this._pc = null;
    this._hls = null;
    this._videoEl = null;
    this._stopping = false;
    this._live = false;
    this._onPlaying = null;
    this._onPause = null;
    this._hlsKeepalive = null;
    this._stallChecker = null;
  }

  Go2rtcStream.prototype.start = function (videoEl, o) {
    o = o || {};
    var wantAudio = !!o.wantAudio;
    var armed = !!o.armed;
    this._stopping = false;
    this._videoEl = videoEl;
    var effectivelyArmed =
      armed || !!(wantAudio && _sharedAudioCtx && _sharedAudioCtx.state === "running");
    videoEl.muted = !(wantAudio && effectivelyArmed);
    this._onPhase("connecting", null);
    var webrtcTimeout = isRemoteSession() ? 2500 : 5000;
    var self = this;
    return this._startWebRTC(videoEl, wantAudio, effectivelyArmed, webrtcTimeout)
      .catch(function (webrtcErr) {
        if (self._stopping) { return; }
        console.warn("[bosch-live] WebRTC failed, HLS fallback:", webrtcErr.message);
        self._cleanupWebRTC();
        return self._startHLS(videoEl, wantAudio, effectivelyArmed).catch(function (hlsErr) {
          if (self._stopping) { return; }
          self._onPhase("error", null);
          self._onError(hlsErr);
        });
      });
  };

  Go2rtcStream.prototype.stop = function () {
    this._stopping = true;
    this._live = false;
    this._detachVideoListeners();
    this._cleanupWebRTC();
    this._cleanupHLS();
    if (this._videoEl) {
      this._videoEl.srcObject = null;
      this._videoEl.src = "";
      this._videoEl.load();
    }
    this._transport = null;
    this._onPhase("idle", null);
  };

  Go2rtcStream.prototype.isLive = function () { return this._live; };

  Go2rtcStream.prototype._startWebRTC = function (videoEl, wantAudio, armed, timeoutMs) {
    var self = this;
    return new Promise(function (resolve, reject) {
      var settled = false;
      var timer = setTimeout(function () {
        if (!settled) { settled = true; reject(new Error("WebRTC ICE timeout " + timeoutMs)); }
      }, timeoutMs);
      function settle(fn, val) {
        if (settled) { return; }
        settled = true; clearTimeout(timer); fn(val);
      }
      var pc;
      try {
        pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
        self._pc = pc;
      } catch (e) { return settle(reject, e); }
      pc.addTransceiver("video", { direction: "recvonly" });
      pc.addTransceiver("audio", { direction: "recvonly" });
      var remoteStream = new MediaStream();
      pc.ontrack = function (evt) {
        if (self._stopping) { return; }
        remoteStream.addTrack(evt.track);
        if (videoEl.srcObject !== remoteStream) { videoEl.srcObject = remoteStream; }
      };
      pc.oniceconnectionstatechange = function () {
        if (pc.iceConnectionState === "failed") { settle(reject, new Error("ICE failed")); }
      };
      (async function () {
        try {
          var offer = await pc.createOffer();
          await pc.setLocalDescription(offer);
          await self._waitIceGathering(pc);
          if (self._stopping) { settle(reject, new Error("stopped")); return; }
          var localDesc = pc.localDescription;
          var resp = await fetch(
            self._baseUrl + "/api/webrtc?src=" + encodeURIComponent(self._src),
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ type: localDesc.type, sdp: localDesc.sdp }),
            }
          );
          if (!resp.ok) { throw new Error("go2rtc WebRTC HTTP " + resp.status); }
          var answer = await resp.json();
          await pc.setRemoteDescription(new RTCSessionDescription(answer));
        } catch (e) { settle(reject, e); return; }
        self._transport = "webrtc";
        self._attachVideoListeners(videoEl, wantAudio, armed, function () { settle(resolve); });
      })();
    });
  };

  Go2rtcStream.prototype._waitIceGathering = function (pc) {
    return new Promise(function (resolve) {
      if (pc.iceGatheringState === "complete") { resolve(); return; }
      pc.onicegatheringstatechange = function () {
        if (pc.iceGatheringState === "complete") { pc.onicegatheringstatechange = null; resolve(); }
      };
      setTimeout(function () { pc.onicegatheringstatechange = null; resolve(); }, 4000);
    });
  };

  Go2rtcStream.prototype._cleanupWebRTC = function () {
    if (this._pc) { try { this._pc.close(); } catch (e) {} this._pc = null; }
  };

  Go2rtcStream.prototype._startHLS = async function (videoEl, wantAudio, armed) {
    this._transport = "hls";
    var hlsUrl = this._baseUrl + "/api/stream.m3u8?src=" + encodeURIComponent(this._src);
    var HlsClass = null;
    try { HlsClass = await loadHlsJs(); } catch (e) {}
    var self = this;
    if (HlsClass && HlsClass.isSupported()) {
      var hls = new HlsClass({
        lowLatencyMode: true, liveSyncDurationCount: 4, liveMaxLatencyDurationCount: 8,
        maxBufferLength: 14, maxMaxBufferLength: 22,
      });
      this._hls = hls;
      hls.on(HlsClass.Events.ERROR, function (_evt, data) {
        if (self._stopping) { return; }
        if (data.fatal) { self._onError(new Error("hls.js fatal: " + data.type + "/" + data.details)); }
      });
      hls.loadSource(hlsUrl);
      hls.attachMedia(videoEl);
      this._hlsKeepalive = setInterval(function () {
        if (!self._stopping && self._hls) { try { self._hls.startLoad(-1); } catch (e) {} }
      }, 20000);
      this._attachVideoListeners(videoEl, wantAudio, armed, function () {});
      return;
    }
    if (videoEl.canPlayType("application/vnd.apple.mpegurl")) {
      videoEl.src = hlsUrl;
      this._attachVideoListeners(videoEl, wantAudio, armed, function () {});
      videoEl.load();
      try { await videoEl.play(); }
      catch (e) { videoEl.muted = true; try { await videoEl.play(); } catch (e2) {} }
      return;
    }
    throw new Error("HLS not supported");
  };

  Go2rtcStream.prototype._cleanupHLS = function () {
    clearInterval(this._hlsKeepalive); this._hlsKeepalive = null;
    if (this._hls) { try { this._hls.destroy(); } catch (e) {} this._hls = null; }
  };

  Go2rtcStream.prototype._attachVideoListeners = function (videoEl, wantAudio, armed, onFirstPlaying) {
    this._detachVideoListeners();
    var self = this;
    var firstPlay = true;
    this._onPlaying = function () {
      if (self._stopping) { return; }
      self._live = true;
      self._onPhase("live", self._transport);
      if (firstPlay) {
        firstPlay = false;
        onFirstPlaying();
        if (armed && wantAudio) {
          videoEl.muted = false;
          if (videoEl.paused) {
            videoEl.play().catch(function () { videoEl.muted = true; videoEl.play().catch(function () {}); });
          }
        }
      }
    };
    this._onPause = function () { self._handlePause(); };
    videoEl.addEventListener("playing", this._onPlaying);
    videoEl.addEventListener("pause", this._onPause);
    this._startStallChecker(videoEl);
  };

  Go2rtcStream.prototype._detachVideoListeners = function () {
    this._stopStallChecker();
    if (this._videoEl) {
      if (this._onPlaying) { this._videoEl.removeEventListener("playing", this._onPlaying); }
      if (this._onPause) { this._videoEl.removeEventListener("pause", this._onPause); }
    }
  };

  Go2rtcStream.prototype._startStallChecker = function (videoEl) {
    this._stopStallChecker();
    var self = this;
    this._stallChecker = setInterval(function () {
      if (self._stopping || !self._live || !videoEl) { self._stopStallChecker(); return; }
      if (videoEl.paused) { videoEl.play().catch(function () {}); }
    }, 5000);
  };

  Go2rtcStream.prototype._stopStallChecker = function () {
    if (this._stallChecker) { clearInterval(this._stallChecker); this._stallChecker = null; }
  };

  Go2rtcStream.prototype._handlePause = function () {
    if (this._stopping) { return; }
    var video = this._videoEl;
    if (!video) { return; }
    if (!video.muted) {
      video.play().catch(function () { video.muted = true; video.play().catch(function () {}); });
    } else {
      video.play().catch(function () {});
    }
  };

  // ---- standalone control bar + mount --------------------------------------
  function mountBoschLivePlayer(rootId, opts) {
    var root = document.getElementById(rootId);
    if (!root || root.__boschMounted) { return; }
    root.__boschMounted = true;
    opts = opts || {};
    var camName = opts.camName || "Camera";
    var wantAudioDefault = !!opts.audioDefault;

    root.style.position = "relative";
    root.style.isolation = "isolate";  // flatten layers → no corner flicker

    var video = document.createElement("video");
    video.playsInline = true; video.muted = true; video.setAttribute("playsinline", "");
    video.style.cssText =
      "width:100%;max-height:360px;background:#000;border-radius:8px;display:block;object-fit:contain;";
    root.appendChild(video);

    var bar = document.createElement("div");
    bar.style.cssText =
      "display:flex;gap:6px;align-items:center;padding:6px 2px;flex-wrap:wrap;";
    root.appendChild(bar);

    function mkBtn(label, title) {
      var b = document.createElement("button");
      b.textContent = label; b.title = title;
      b.style.cssText =
        "border:0;border-radius:16px;padding:4px 12px;cursor:pointer;" +
        "background:rgba(0,0,0,.06);font-size:13px;";
      bar.appendChild(b); return b;
    }
    var playBtn = mkBtn("▶ Live", "Play / stop");
    var audioBtn = mkBtn("🔇", "Mute / unmute");
    var pipBtn = mkBtn("⧉ PiP", "Picture in Picture");
    var fsBtn = mkBtn("⛶ Full", "Fullscreen");
    var status = document.createElement("span");
    status.style.cssText = "font-size:12px;color:#888;margin-left:4px;";
    status.textContent = "Press play";
    bar.appendChild(status);

    var wantAudio = wantAudioDefault;
    var live = false;

    // Audio + PiP are meaningless until a live stream exists → hide while idle
    // (HA v13.5.17 parity: stream-contextual controls hidden, not just greyed).
    function reflectControls() {
      audioBtn.style.display = live ? "" : "none";
      pipBtn.style.display = (live && document.pictureInPictureEnabled) ? "" : "none";
      fsBtn.style.display = live ? "" : "none";
      audioBtn.textContent = video.muted ? "🔇" : "🔊";
    }
    reflectControls();

    var stream = new Go2rtcStream({
      baseUrl: opts.base, src: opts.src,
      onPhase: function (phase, transport) {
        live = (phase === "live");
        if (phase === "connecting") { status.textContent = "Connecting…"; }
        else if (phase === "live") { status.textContent = "Live ● " + (transport || ""); }
        else if (phase === "error") { status.textContent = "Stream error"; }
        else { status.textContent = "Stopped"; }
        playBtn.textContent = live ? "■ Stop" : "▶ Live";
        reflectControls();
      },
      onError: function (err) { console.warn("[bosch-live]", err && err.message); },
    });

    var started = false;
    function startStream(armed) {
      started = true;
      stream.start(video, { wantAudio: wantAudio, armed: armed });
    }
    function stopStream() {
      started = false;
      stream.stop();
    }

    playBtn.addEventListener("click", function () {
      // resume AudioContext synchronously in the gesture so a later unmute is allowed
      if (wantAudio) { armAudioUnlock(); }
      if (started && live) { stopStream(); }
      else { startStream(true); }
    });

    audioBtn.addEventListener("click", function () {
      // Unmute MUST happen inside the gesture (Chrome autoplay policy).
      armAudioUnlock();
      wantAudio = video.muted;        // toggling toward unmuted = want audio
      video.muted = !video.muted;
      if (!video.muted && video.paused) { video.play().catch(function () {}); }
      reflectControls();
    });

    pipBtn.addEventListener("click", function () {
      if (!document.pictureInPictureEnabled) { return; }
      if (document.pictureInPictureElement) {
        document.exitPictureInPicture().catch(function () {});
      } else {
        try {
          if ("mediaSession" in navigator) {
            navigator.mediaSession.metadata = new MediaMetadata({ title: camName });
          }
        } catch (e) {}
        video.requestPictureInPicture().catch(function () {});
      }
    });

    fsBtn.addEventListener("click", function () {
      if (document.fullscreenElement) { document.exitFullscreen().catch(function () {}); }
      else { root.requestFullscreen().catch(function () {}); }
    });

    // Lifecycle recovery: a bfcache restore / tab re-show can leave a dead
    // <video>. If we were live, re-start (go2rtc gives a fresh session).
    function recover() {
      if (started && document.visibilityState === "visible" && video.paused) {
        stream.stop(); startStream(_sharedAudioCtx && _sharedAudioCtx.state === "running");
      }
    }
    window.addEventListener("pageshow", function (e) { if (e.persisted) { recover(); } });
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") { recover(); }
    });

    root.__boschPlayer = { start: startStream, stop: stopStream };
  }

  window.__boschLivePlayer = { mount: mountBoschLivePlayer, Go2rtcStream: Go2rtcStream };
})();
</script>
"""
    )
    .replace("%HLS_URL%", _HLS_CDN_URL)
    .replace("%HLS_SRI%", _HLS_SRI)
)


class LivePlayer(ui.element):
    """go2rtc WebRTC/HLS live player element.

    Args:
        webrtc_base: go2rtc base URL (e.g. ``http://127.0.0.1:1984``) — from
            :pyattr:`Go2rtcManager.base_url`.
        src_name: the registered go2rtc stream name (the ``?src=`` value).
        cam_name: camera display name (used for the PiP / Media-Session title).
        audio_default: start with audio wanted (still muted until a user gesture).
    """

    def __init__(
        self,
        webrtc_base: str,
        src_name: str,
        cam_name: str = "",
        audio_default: bool = False,
    ) -> None:
        super().__init__("div")
        self._base = webrtc_base
        self._src = src_name
        self._cam_name = cam_name or "Camera"
        self._audio_default = audio_default
        self._build()

    def _build(self) -> None:
        # Inject the engine once per page (window-flag guarded inside the script).
        ui.add_head_html(_PLAYER_JS, shared=True)
        root_id = f"bosch_live_{id(self)}"
        with self:
            ui.html(f'<div id="{root_id}" class="w-full"></div>', sanitize=False)
        opts = {
            "base": self._base,
            "src": self._src,
            "camName": self._cam_name,
            "audioDefault": self._audio_default,
        }
        # Escape "</" → "<\/" so a camera name containing "</script>" can't break
        # out of the inline <script> block (json.dumps does not escape '/').
        root_js = json.dumps(root_id).replace("</", "<\\/")
        opts_js = json.dumps(opts).replace("</", "<\\/")
        # Mount after the container exists in the DOM.
        ui.html(
            "<script>(function(){function m(){"
            "if(window.__boschLivePlayer){"
            f"window.__boschLivePlayer.mount({root_js},{opts_js});"
            "}else{setTimeout(m,50);}}m();})();</script>",
            sanitize=False,
        )
