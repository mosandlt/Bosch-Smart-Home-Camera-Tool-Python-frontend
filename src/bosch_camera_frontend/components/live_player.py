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
  // Bounded fatal hls.js error recovery (parity HA v14.4.0 P1): NETWORK_ERROR
  // and MEDIA_ERROR each get this many in-place hls.js retries before we give
  // up on patching the same session and do a full teardown+reconnect instead.
  var HLS_FATAL_RETRY_MAX = 3;

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
    this._trackMuteTimer = null;
    this._rvfcHandle = null;
    this._recovering = false;
    this._stallWorker = null;
    // Sticky-HLS (parity HA v13.7.9): once a dead WebRTC track is detected
    // (track "live" but no frames ever decode — CGNAT/5G), we fall back to
    // HLS and latch this flag for the rest of the session so subsequent
    // recoveries never retry WebRTC again, breaking the endless
    // VERBINDE<->LIVE flip loop. Cleared only by creating a new Go2rtcStream
    // (page reload / camera-detail re-open).
    this._stickyHls = false;
    this._hlsNetworkErrorCount = 0;
    this._hlsMediaErrorCount = 0;
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
    var self = this;
    // Sticky-HLS (parity HA v13.7.9): a prior dead-track detection this
    // session means WebRTC is known-bad on this network path — skip straight
    // to HLS instead of re-running the same flip that caused the freeze.
    if (this._stickyHls) {
      console.warn("[bosch-live] sticky HLS active this session, skipping WebRTC");
      return this._startHLS(videoEl, wantAudio, effectivelyArmed).catch(function (hlsErr) {
        if (self._stopping) { return; }
        self._onPhase("error", null);
        self._onError(hlsErr);
      });
    }
    var webrtcTimeout = isRemoteSession() ? 2500 : 5000;
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
        if (videoEl.srcObject !== remoteStream) { videoEl.srcObject = remoteStream; self._startRvfc(videoEl); }
        // PiP-freeze fix (parity HA v13.7.4): when go2rtc stops delivering media
        // (background-tab WebSocket i/o timeout) Chrome fires `mute` on the remote
        // track — an EVENT, so it arrives even while the tab is hidden and the
        // stall-checker setInterval is throttled. Debounce 6s then recover.
        if (evt.track.kind === "video") {
          evt.track.onunmute = function () {
            if (self._trackMuteTimer) { clearTimeout(self._trackMuteTimer); self._trackMuteTimer = null; }
          };
          evt.track.onmute = function () {
            if (self._stopping || !self._live) { return; }
            if (self._trackMuteTimer) { clearTimeout(self._trackMuteTimer); }
            self._trackMuteTimer = setTimeout(function () {
              self._trackMuteTimer = null;
              // deadTrack=true: the track itself went dark — sticky-HLS trigger.
              if (evt.track.muted && self._live && !self._stopping) { self._recover("webrtc video track muted >6s", true); }
            }, 6000);
          };
        }
      };
      pc.oniceconnectionstatechange = function () {
        if (pc.iceConnectionState === "failed") { settle(reject, new Error("ICE failed")); }
      };
      // Live-phase transport-failure recovery (parity HA v13.7.4): the listener
      // above only settles the INITIAL connect; once live a `failed` aggregate
      // connection state means the transport died — recover PiP-safely.
      pc.onconnectionstatechange = function () {
        if (self._pc !== pc || !self._live || self._stopping) { return; }
        if (pc.connectionState === "failed") { self._recover('webrtc connectionState "failed"'); }
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
    // Fresh retry budget for every new HLS session (initial start AND every
    // reconnect via _recover() re-enters here through start()).
    this._hlsNetworkErrorCount = 0;
    this._hlsMediaErrorCount = 0;
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
      // Bounded fatal-error recovery (parity HA v14.4.0 P1): NETWORK_ERROR and
      // MEDIA_ERROR each get up to HLS_FATAL_RETRY_MAX in-place hls.js retries
      // (startLoad() / recoverMediaError()) before we give up patching this
      // hls.js instance and do a full teardown+reconnect via _recover() —
      // previously MEDIA_ERROR had no cap at all (nor any retry), so a single
      // fatal error left the stream dead with only a console warning.
      hls.on(HlsClass.Events.ERROR, function (_evt, data) {
        if (self._stopping) { return; }
        if (!data.fatal) { return; }
        if (data.type === HlsClass.ErrorTypes.NETWORK_ERROR) {
          self._hlsNetworkErrorCount++;
          if (self._hlsNetworkErrorCount <= HLS_FATAL_RETRY_MAX) {
            console.warn(
              "[bosch-live] hls.js fatal NETWORK_ERROR, retry " +
              self._hlsNetworkErrorCount + "/" + HLS_FATAL_RETRY_MAX
            );
            try { hls.startLoad(); } catch (e) {}
            return;
          }
        } else if (data.type === HlsClass.ErrorTypes.MEDIA_ERROR) {
          self._hlsMediaErrorCount++;
          if (self._hlsMediaErrorCount <= HLS_FATAL_RETRY_MAX) {
            console.warn(
              "[bosch-live] hls.js fatal MEDIA_ERROR, retry " +
              self._hlsMediaErrorCount + "/" + HLS_FATAL_RETRY_MAX
            );
            try { hls.recoverMediaError(); } catch (e) {}
            return;
          }
        }
        self._onError(new Error("hls.js fatal: " + data.type + "/" + data.details));
        self._recover("hls fatal " + data.type + " (retry cap reached)");
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
    this._stopRvfc(this._videoEl);
    if (this._trackMuteTimer) { clearTimeout(this._trackMuteTimer); this._trackMuteTimer = null; }
    if (this._videoEl) {
      if (this._onPlaying) { this._videoEl.removeEventListener("playing", this._onPlaying); }
      if (this._onPause) { this._videoEl.removeEventListener("pause", this._onPause); }
    }
  };

  Go2rtcStream.prototype._startStallChecker = function (videoEl) {
    this._stopStallChecker();
    this._startLiveStallWorker();
    var self = this;
    var lastTime = 0;
    var stallCount = 0;
    this._stallChecker = setInterval(function () {
      if (self._stopping || !self._live || !videoEl) { self._stopStallChecker(); return; }
      // Presented-frame freeze (rVFC, parity HA v13.7.4): _boschLastFrameAt keeps
      // updating for a PiP window in a hidden tab and STOPS the instant frames
      // freeze — an un-throttled signal the throttled currentTime poll can't give.
      var frameFrozen =
        videoEl._boschLastFrameAt != null && (performance.now() - videoEl._boschLastFrameAt) > 10000;
      var frozen = videoEl.currentTime === lastTime;
      var pausedWhileLive = videoEl.paused;
      if (frozen || pausedWhileLive || frameFrozen) {
        if (videoEl.paused) { videoEl.play().catch(function () {}); }
        stallCount++;
        if (stallCount >= 3 || frameFrozen) {
          stallCount = 0;
          // frameFrozen (rVFC-based, WebRTC-only signal) = dead track → sticky-HLS.
          // A plain currentTime/paused stall can happen on either transport and
          // is not itself proof WebRTC is unusable, so it stays non-sticky.
          self._recover(frameFrozen ? "no presented frame >10s" : "stall checker ~15s", frameFrozen);
        }
      } else {
        stallCount = 0;
      }
      lastTime = videoEl.currentTime;
    }, 5000);
  };

  Go2rtcStream.prototype._stopStallChecker = function () {
    if (this._stallChecker) { clearInterval(this._stallChecker); this._stallChecker = null; }
    this._stopLiveStallWorker();
  };

  Go2rtcStream.prototype._startLiveStallWorker = function () {
    this._stopLiveStallWorker();
    if (typeof Worker !== "function") { return; }
    try {
      var src = "let t=setInterval(function(){postMessage(0);},5000);"
        + "onmessage=function(e){if(e.data==='stop'){clearInterval(t);close();}};";
      var blob = new Blob([src], { type: "application/javascript" });
      var url = URL.createObjectURL(blob);
      var self = this;
      this._stallWorker = new Worker(url);
      URL.revokeObjectURL(url);
      this._stallWorker.onmessage = function () { self._liveStallTickFromWorker(); };
      this._stallWorker.onerror = function () { self._stopLiveStallWorker(); };
    } catch (e) { this._stallWorker = null; }
  };

  Go2rtcStream.prototype._stopLiveStallWorker = function () {
    if (this._stallWorker) {
      try { this._stallWorker.postMessage("stop"); } catch (e) {}
      try { this._stallWorker.terminate(); } catch (e) {}
      this._stallWorker = null;
    }
  };

  Go2rtcStream.prototype._liveStallTickFromWorker = function () {
    if (document.visibilityState !== "hidden") { return; }
    if (!this._live || this._recovering || this._stopping) { return; }
    var videoEl = this._videoEl;
    if (!videoEl) { return; }
    var ownsPip = document.pictureInPictureElement === videoEl;
    if (!ownsPip) { return; }
    var isIOS = /iP(hone|ad|od)/.test(navigator.userAgent);
    var frameFrozen = videoEl._boschLastFrameAt != null
      && (performance.now() - videoEl._boschLastFrameAt) > 10000;
    if (frameFrozen && !isIOS) { this._recover("no presented frame >10s (bg worker)", true); }
  };

  // rVFC liveness heartbeat: stamp _boschLastFrameAt on every PRESENTED frame.
  // Re-arms while live; cancelled in _detachVideoListeners. The stall checker
  // reads it to catch a freeze even in a hidden-tab PiP. (Parity HA v13.7.4.)
  Go2rtcStream.prototype._startRvfc = function (videoEl) {
    if (typeof videoEl.requestVideoFrameCallback !== "function") { return; }
    this._stopRvfc(videoEl);
    var self = this;
    var onFrame = function () {
      videoEl._boschLastFrameAt = performance.now();
      if (self._live && !self._stopping && videoEl.srcObject) {
        self._rvfcHandle = videoEl.requestVideoFrameCallback(onFrame);
      } else {
        self._rvfcHandle = null;
      }
    };
    this._rvfcHandle = videoEl.requestVideoFrameCallback(onFrame);
  };

  Go2rtcStream.prototype._stopRvfc = function (videoEl) {
    var el = videoEl || this._videoEl;
    if (this._rvfcHandle != null && el && typeof el.cancelVideoFrameCallback === "function") {
      try { el.cancelVideoFrameCallback(this._rvfcHandle); } catch (e) {}
    }
    this._rvfcHandle = null;
    if (el) { el._boschLastFrameAt = null; }
  };

  // Idempotent, PiP-safe live-stream recovery. Called by the stall checker AND by
  // the WebRTC track-`mute` / connection-`failed` handlers (events, not throttled
  // timers — they fire while the tab is hidden). Tears the dead transport down but
  // keeps the SAME <video> (so any PiP window survives) and re-starts on it after a
  // short delay — the fresh srcObject flows back into the floating window with no
  // user gesture. Guarded by _recovering. (Parity HA v13.7.4.)
  Go2rtcStream.prototype._recover = function (reason, deadTrack) {
    if (this._stopping || this._recovering || !this._live || !this._videoEl) { return; }
    console.warn("[bosch-live] live recovery (" + reason + ")");
    // Sticky-HLS (parity HA v13.7.9): a confirmed dead WebRTC track (frames
    // never decode, or the track itself muted for good) means retrying
    // WebRTC again would just re-enter the same freeze — latch HLS for the
    // rest of this session instead of flip-flopping forever.
    if (deadTrack && !this._stickyHls) {
      this._stickyHls = true;
      console.warn("[bosch-live] dead WebRTC track detected, sticking to HLS for this session");
    }
    this._recovering = true;
    var self = this;
    var videoEl = this._videoEl;
    var wantAudio = !videoEl.muted;
    this._detachVideoListeners();
    this._cleanupWebRTC();
    this._cleanupHLS();
    this._live = false;
    setTimeout(function () {
      self._recovering = false;
      if (self._stopping || !self._videoEl) { return; }
      Promise.resolve(self.start(videoEl, { wantAudio: wantAudio, armed: false })).catch(function () {});
    }, 2000);
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
