"""go2rtc subprocess manager — one long-running instance for the whole app.

The Python CLI already knows how to spawn go2rtc for a *single* camera and block
until Ctrl+C (``bosch_camera._start_go2rtc_with_camera``). A web frontend needs
the opposite lifecycle: ONE shared go2rtc process for the whole app, streams
added/removed dynamically over go2rtc's REST API, and a clean shutdown hook.

This manager owns that lifecycle:

* :meth:`ensure_running` — idempotent spawn (bootstrap config = API + WebRTC
  listeners only, no streams); waits for the HTTP API; startup is serialised so
  concurrent callers never spawn twice, and the (up-to-``start_timeout``) wait
  does NOT hold the state lock (so :meth:`stop` stays responsive).
* :meth:`add_stream` — ``PUT /api/streams?name=&src=`` to register a camera's
  source, then verifies via ``GET /api/streams?src=<name>``. Mirrors the proven
  HA path: ``rtsps://`` is rewritten to ``rtspx://`` so go2rtc skips its RTSP-
  client TLS check (Bosch cloud certs have a hostname mismatch go2rtc rejects),
  and an ``HTTP 400`` with a ``yaml:``-prefixed body is a SOFT success (the in-
  memory stream is live; only the on-disk yaml persist failed).
* :meth:`remove_stream` / :meth:`stop` — teardown.
* URL helpers (:meth:`webrtc_url`, :meth:`hls_url`, :meth:`viewer_url`) hand the
  browser player the endpoints the ported ``Go2rtcStream`` JS expects.

The blocking subprocess/socket/HTTP work is synchronous; async (NiceGUI) callers
MUST use the ``async_*`` wrappers, which offload to a worker thread so the event
loop is never blocked.

The actual source URL comes from :func:`cli_bridge.get_stream_url`. Because Gen2
cameras rotate Digest creds on every ``PUT /connection``, that URL is short-
lived — refreshing it + re-registering the source is the manager's job too
(Phase E); for now :meth:`add_stream` just (re)registers whatever URL it is given.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import types
import urllib.error
import urllib.parse
import urllib.request

_LOGGER = logging.getLogger(__name__)

# Bootstrap go2rtc config: API + WebRTC listeners, CORS open, NO streams (streams
# are added at runtime via the REST API). ``origin: "*"`` lets the browser POST
# the WebRTC SDP offer cross-origin from the NiceGUI app's port to go2rtc's port
# (the only CORS mode go2rtc supports).
_BOOTSTRAP_CONFIG = (
    "api:\n"
    '  listen: ":{api_port}"\n'
    '  origin: "*"\n'
    "webrtc:\n"
    '  listen: ":{webrtc_port}"\n'
    "log:\n"
    "  level: warn\n"
    "streams:\n"
)


class Go2rtcManager:
    """Owns a single shared go2rtc subprocess for the frontend.

    Args:
        binary: go2rtc binary name (resolved on PATH) or an absolute path.
        api_port: HTTP API + WebRTC-signaling port (browser connects here).
        webrtc_port: ICE/RTP listener port.
        start_timeout: Seconds to wait for the API to become reachable.
    """

    def __init__(
        self,
        *,
        binary: str = "go2rtc",
        api_port: int = 1984,
        webrtc_port: int = 8555,
        start_timeout: float = 10.0,
    ) -> None:
        self._binary = binary
        self._api_port = api_port
        self._webrtc_port = webrtc_port
        self._start_timeout = start_timeout
        self._lock = threading.RLock()  # guards _proc / _cfg_path mutations
        self._start_lock = (
            threading.Lock()
        )  # serialises spawn+wait, never held by stop()
        self._proc: subprocess.Popen[bytes] | None = None
        self._cfg_path: str | None = None
        self._reusing_external = False  # True when an already-running go2rtc was reused

    # ── capability ────────────────────────────────────────────────────────
    def _resolve_binary(self) -> str | None:
        """Return the resolved go2rtc binary path, or None if unavailable."""
        found = shutil.which(self._binary)
        if found:
            return found
        if os.path.isfile(self._binary) and os.access(self._binary, os.X_OK):
            return self._binary
        return None

    @property
    def available(self) -> bool:
        """True if a usable go2rtc binary exists on this host."""
        return self._resolve_binary() is not None

    @property
    def base_url(self) -> str:
        """go2rtc HTTP base URL the browser player talks to."""
        return f"http://127.0.0.1:{self._api_port}"

    @property
    def running(self) -> bool:
        """True if we have a live managed process OR reused an external one."""
        with self._lock:
            if self._reusing_external:
                return True
            return self._proc is not None and self._proc.poll() is None

    # ── lifecycle ─────────────────────────────────────────────────────────
    def ensure_running(self) -> bool:
        """Start go2rtc if it is not already running. Idempotent + thread-safe.

        Startup is serialised by ``_start_lock`` so concurrent callers spawn at
        most one process; the blocking readiness wait happens WITHOUT the state
        lock so :meth:`stop` and status reads stay responsive.

        Returns True if a usable instance is running afterwards, else False.
        """
        if self.running:
            return True

        with self._start_lock:
            # Re-check under the startup lock (another thread may have won).
            if self.running:
                return True

            resolved = self._resolve_binary()
            if resolved is None:
                _LOGGER.warning("go2rtc binary %r not found on PATH", self._binary)
                return False

            if not self._port_free(self._api_port):
                # Port busy: reuse an already-running go2rtc if its API answers.
                # NOTE: a foreign go2rtc may lack `api.origin:"*"` — browser
                # WebRTC POSTs would then fail CORS. We cannot detect that here.
                if self._api_reachable():
                    _LOGGER.info("Reusing existing go2rtc on port %d", self._api_port)
                    with self._lock:
                        self._reusing_external = True
                    return True
                _LOGGER.warning("Port %d busy and not a go2rtc API", self._api_port)
                return False

            cfg = _BOOTSTRAP_CONFIG.format(
                api_port=self._api_port, webrtc_port=self._webrtc_port
            )
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", prefix="bosch_fe_go2rtc_", delete=False
            )
            tmp.write(cfg)
            tmp.flush()
            tmp.close()

            try:
                proc = subprocess.Popen(
                    [resolved, "-config", tmp.name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                _LOGGER.error("Failed to spawn go2rtc: %s", exc)
                self._safe_unlink(tmp.name)
                return False

            with self._lock:
                self._proc = proc
                self._cfg_path = tmp.name

            # Blocking readiness wait — OUTSIDE any lock.
            if not self._wait_for_api():
                _LOGGER.error(
                    "go2rtc did not become reachable within %.0fs", self._start_timeout
                )
                self.stop()
                return False

            _LOGGER.info("go2rtc started on %s (pid %d)", self.base_url, proc.pid)
            return True

    def stop(self) -> None:
        """Terminate the subprocess and remove the temp config. Safe to repeat."""
        # Capture + clear state under the lock, then do the blocking wait outside
        # so a concurrent caller is never stalled by our 5s terminate window.
        with self._lock:
            proc = self._proc
            cfg_path = self._cfg_path
            self._proc = None
            self._cfg_path = None
            self._reusing_external = False
        if proc is not None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except OSError:
                pass
        self._safe_unlink(cfg_path)

    # ── stream registration ───────────────────────────────────────────────
    def add_stream(self, name: str, src_url: str) -> bool:
        """Register (or replace) a camera source under *name*.

        Args:
            name: stream key (also the browser ``?src=`` value), e.g. ``bosch_terrasse``.
            src_url: the source URL go2rtc consumes. ``rtsps://`` is rewritten to
                ``rtspx://`` so go2rtc skips its RTSP-client TLS verification.

        Returns True once go2rtc confirms the stream exists.
        """
        if not name or not src_url:
            return False
        if not self.ensure_running():
            return False

        # Bosch cloud certs have a hostname mismatch go2rtc's Go RTSP client
        # rejects; rtspx:// tells go2rtc to skip that check (proven in HA).
        if src_url.startswith("rtsps://"):
            src_url = "rtspx://" + src_url[len("rtsps://") :]

        qs = urllib.parse.urlencode({"name": name, "src": src_url})
        try:
            status, body = self._api_request(f"/api/streams?{qs}", method="PUT")
        except urllib.error.URLError as exc:
            _LOGGER.error("go2rtc add_stream(%s) failed: %s", name, exc)
            return False

        # 2xx = clean success. HTTP 400 + "yaml:" body = SOFT success: the stream
        # is registered in memory, only the on-disk yaml persist failed (expected
        # with a read-only/temp config). Anything else is a real failure.
        soft_yaml_ok = status == 400 and body.lstrip().startswith(b"yaml:")
        if not (200 <= status < 300 or soft_yaml_ok):
            _LOGGER.error("go2rtc add_stream(%s) HTTP %d: %r", name, status, body[:120])
            return False

        return self.stream_exists(name)

    def remove_stream(self, name: str) -> bool:
        """Delete a stream by name. Returns True if go2rtc accepted the request."""
        if not name or not self.running:
            return False
        qs = urllib.parse.urlencode({"src": name})
        try:
            status, _ = self._api_request(f"/api/streams?{qs}", method="DELETE")
        except urllib.error.URLError as exc:
            _LOGGER.error("go2rtc remove_stream(%s) failed: %s", name, exc)
            return False
        return 200 <= status < 300

    def stream_exists(self, name: str) -> bool:
        """True if go2rtc currently knows a stream named *name*.

        Uses the filtered ``GET /api/streams?src=<name>`` (HTTP 200 = present,
        404 = absent) — the precise check HA uses to verify a registration.
        """
        if not self.running and not self._api_reachable():
            return False
        qs = urllib.parse.urlencode({"src": name})
        try:
            status, _ = self._api_request(f"/api/streams?{qs}", method="GET")
        except urllib.error.URLError:
            return False
        return 200 <= status < 300

    # ── URL helpers (what the browser player consumes) ─────────────────────
    def webrtc_url(self, name: str) -> str:
        """WebRTC SDP-exchange endpoint (``POST`` offer → answer)."""
        return f"{self.base_url}/api/webrtc?src={urllib.parse.quote(name)}"

    def hls_url(self, name: str) -> str:
        """HLS manifest URL (fallback transport)."""
        return f"{self.base_url}/api/stream.m3u8?src={urllib.parse.quote(name)}"

    def viewer_url(self, name: str) -> str:
        """go2rtc's built-in viewer page (debug / manual check)."""
        return f"{self.base_url}/stream.html?src={urllib.parse.quote(name)}"

    # ── async wrappers (NiceGUI handlers run on the event loop) ────────────
    async def async_ensure_running(self) -> bool:
        """Async twin of :meth:`ensure_running` (offloaded to a worker thread)."""
        return await asyncio.to_thread(self.ensure_running)

    async def async_add_stream(self, name: str, src_url: str) -> bool:
        """Async twin of :meth:`add_stream` (offloaded to a worker thread)."""
        return await asyncio.to_thread(self.add_stream, name, src_url)

    async def async_remove_stream(self, name: str) -> bool:
        """Async twin of :meth:`remove_stream` (offloaded to a worker thread)."""
        return await asyncio.to_thread(self.remove_stream, name)

    # ── internals ──────────────────────────────────────────────────────────
    def _port_free(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False

    def _api_reachable(self) -> bool:
        try:
            self._api_request("/api/streams", method="GET", timeout=1.0)
            return True
        except urllib.error.URLError:
            return False

    def _wait_for_api(self) -> bool:
        """Wait until the HTTP API actually answers (not just the TCP port)."""
        deadline = time.time() + self._start_timeout
        while time.time() < deadline:
            proc = self._proc
            if proc is not None and proc.poll() is not None:
                return False  # exited prematurely
            try:
                with socket.create_connection(
                    ("127.0.0.1", self._api_port), timeout=0.5
                ):
                    pass
            except OSError:
                time.sleep(0.2)
                continue
            # TCP accepts — but go2rtc's HTTP router may not be ready yet, so
            # confirm a real API response before declaring success.
            if self._api_reachable():
                return True
            time.sleep(0.2)
        return False

    def _api_request(
        self, path: str, *, method: str = "GET", timeout: float = 5.0
    ) -> tuple[int, bytes]:
        """Perform a localhost go2rtc API call.

        Returns ``(status_code, body)``. An HTTP error status (4xx/5xx) is
        returned as a normal tuple (NOT raised) so callers can treat go2rtc's
        ``400 yaml:`` soft-success correctly; only transport errors raise URLError.
        """
        req = urllib.request.Request(f"{self.base_url}{path}", method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (localhost)
                body: bytes = resp.read()
                return int(resp.status), body
        except urllib.error.HTTPError as exc:
            # HTTPError IS a response — surface its status + body instead of raising.
            return int(exc.code), exc.read()

    def _safe_unlink(self, path: str | None) -> None:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _unlink_cfg(self) -> None:
        self._safe_unlink(self._cfg_path)
        self._cfg_path = None


# Module-level singleton: the frontend uses one go2rtc for the whole process.
_manager: Go2rtcManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> Go2rtcManager:
    """Return the process-wide Go2rtcManager singleton (created on first call).

    Registers an ``atexit`` hook and (when on the main thread) a SIGTERM handler
    so the go2rtc child is reaped on shutdown. The plumbing layer should ALSO
    wire ``app.on_shutdown(manager.stop)`` for NiceGUI's graceful exit path.
    """
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = Go2rtcManager()
            mgr = _manager
            atexit.register(mgr.stop)
            try:
                _prev = signal.getsignal(signal.SIGTERM)

                def _handler(signum: int, frame: types.FrameType | None) -> None:
                    mgr.stop()
                    if callable(_prev):
                        _prev(signum, frame)

                signal.signal(signal.SIGTERM, _handler)
            except (ValueError, OSError):
                # Not on the main thread (e.g. under the test runner) — skip.
                pass
        return _manager
