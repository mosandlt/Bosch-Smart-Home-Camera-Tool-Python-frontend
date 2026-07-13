"""NVRManager — continuous local Mini-NVR recording, one manager for the whole app.

Sibling pattern to :mod:`go2rtc_manager` (module-level singleton, ``atexit`` +
``SIGTERM`` teardown, sync core with ``async_*`` twins offloaded via
``asyncio.to_thread`` for NiceGUI callers). Where ``Go2rtcManager`` owns ONE
shared subprocess for the whole app, ``NVRManager`` owns ZERO-OR-MORE per-camera
ffmpeg segmenter subprocesses, keyed by stream name.

Scope (Phase 1 — see docs/family-parity-plan.md for the full Mini-NVR concept
ported from the HA sibling repo's ``custom_components/bosch_shc_camera/recorder.py``):

* ``continuous`` mode ONLY. One long-running ``ffmpeg -f segment`` process per
  camera writes rolling N-second MP4 segments straight to disk (``-c copy``, no
  transcode) — ffmpeg's own segment muxer rotates files internally, so the
  process does NOT need to be restarted on a timer.
* ``event_buffered`` (tmpfs ring-buffer writer + motion/person-triggered
  clip assembly with pre-/post-roll) is intentionally NOT implemented here.
  This frontend has no motion/person event consumer yet (no FCM push listener,
  unlike the HA integration) — there is nothing to trigger clip assembly on.
  TODO(nvr-event-buffered): once an event source exists, port the ring-buffer
  + assemble-on-event approach, reusing this module's crash-restart watcher
  for the ring-writer process.

Credential rotation: Gen2 cameras rotate Digest creds on every
``PUT /connection`` (i.e. every call to ``cli_bridge.get_stream_url``). A
freshly resolved URL is used to spawn each ffmpeg process, but the process is
**never proactively restarted just because creds rotated** — an already-open
RTSP session survives rotation (same reasoning as the HA sibling repo's
v14.5.4 fix: heartbeat-driven cred rotation is not a reason to kill a live
session). The URL is only re-resolved when the *process itself* needs
restarting (initial start, or a genuine ffmpeg crash) — never cached across
restarts, since a stale URL/creds would just make the respawn fail again.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import types
from collections.abc import Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)

# ffmpeg segment length. Mirrors the HA sibling repo's continuous-mode default
# (5-minute MP4 segments) — see CLAUDE.md HA v14.6.x/v14.7.x recorder notes.
DEFAULT_SEGMENT_SECONDS = 300

# Crash-restart backoff (seconds between a dead ffmpeg process and the next
# spawn attempt). Doubles on consecutive fast exits, capped, to avoid
# hammering the camera/network on a persistent fault.
_RESTART_BACKOFF_BASE = 5.0
_RESTART_BACKOFF_CAP = 60.0
# A restart is considered "fast" (crash-loop) if the process died before
# running this long — escalates backoff instead of resetting it.
_MIN_CLEAN_RUNTIME_SECONDS = 30.0

StreamResolver = Callable[[], "dict[str, Any] | None"]


class _CameraRecorder:
    """Owns one camera's continuous-recording ffmpeg process + watcher thread."""

    def __init__(
        self,
        name: str,
        resolver: StreamResolver,
        output_dir: str,
        ffmpeg_binary: str,
        segment_seconds: int,
    ) -> None:
        self.name = name
        self._resolver = resolver
        self._output_dir = output_dir
        self._ffmpeg_binary = ffmpeg_binary
        self._segment_seconds = segment_seconds
        self._lock = threading.RLock()  # guards _proc mutation
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: "subprocess.Popen[bytes] | None" = None
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Spawn the watcher thread. Idempotent — no-op if already running."""
        with self._lock:
            if self.running:
                return True
            self._stop_event.clear()
            self.last_error = None
            self._thread = threading.Thread(
                target=self._run, name=f"nvr-recorder-{self.name}", daemon=True
            )
            self._thread.start()
        return True

    def stop(self) -> None:
        """Stop the watcher thread and terminate any live ffmpeg process.

        Safe to call repeatedly / on an already-stopped recorder.
        """
        with self._lock:
            self._stop_event.set()
            proc = self._proc
        self._terminate(proc)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=10)
        with self._lock:
            self._proc = None
            self._thread = None

    @staticmethod
    def _terminate(proc: "subprocess.Popen[bytes] | None") -> None:
        """Best-effort terminate (then kill on timeout) a possibly-None proc."""
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except OSError:
            pass

    # ── watcher loop ─────────────────────────────────────────────────────
    def _run(self) -> None:
        """Resolve → spawn → block on exit → (maybe) restart. Runs off-thread.

        Only exits the loop when ``_stop_event`` is set (by :meth:`stop`).
        Every iteration re-resolves the stream URL — see module docstring on
        why creds are never cached across a restart.
        """
        consecutive_fast_exits = 0
        while not self._stop_event.is_set():
            started_at = time.monotonic()
            proc = self._spawn_once()
            if proc is None:
                # resolve/mkdir/spawn failure already recorded in last_error
                if self._stop_event.wait(_RESTART_BACKOFF_BASE):
                    return
                continue

            with self._lock:
                # A concurrent stop() may have run its terminate-check between
                # our spawn (above, outside the lock — resolving+Popen can
                # take a while) and this point. If so, nobody else will ever
                # terminate this freshly spawned process — do it ourselves
                # instead of handing it to proc.wait() and leaking an
                # untracked, never-terminated ffmpeg child.
                already_stopped = self._stop_event.is_set()
                if not already_stopped:
                    self._proc = proc
            if already_stopped:
                self._terminate(proc)
                return
            proc.wait()
            with self._lock:
                self._proc = None

            if self._stop_event.is_set():
                return

            runtime = time.monotonic() - started_at
            if runtime < _MIN_CLEAN_RUNTIME_SECONDS:
                consecutive_fast_exits += 1
            else:
                consecutive_fast_exits = 0
            backoff = min(
                _RESTART_BACKOFF_BASE * (2**consecutive_fast_exits),
                _RESTART_BACKOFF_CAP,
            )
            self.last_error = f"ffmpeg exited (code {proc.returncode}); restarting"
            _LOGGER.warning(
                "NVR recorder %r exited (code %s) after %.1fs; restarting in %.0fs",
                self.name,
                proc.returncode,
                runtime,
                backoff,
            )
            if self._stop_event.wait(backoff):
                return

    def _spawn_once(self) -> "subprocess.Popen[bytes] | None":
        """Resolve a fresh URL and spawn one ffmpeg process, or None on failure."""
        try:
            info = self._resolver()
        except Exception as exc:  # noqa: BLE001 — must not kill the watcher thread
            self.last_error = f"resolve failed: {exc}"
            return None
        if not info or not isinstance(info, dict):
            self.last_error = "no stream URL available"
            return None
        url = info.get("url")
        if not isinstance(url, str) or not url:
            self.last_error = "no stream URL available"
            return None
        conn_type = info.get("type") if isinstance(info.get("type"), str) else None

        try:
            os.makedirs(self._output_dir, exist_ok=True)
        except OSError as exc:
            self.last_error = f"cannot create output dir: {exc}"
            return None

        cmd = self._build_cmd(url, conn_type)
        try:
            return subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except (OSError, FileNotFoundError) as exc:
            self.last_error = f"ffmpeg spawn failed: {exc}"
            return None

    def _build_cmd(self, url: str, conn_type: str | None) -> list[str]:
        """Build the ffmpeg segment-muxer command line.

        ``-rtsp_transport tcp`` only for LOCAL (matches CLAUDE.md's Stream
        Rules: ``{"rtsp_transport":"tcp"}`` LOCAL only, empty for REMOTE).
        """
        cmd = [self._ffmpeg_binary, "-y"]
        if conn_type == "LOCAL":
            cmd += ["-rtsp_transport", "tcp"]
        cmd += ["-i", url]
        pattern = os.path.join(self._output_dir, "%Y%m%d-%H%M%S.mp4")
        cmd += [
            "-c",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            str(self._segment_seconds),
            "-reset_timestamps",
            "1",
            "-strftime",
            "1",
            "-movflags",
            "+faststart",
            pattern,
        ]
        return cmd


class NVRManager:
    """Owns continuous-mode local recorders for all cameras.

    Args:
        ffmpeg_binary: ffmpeg binary name (resolved on PATH) or absolute path.
        segment_seconds: MP4 segment length in seconds.
    """

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        segment_seconds: int = DEFAULT_SEGMENT_SECONDS,
    ) -> None:
        self._ffmpeg_binary = ffmpeg_binary
        self._segment_seconds = segment_seconds
        self._lock = threading.RLock()  # guards _recorders dict mutation
        self._recorders: dict[str, _CameraRecorder] = {}

    # ── capability ────────────────────────────────────────────────────────
    def _resolve_binary(self) -> str | None:
        found = shutil.which(self._ffmpeg_binary)
        if found:
            return found
        if os.path.isfile(self._ffmpeg_binary) and os.access(
            self._ffmpeg_binary, os.X_OK
        ):
            return self._ffmpeg_binary
        return None

    @property
    def available(self) -> bool:
        """True if a usable ffmpeg binary exists on this host."""
        return self._resolve_binary() is not None

    # ── status ───────────────────────────────────────────────────────────
    def is_recording(self, name: str) -> bool:
        """True if a live watcher/ffmpeg process is running for *name*."""
        with self._lock:
            rec = self._recorders.get(name)
        return rec is not None and rec.running

    def last_error(self, name: str) -> str | None:
        """Most recent resolve/spawn/exit diagnostic for *name*, or None."""
        with self._lock:
            rec = self._recorders.get(name)
        return rec.last_error if rec is not None else None

    # ── lifecycle ────────────────────────────────────────────────────────
    def start_recording(
        self, name: str, resolver: StreamResolver, output_dir: str
    ) -> bool:
        """Start (or confirm already-running) continuous recording for *name*.

        Args:
            name: stable per-camera key (recommend the same slug used for the
                go2rtc stream name, e.g. ``bosch_terrasse``).
            resolver: SYNC callable returning ``{"url", "type", ...}`` (the
                same shape as ``cli_bridge.get_stream_url``) or ``None``. Runs
                on the watcher thread, NOT the event loop — callers building a
                closure over the async cli_bridge must wrap the sync variant
                (``cli_bridge.get_stream_url``), not the async one.
            output_dir: directory MP4 segments are written to (created if
                missing).

        Returns False immediately if ffmpeg is unavailable or arguments are
        invalid; the watcher's own resolve/spawn failures surface via
        :meth:`last_error` instead (this call does not block on them).
        """
        if not name or not output_dir:
            return False
        resolved_binary = self._resolve_binary()
        if resolved_binary is None:
            _LOGGER.warning(
                "ffmpeg binary %r not found; cannot start NVR recording for %r",
                self._ffmpeg_binary,
                name,
            )
            return False
        with self._lock:
            rec = self._recorders.get(name)
            if rec is None:
                rec = _CameraRecorder(
                    name, resolver, output_dir, resolved_binary, self._segment_seconds
                )
                self._recorders[name] = rec
        return rec.start()

    def stop_recording(self, name: str) -> None:
        """Stop and forget the recorder for *name*. Safe if not running."""
        with self._lock:
            rec = self._recorders.pop(name, None)
        if rec is not None:
            rec.stop()

    def stop_all(self) -> None:
        """Stop every active recorder (app shutdown hook)."""
        with self._lock:
            recs = list(self._recorders.values())
            self._recorders.clear()
        for rec in recs:
            rec.stop()

    # ── async wrappers (NiceGUI handlers run on the event loop) ────────────
    async def async_start_recording(
        self, name: str, resolver: StreamResolver, output_dir: str
    ) -> bool:
        """Async twin of :meth:`start_recording` (offloaded to a worker thread)."""
        return await asyncio.to_thread(self.start_recording, name, resolver, output_dir)

    async def async_stop_recording(self, name: str) -> None:
        """Async twin of :meth:`stop_recording` (offloaded to a worker thread)."""
        await asyncio.to_thread(self.stop_recording, name)


# Module-level singleton: the frontend uses one NVRManager for the whole process.
_manager: NVRManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> NVRManager:
    """Return the process-wide NVRManager singleton (created on first call).

    Registers an ``atexit`` hook and (when on the main thread) a SIGTERM
    handler so every camera's ffmpeg child is reaped on shutdown, mirroring
    :func:`go2rtc_manager.get_manager`.
    """
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = NVRManager()
            mgr = _manager
            atexit.register(mgr.stop_all)
            try:
                _prev = signal.getsignal(signal.SIGTERM)

                def _handler(signum: int, frame: types.FrameType | None) -> None:
                    mgr.stop_all()
                    if callable(_prev):
                        _prev(signum, frame)

                signal.signal(signal.SIGTERM, _handler)
            except (ValueError, OSError):
                # Not on the main thread (e.g. under the test runner) — skip.
                pass
        return _manager
