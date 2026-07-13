"""Tests for the local Mini-NVR continuous-recording manager (Phase 1).

Subprocess/thread I/O is mocked or driven synchronously — these pin the
lifecycle (idempotent start, resolve-per-restart, crash-restart backoff,
never-restart-just-for-creds), the ffmpeg command line (rtsp_transport tcp
LOCAL-only, segment muxer flags), the singleton, and the async wrappers. No
real ffmpeg binary or network is touched.

``_CameraRecorder._run`` is the watcher loop that normally lives on its own
background thread; tests call it directly (synchronously, on the test
thread) with a pre-armed ``_stop_event`` and small/zero backoff constants so
the loop terminates deterministically without real sleeps.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bosch_camera_frontend.adapters import nvr_manager as nm
from bosch_camera_frontend.adapters.nvr_manager import NVRManager, _CameraRecorder


def _rec(**kw: Any) -> _CameraRecorder:
    defaults: dict[str, Any] = dict(
        name="bosch_cam",
        resolver=lambda: {"url": "rtsp://u:p@1.2.3.4/rtsp_tunnel", "type": "LOCAL"},
        output_dir="/tmp/nvr_out",
        ffmpeg_binary="ffmpeg",
        segment_seconds=300,
    )
    defaults.update(kw)
    return _CameraRecorder(**defaults)


class TestAvailability:
    def test_available_true_when_on_path(self) -> None:
        m = NVRManager()
        with patch.object(nm.shutil, "which", return_value="/usr/local/bin/ffmpeg"):
            assert m.available is True

    def test_available_false_when_missing(self) -> None:
        m = NVRManager()
        with (
            patch.object(nm.shutil, "which", return_value=None),
            patch.object(nm.os.path, "isfile", return_value=False),
        ):
            assert m.available is False

    def test_absolute_path_binary_accepted(self) -> None:
        m = NVRManager(ffmpeg_binary="/opt/ffmpeg")
        with (
            patch.object(nm.shutil, "which", return_value=None),
            patch.object(nm.os.path, "isfile", return_value=True),
            patch.object(nm.os, "access", return_value=True),
        ):
            assert m.available is True


class TestBuildCmd:
    def test_local_adds_rtsp_transport_tcp(self) -> None:
        r = _rec()
        cmd = r._build_cmd("rtsp://u:p@1.2.3.4/x", "LOCAL")
        assert "-rtsp_transport" in cmd
        assert cmd[cmd.index("-rtsp_transport") + 1] == "tcp"

    def test_remote_omits_rtsp_transport(self) -> None:
        r = _rec()
        cmd = r._build_cmd("rtsps://proxy:443/x", "REMOTE")
        assert "-rtsp_transport" not in cmd

    def test_none_conn_type_omits_rtsp_transport(self) -> None:
        r = _rec()
        cmd = r._build_cmd("rtsp://x", None)
        assert "-rtsp_transport" not in cmd

    def test_segment_muxer_flags_present(self) -> None:
        r = _rec(segment_seconds=120)
        cmd = r._build_cmd("rtsp://x", "LOCAL")
        assert cmd[0] == "ffmpeg"
        assert "-f" in cmd and cmd[cmd.index("-f") + 1] == "segment"
        assert "-segment_time" in cmd
        assert cmd[cmd.index("-segment_time") + 1] == "120"
        assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
        assert "-strftime" in cmd
        assert cmd[-1].endswith("%Y%m%d-%H%M%S.mp4")
        assert cmd[-1].startswith("/tmp/nvr_out")


class TestSpawnOnce:
    def test_resolver_raises_records_error_returns_none(self) -> None:
        def _boom() -> dict[str, Any] | None:
            raise RuntimeError("network down")

        r = _rec(resolver=_boom)
        assert r._spawn_once() is None
        assert "resolve failed" in (r.last_error or "")

    def test_resolver_returns_none_records_error(self) -> None:
        r = _rec(resolver=lambda: None)
        assert r._spawn_once() is None
        assert r.last_error == "no stream URL available"

    def test_resolver_missing_url_key_records_error(self) -> None:
        r = _rec(resolver=lambda: {"type": "LOCAL"})
        assert r._spawn_once() is None
        assert r.last_error == "no stream URL available"

    def test_resolver_empty_url_records_error(self) -> None:
        r = _rec(resolver=lambda: {"url": "", "type": "LOCAL"})
        assert r._spawn_once() is None
        assert r.last_error == "no stream URL available"

    def test_resolver_non_dict_return_records_error_no_crash(self) -> None:
        """Regression test for a bug-hunt finding (2026-07-13): a resolver
        that violates its own contract (returns a truthy non-dict, e.g. a
        stray string) must not crash the watcher thread with an
        AttributeError on `.get` — it must be treated the same as a failed
        resolve."""
        r = _rec(resolver=lambda: "not-a-dict")  # type: ignore[arg-type,return-value]
        assert r._spawn_once() is None
        assert r.last_error == "no stream URL available"

    def test_mkdir_failure_records_error(self) -> None:
        r = _rec()
        with patch.object(nm.os, "makedirs", side_effect=OSError("no space")):
            assert r._spawn_once() is None
        assert "cannot create output dir" in (r.last_error or "")

    def test_popen_filenotfound_records_error(self) -> None:
        r = _rec()
        with (
            patch.object(nm.os, "makedirs"),
            patch.object(
                nm.subprocess, "Popen", side_effect=FileNotFoundError("no ffmpeg")
            ),
        ):
            assert r._spawn_once() is None
        assert "ffmpeg spawn failed" in (r.last_error or "")

    def test_happy_path_spawns_process(self) -> None:
        r = _rec()
        fake_proc = MagicMock()
        with (
            patch.object(nm.os, "makedirs") as mkdir,
            patch.object(nm.subprocess, "Popen", return_value=fake_proc) as popen,
        ):
            proc = r._spawn_once()
            mkdir.assert_called_once_with("/tmp/nvr_out", exist_ok=True)
            popen.assert_called_once()
            assert proc is fake_proc


class TestWatcherLoop:
    """Drives ``_CameraRecorder._run`` directly (synchronously) with the
    stop event pre-armed via side effects so the loop always terminates.
    """

    def test_stop_before_first_iteration_does_nothing(self) -> None:
        r = _rec()
        r._stop_event.set()
        r._run()  # returns immediately, no spawn attempted
        assert r._proc is None

    def test_stop_race_after_spawn_terminates_orphaned_process(self) -> None:
        """Regression test for a race found by an adversarial bug-hunt agent
        (2026-07-13): if stop() sets _stop_event while the watcher is inside
        _spawn_once() (resolving + Popen, both outside the lock), the newly
        spawned process must be terminated by _run() itself instead of being
        silently orphaned (nobody else holds a reference to it once stop()
        has already returned and the caller dropped the recorder)."""
        r = _rec()
        fake_proc = MagicMock()

        def _spawn_and_stop() -> "MagicMock":
            # Simulate stop() racing in exactly between the spawn and the
            # lock-protected _stop_event check.
            r._stop_event.set()
            return fake_proc

        with patch.object(r, "_spawn_once", side_effect=_spawn_and_stop):
            r._run()

        fake_proc.terminate.assert_called_once()
        assert r._proc is None  # never stored, so no later code can find it
        # _terminate()'s own bounded wait(timeout=5) is expected (that's the
        # cleanup path) — the regression this guards against is an
        # UNBOUNDED, untracked proc.wait() via the main loop body instead.
        fake_proc.wait.assert_called_once_with(timeout=5)

    def test_resolve_failure_backs_off_then_stops(self) -> None:
        r = _rec(resolver=lambda: None)
        # First wait() call (the backoff after a failed resolve) reports the
        # stop flag as set, terminating the loop after exactly one attempt.
        with patch.object(r._stop_event, "wait", return_value=True) as wait:
            r._run()
        wait.assert_called_once_with(nm._RESTART_BACKOFF_BASE)
        assert r.last_error == "no stream URL available"

    def test_clean_exit_then_restart_then_stop(self) -> None:
        """A long-lived ffmpeg exits cleanly (runtime above the fast-exit
        threshold) — the fast-exit counter must reset, then the watcher
        restarts once more before stop() takes effect."""
        r = _rec()
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        call_count = {"n": 0}

        def _wait(timeout: float | None = None) -> None:
            call_count["n"] += 1
            if call_count["n"] >= 2:
                r._stop_event.set()

        fake_proc.wait = _wait

        # started_at, then-runtime pairs: each iteration reads monotonic()
        # once before spawn and once after wait() returns; a 60s gap keeps
        # runtime >= _MIN_CLEAN_RUNTIME_SECONDS so the reset branch runs.
        monotonic_values = iter([0.0, 60.0, 60.0, 120.0])

        def _monotonic() -> float:
            try:
                return next(monotonic_values)
            except StopIteration:
                return 120.0

        with (
            patch.object(nm.os, "makedirs"),
            patch.object(nm.subprocess, "Popen", return_value=fake_proc),
            patch.object(nm.time, "monotonic", side_effect=_monotonic),
            patch.object(r._stop_event, "wait", return_value=False),
        ):
            r._run()
        assert call_count["n"] == 2
        assert r._proc is None

    def test_fast_exit_loop_escalates_backoff(self) -> None:
        """Two immediate crashes (runtime < _MIN_CLEAN_RUNTIME_SECONDS) must
        escalate the backoff passed to stop_event.wait beyond the base."""
        r = _rec()
        fake_proc = MagicMock()
        fake_proc.returncode = 1
        fake_proc.wait = MagicMock()

        monotonic_values = iter([0.0, 1.0, 1.0, 2.0, 2.0, 3.0])

        def _monotonic() -> float:
            try:
                return next(monotonic_values)
            except StopIteration:
                return 3.0

        backoffs: list[float] = []

        def _stop_wait(timeout: float | None = None) -> bool:
            if timeout is not None:
                backoffs.append(timeout)
            return len(backoffs) >= 2  # stop after second backoff wait

        with (
            patch.object(nm.os, "makedirs"),
            patch.object(nm.subprocess, "Popen", return_value=fake_proc),
            patch.object(nm.time, "monotonic", side_effect=_monotonic),
            patch.object(r._stop_event, "wait", side_effect=_stop_wait),
        ):
            r._run()
        assert len(backoffs) == 2
        assert backoffs[1] > backoffs[0]  # escalated on the second fast exit

    def test_spawn_failure_then_stop(self) -> None:
        r = _rec(resolver=lambda: {"url": "rtsp://x", "type": "LOCAL"})
        with (
            patch.object(nm.os, "makedirs"),
            patch.object(nm.subprocess, "Popen", side_effect=OSError("boom")),
            patch.object(r._stop_event, "wait", return_value=True),
        ):
            r._run()
        assert "ffmpeg spawn failed" in (r.last_error or "")


class TestRecorderStartStop:
    def test_start_is_idempotent(self) -> None:
        r = _rec()
        block = threading.Event()
        with patch.object(r, "_run", side_effect=lambda: block.wait(5)):
            assert r.start() is True
            first_thread = r._thread
            assert r.start() is True  # already running (thread still blocked
            # in the mocked _run), so no second thread is spawned
            assert r._thread is first_thread
        block.set()
        r.stop()

    def test_running_false_before_start(self) -> None:
        r = _rec()
        assert r.running is False

    def test_stop_terminates_live_process(self) -> None:
        r = _rec()
        fake_proc = MagicMock()
        r._proc = fake_proc
        r._thread = threading.Thread(target=lambda: None)
        r._thread.start()
        r._thread.join()
        r.stop()
        fake_proc.terminate.assert_called_once()

    def test_stop_kills_on_timeout(self) -> None:
        r = _rec()
        fake_proc = MagicMock()
        fake_proc.wait.side_effect = subprocess.TimeoutExpired("ffmpeg", 5)
        r._proc = fake_proc
        r.stop()
        fake_proc.kill.assert_called_once()

    def test_stop_swallows_terminate_oserror(self) -> None:
        r = _rec()
        fake_proc = MagicMock()
        fake_proc.terminate.side_effect = OSError("dead")
        r._proc = fake_proc
        r.stop()  # must not raise

    def test_stop_is_safe_when_idle(self) -> None:
        r = _rec()
        r.stop()  # no proc, no thread — must not raise
        assert r.running is False

    def test_stop_from_within_watcher_thread_does_not_self_join(self) -> None:
        """A real end-to-end start()/stop() pair must not deadlock: stop()
        must not try to join the thread it's called from."""
        r = _rec(resolver=lambda: None)
        with patch.object(nm, "_RESTART_BACKOFF_BASE", 0.0):
            assert r.start() is True
            # Give the watcher thread a moment to enter its resolve-failure
            # backoff loop, then stop it — this must return promptly.
            import time as _time

            _time.sleep(0.05)
            r.stop()
        assert r.running is False


class TestManagerLifecycle:
    def test_start_recording_no_ffmpeg_returns_false(self) -> None:
        m = NVRManager()
        with patch.object(m, "_resolve_binary", return_value=None):
            assert m.start_recording("cam", lambda: None, "/tmp/x") is False

    def test_start_recording_empty_args_returns_false(self) -> None:
        m = NVRManager()
        assert m.start_recording("", lambda: None, "/tmp/x") is False
        assert m.start_recording("cam", lambda: None, "") is False

    def test_start_recording_spawns_and_is_recording(self) -> None:
        m = NVRManager()
        with (
            patch.object(m, "_resolve_binary", return_value="/bin/ffmpeg"),
            patch.object(_CameraRecorder, "start", return_value=True) as start,
        ):
            assert m.start_recording("cam", lambda: None, "/tmp/x") is True
            start.assert_called_once()

    def test_start_recording_end_to_end_reflects_is_recording(self) -> None:
        """Real (non-mocked) recorder: start_recording() makes is_recording()
        True while the watcher thread is alive in its resolve-failure
        backoff, then stop_recording() makes it False again."""
        m = NVRManager()
        with (
            patch.object(m, "_resolve_binary", return_value="/bin/ffmpeg"),
            patch.object(nm, "_RESTART_BACKOFF_BASE", 0.0),
        ):
            assert m.start_recording("cam", lambda: None, "/tmp/x") is True
            import time as _time

            _time.sleep(0.05)
            assert m.is_recording("cam") is True
            m.stop_recording("cam")
        assert m.is_recording("cam") is False

    def test_start_recording_reuses_existing_recorder(self) -> None:
        m = NVRManager()
        with (
            patch.object(m, "_resolve_binary", return_value="/bin/ffmpeg"),
            patch.object(_CameraRecorder, "start", return_value=True) as start,
        ):
            m.start_recording("cam", lambda: None, "/tmp/x")
            m.start_recording("cam", lambda: None, "/tmp/x")
        assert start.call_count == 2  # same recorder object, start() called twice
        with m._lock:
            assert len(m._recorders) == 1

    def test_is_recording_unknown_camera_false(self) -> None:
        m = NVRManager()
        assert m.is_recording("nope") is False

    def test_last_error_unknown_camera_none(self) -> None:
        m = NVRManager()
        assert m.last_error("nope") is None

    def test_last_error_delegates_to_recorder(self) -> None:
        m = NVRManager()
        with patch.object(m, "_resolve_binary", return_value="/bin/ffmpeg"):
            with patch.object(_CameraRecorder, "start", return_value=True):
                m.start_recording("cam", lambda: None, "/tmp/x")
            with m._lock:
                m._recorders["cam"].last_error = "boom"
            assert m.last_error("cam") == "boom"

    def test_stop_recording_stops_and_forgets(self) -> None:
        m = NVRManager()
        with (
            patch.object(m, "_resolve_binary", return_value="/bin/ffmpeg"),
            patch.object(_CameraRecorder, "start", return_value=True),
            patch.object(_CameraRecorder, "stop") as stop,
        ):
            m.start_recording("cam", lambda: None, "/tmp/x")
            m.stop_recording("cam")
            stop.assert_called_once()
        with m._lock:
            assert "cam" not in m._recorders

    def test_stop_recording_unknown_camera_noop(self) -> None:
        m = NVRManager()
        m.stop_recording("nope")  # must not raise

    def test_stop_all_stops_every_recorder(self) -> None:
        m = NVRManager()
        with (
            patch.object(m, "_resolve_binary", return_value="/bin/ffmpeg"),
            patch.object(_CameraRecorder, "start", return_value=True),
            patch.object(_CameraRecorder, "stop") as stop,
        ):
            m.start_recording("cam1", lambda: None, "/tmp/x")
            m.start_recording("cam2", lambda: None, "/tmp/y")
            m.stop_all()
        assert stop.call_count == 2
        with m._lock:
            assert m._recorders == {}


class TestAsyncWrappers:
    async def test_async_start_recording(self) -> None:
        m = NVRManager()
        with patch.object(m, "start_recording", return_value=True) as start:
            assert await m.async_start_recording("cam", lambda: None, "/tmp/x") is True
            start.assert_called_once()

    async def test_async_stop_recording(self) -> None:
        m = NVRManager()
        with patch.object(m, "stop_recording") as stop:
            await m.async_stop_recording("cam")
            stop.assert_called_once_with("cam")


class TestSingleton:
    def test_get_manager_returns_same_instance(self) -> None:
        nm._manager = None
        try:
            with patch.object(nm.atexit, "register"):
                a = nm.get_manager()
                b = nm.get_manager()
                assert a is b
        finally:
            nm._manager = None

    def test_singleton_registers_atexit_and_signal(self) -> None:
        nm._manager = None
        captured: dict[str, Any] = {}

        def _fake_signal(sig: int, handler: Any) -> Any:
            captured["handler"] = handler
            return None

        with (
            patch.object(nm.atexit, "register") as atexit_reg,
            patch.object(nm.signal, "getsignal", return_value=None),
            patch.object(nm.signal, "signal", side_effect=_fake_signal),
        ):
            m = nm.get_manager()
            atexit_reg.assert_called_once_with(m.stop_all)
            with patch.object(m, "stop_all") as stop_all:
                captured["handler"](nm.signal.SIGTERM, None)
                stop_all.assert_called_once()
        nm._manager = None

    def test_singleton_signal_register_failure_swallowed(self) -> None:
        nm._manager = None
        with (
            patch.object(nm.atexit, "register"),
            patch.object(nm.signal, "getsignal", return_value=None),
            patch.object(
                nm.signal, "signal", side_effect=ValueError("not main thread")
            ),
        ):
            m = nm.get_manager()  # must not raise
            assert isinstance(m, NVRManager)
        nm._manager = None


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    """Keep the module-level singleton from leaking between tests."""
    nm._manager = None
    yield
    nm._manager = None
