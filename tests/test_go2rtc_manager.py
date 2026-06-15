"""Tests for the go2rtc subprocess manager (WebRTC Phase B).

Subprocess, socket and HTTP I/O are all mocked — these pin the lifecycle
(idempotent spawn, reuse-existing, premature-exit teardown), the REST stream
registration (rtspx rewrite, 400-yaml soft-success, GET-verify), the URL
helpers and the async wrappers. No real go2rtc binary or network is touched.
"""

from __future__ import annotations

import urllib.error
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bosch_camera_frontend.adapters import go2rtc_manager as gm
from bosch_camera_frontend.adapters.go2rtc_manager import Go2rtcManager


def _mgr(**kw: Any) -> Go2rtcManager:
    return Go2rtcManager(binary="go2rtc", api_port=19840, webrtc_port=18555, **kw)


class TestAvailability:
    def test_available_true_when_on_path(self) -> None:
        with patch.object(gm.shutil, "which", return_value="/usr/local/bin/go2rtc"):
            assert _mgr().available is True

    def test_available_false_when_missing(self) -> None:
        with (
            patch.object(gm.shutil, "which", return_value=None),
            patch.object(gm.os.path, "isfile", return_value=False),
        ):
            assert _mgr().available is False

    def test_absolute_path_binary_accepted(self) -> None:
        m = Go2rtcManager(binary="/opt/go2rtc")
        with (
            patch.object(gm.shutil, "which", return_value=None),
            patch.object(gm.os.path, "isfile", return_value=True),
            patch.object(gm.os, "access", return_value=True),
        ):
            assert m.available is True


class TestEnsureRunning:
    def test_binary_missing_returns_false(self) -> None:
        m = _mgr()
        with patch.object(m, "_resolve_binary", return_value=None):
            assert m.ensure_running() is False

    def test_happy_path_spawns_and_waits(self) -> None:
        m = _mgr()
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 4242
        with (
            patch.object(m, "_resolve_binary", return_value="/bin/go2rtc"),
            patch.object(m, "_port_free", return_value=True),
            patch.object(m, "_wait_for_api", return_value=True),
            patch.object(gm.subprocess, "Popen", return_value=fake_proc) as popen,
            patch.object(gm.tempfile, "NamedTemporaryFile") as ntf,
        ):
            ntf.return_value.name = "/tmp/cfg.yaml"
            assert m.ensure_running() is True
            popen.assert_called_once()
        assert m.running is True

    def test_idempotent_no_second_spawn(self) -> None:
        m = _mgr()
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        with (
            patch.object(m, "_resolve_binary", return_value="/bin/go2rtc"),
            patch.object(m, "_port_free", return_value=True),
            patch.object(m, "_wait_for_api", return_value=True),
            patch.object(gm.subprocess, "Popen", return_value=fake_proc) as popen,
            patch.object(gm.tempfile, "NamedTemporaryFile") as ntf,
        ):
            ntf.return_value.name = "/tmp/cfg.yaml"
            assert m.ensure_running() is True
            assert m.ensure_running() is True  # already running
            popen.assert_called_once()

    def test_reuse_existing_go2rtc_when_port_busy(self) -> None:
        m = _mgr()
        with (
            patch.object(m, "_resolve_binary", return_value="/bin/go2rtc"),
            patch.object(m, "_port_free", return_value=False),
            patch.object(m, "_api_reachable", return_value=True),
            patch.object(gm.subprocess, "Popen") as popen,
        ):
            assert m.ensure_running() is True
            popen.assert_not_called()  # reused, not spawned
            assert m.running is True  # reuse flag makes running True

    def test_port_busy_not_go2rtc_returns_false(self) -> None:
        m = _mgr()
        with (
            patch.object(m, "_resolve_binary", return_value="/bin/go2rtc"),
            patch.object(m, "_port_free", return_value=False),
            patch.object(m, "_api_reachable", return_value=False),
            patch.object(gm.subprocess, "Popen") as popen,
        ):
            assert m.ensure_running() is False
            popen.assert_not_called()

    def test_premature_exit_returns_false_and_cleans_up(self) -> None:
        m = _mgr()
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 1  # already exited
        with (
            patch.object(m, "_resolve_binary", return_value="/bin/go2rtc"),
            patch.object(m, "_port_free", return_value=True),
            patch.object(m, "_wait_for_api", return_value=False),
            patch.object(gm.subprocess, "Popen", return_value=fake_proc),
            patch.object(gm.tempfile, "NamedTemporaryFile") as ntf,
        ):
            ntf.return_value.name = "/tmp/cfg.yaml"
            assert m.ensure_running() is False
        assert m.running is False

    def test_popen_oserror(self) -> None:
        m = _mgr()
        with (
            patch.object(m, "_resolve_binary", return_value="/bin/go2rtc"),
            patch.object(m, "_port_free", return_value=True),
            patch.object(gm.subprocess, "Popen", side_effect=OSError("nope")),
            patch.object(gm.tempfile, "NamedTemporaryFile") as ntf,
            patch.object(gm.os, "unlink"),
        ):
            ntf.return_value.name = "/tmp/cfg.yaml"
            assert m.ensure_running() is False


class TestStreamRegistration:
    def test_add_stream_success_rewrites_rtspx(self) -> None:
        m = _mgr()
        with (
            patch.object(m, "ensure_running", return_value=True),
            patch.object(m, "_api_request", return_value=(200, b"")) as api,
            patch.object(m, "stream_exists", return_value=True),
        ):
            assert m.add_stream("bosch_terrasse", "rtsps://h:443/x/rtsp_tunnel") is True
            call_path = api.call_args.args[0]
            assert call_path.startswith("/api/streams?")
            assert "name=bosch_terrasse" in call_path
            # rtsps:// rewritten to rtspx:// (URL-encoded) so go2rtc skips TLS check
            assert "rtspx" in call_path
            assert "rtsps" not in call_path
            assert api.call_args.kwargs["method"] == "PUT"

    def test_add_stream_non_rtsps_url_passed_through(self) -> None:
        m = _mgr()
        with (
            patch.object(m, "ensure_running", return_value=True),
            patch.object(m, "_api_request", return_value=(200, b"")) as api,
            patch.object(m, "stream_exists", return_value=True),
        ):
            assert m.add_stream("cam", "rtsp://127.0.0.1:8554/x") is True
            assert "rtspx" not in api.call_args.args[0]

    def test_add_stream_400_yaml_is_soft_success(self) -> None:
        m = _mgr()
        with (
            patch.object(m, "ensure_running", return_value=True),
            patch.object(m, "_api_request", return_value=(400, b"yaml: cannot write config")),
            patch.object(m, "stream_exists", return_value=True),
        ):
            # in-memory stream IS registered → treat 400+yaml as success
            assert m.add_stream("cam", "rtspx://x") is True

    def test_add_stream_400_non_yaml_is_failure(self) -> None:
        m = _mgr()
        with (
            patch.object(m, "ensure_running", return_value=True),
            patch.object(m, "_api_request", return_value=(400, b"bad request")),
            patch.object(m, "stream_exists", return_value=True),
        ):
            assert m.add_stream("cam", "rtspx://x") is False

    def test_add_stream_500_is_failure(self) -> None:
        m = _mgr()
        with (
            patch.object(m, "ensure_running", return_value=True),
            patch.object(m, "_api_request", return_value=(500, b"boom")),
            patch.object(m, "stream_exists", return_value=True),
        ):
            assert m.add_stream("cam", "rtspx://x") is False

    def test_add_stream_empty_args_returns_false(self) -> None:
        m = _mgr()
        assert m.add_stream("", "rtsps://x") is False
        assert m.add_stream("name", "") is False

    def test_add_stream_ensure_running_fails(self) -> None:
        m = _mgr()
        with patch.object(m, "ensure_running", return_value=False):
            assert m.add_stream("cam", "rtsps://x") is False

    def test_add_stream_verify_fails_returns_false(self) -> None:
        m = _mgr()
        with (
            patch.object(m, "ensure_running", return_value=True),
            patch.object(m, "_api_request", return_value=(200, b"")),
            patch.object(m, "stream_exists", return_value=False),
        ):
            assert m.add_stream("cam", "rtspx://x") is False

    def test_add_stream_transport_error_returns_false(self) -> None:
        m = _mgr()
        with (
            patch.object(m, "ensure_running", return_value=True),
            patch.object(m, "_api_request", side_effect=urllib.error.URLError("boom")),
        ):
            assert m.add_stream("cam", "rtspx://x") is False

    def test_stream_exists_200_true_404_false(self) -> None:
        m = _mgr()
        with patch.object(type(m), "running", property(lambda self: True)):
            with patch.object(m, "_api_request", return_value=(200, b"{}")):
                assert m.stream_exists("cam") is True
            with patch.object(m, "_api_request", return_value=(404, b"")):
                assert m.stream_exists("cam") is False

    def test_stream_exists_transport_error_false(self) -> None:
        m = _mgr()
        with (
            patch.object(type(m), "running", property(lambda self: True)),
            patch.object(m, "_api_request", side_effect=urllib.error.URLError("x")),
        ):
            assert m.stream_exists("cam") is False

    def test_stream_exists_not_running_unreachable(self) -> None:
        m = _mgr()
        with patch.object(m, "_api_reachable", return_value=False):
            assert m.stream_exists("cam") is False

    def test_remove_stream(self) -> None:
        m = _mgr()
        with (
            patch.object(type(m), "running", property(lambda self: True)),
            patch.object(m, "_api_request", return_value=(200, b"")) as api,
        ):
            assert m.remove_stream("cam") is True
            assert api.call_args.kwargs["method"] == "DELETE"

    def test_remove_stream_not_running(self) -> None:
        m = _mgr()
        with patch.object(type(m), "running", property(lambda self: False)):
            assert m.remove_stream("cam") is False

    def test_remove_stream_api_error(self) -> None:
        m = _mgr()
        with (
            patch.object(type(m), "running", property(lambda self: True)),
            patch.object(m, "_api_request", side_effect=urllib.error.URLError("x")),
        ):
            assert m.remove_stream("cam") is False


class TestUrlHelpers:
    def test_webrtc_url(self) -> None:
        assert _mgr().webrtc_url("bosch_terrasse") == (
            "http://127.0.0.1:19840/api/webrtc?src=bosch_terrasse"
        )

    def test_hls_url(self) -> None:
        assert _mgr().hls_url("bosch_terrasse") == (
            "http://127.0.0.1:19840/api/stream.m3u8?src=bosch_terrasse"
        )

    def test_viewer_url(self) -> None:
        assert _mgr().viewer_url("bosch_terrasse") == (
            "http://127.0.0.1:19840/stream.html?src=bosch_terrasse"
        )

    def test_url_helpers_encode_special_chars(self) -> None:
        assert "src=a%20b" in _mgr().webrtc_url("a b")

    def test_base_url(self) -> None:
        assert _mgr().base_url == "http://127.0.0.1:19840"


class TestAsyncWrappers:
    async def test_async_ensure_running(self) -> None:
        m = _mgr()
        with patch.object(m, "ensure_running", return_value=True):
            assert await m.async_ensure_running() is True

    async def test_async_add_stream(self) -> None:
        m = _mgr()
        with patch.object(m, "add_stream", return_value=True) as add:
            assert await m.async_add_stream("cam", "rtsps://x") is True
            add.assert_called_once_with("cam", "rtsps://x")

    async def test_async_remove_stream(self) -> None:
        m = _mgr()
        with patch.object(m, "remove_stream", return_value=True):
            assert await m.async_remove_stream("cam") is True


class TestStop:
    def test_stop_terminates_and_unlinks(self) -> None:
        m = _mgr()
        fake_proc = MagicMock()
        object.__setattr__(m, "_proc", fake_proc)
        object.__setattr__(m, "_cfg_path", "/tmp/cfg.yaml")
        with patch.object(gm.os, "unlink") as unlink:
            m.stop()
            fake_proc.terminate.assert_called_once()
            unlink.assert_called_once_with("/tmp/cfg.yaml")
        assert m.running is False

    def test_stop_kill_on_timeout(self) -> None:
        m = _mgr()
        fake_proc = MagicMock()
        fake_proc.wait.side_effect = gm.subprocess.TimeoutExpired("go2rtc", 5)
        object.__setattr__(m, "_proc", fake_proc)
        m.stop()
        fake_proc.kill.assert_called_once()

    def test_stop_swallows_terminate_oserror(self) -> None:
        m = _mgr()
        fake_proc = MagicMock()
        fake_proc.terminate.side_effect = OSError("dead")
        object.__setattr__(m, "_proc", fake_proc)
        m.stop()  # must not raise
        assert m.running is False

    def test_stop_clears_reuse_flag(self) -> None:
        m = _mgr()
        object.__setattr__(m, "_reusing_external", True)
        assert m.running is True
        m.stop()
        assert m.running is False

    def test_stop_is_safe_when_idle(self) -> None:
        m = _mgr()
        m.stop()  # no proc, no cfg — must not raise
        assert m.running is False


class TestInternals:
    def test_port_free_true_then_busy(self) -> None:
        import socket as _socket

        m = _mgr()
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        busy_port = s.getsockname()[1]
        try:
            assert m._port_free(busy_port) is False
        finally:
            s.close()
        assert m._port_free(0) is True

    def test_api_reachable_true_false(self) -> None:
        m = _mgr()
        with patch.object(m, "_api_request", return_value=(200, b"{}")):
            assert m._api_reachable() is True
        with patch.object(m, "_api_request", side_effect=urllib.error.URLError("x")):
            assert m._api_reachable() is False

    def test_wait_for_api_success(self) -> None:
        m = _mgr()
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        object.__setattr__(m, "_proc", fake_proc)
        with (
            patch.object(gm.socket, "create_connection") as cc,
            patch.object(m, "_api_reachable", return_value=True),
        ):
            cc.return_value.__enter__.return_value = MagicMock()
            assert m._wait_for_api() is True

    def test_wait_for_api_tcp_ok_but_http_not_ready_then_timeout(self) -> None:
        m = _mgr(start_timeout=0.05)
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        object.__setattr__(m, "_proc", fake_proc)
        with (
            patch.object(gm.socket, "create_connection") as cc,
            patch.object(m, "_api_reachable", return_value=False),  # HTTP never ready
            patch.object(gm.time, "sleep", return_value=None),
        ):
            cc.return_value.__enter__.return_value = MagicMock()
            assert m._wait_for_api() is False

    def test_wait_for_api_premature_exit(self) -> None:
        m = _mgr()
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 1  # exited
        object.__setattr__(m, "_proc", fake_proc)
        assert m._wait_for_api() is False

    def test_wait_for_api_tcp_refused_timeout(self) -> None:
        m = _mgr(start_timeout=0.05)
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        object.__setattr__(m, "_proc", fake_proc)
        with (
            patch.object(gm.socket, "create_connection", side_effect=OSError("no")),
            patch.object(gm.time, "sleep", return_value=None),
        ):
            assert m._wait_for_api() is False

    def test_api_request_ok(self) -> None:
        m = _mgr()
        fake_resp = MagicMock()
        fake_resp.read.return_value = b'{"ok":true}'
        fake_resp.status = 200
        fake_resp.__enter__.return_value = fake_resp
        with patch.object(gm.urllib.request, "urlopen", return_value=fake_resp):
            assert m._api_request("/api/streams") == (200, b'{"ok":true}')

    def test_api_request_httperror_returned_not_raised(self) -> None:
        m = _mgr()
        err = urllib.error.HTTPError(
            url="http://x", code=400, msg="Bad", hdrs=None, fp=None
        )
        err.read = MagicMock(return_value=b"yaml: oops")  # type: ignore[method-assign]
        with patch.object(gm.urllib.request, "urlopen", side_effect=err):
            status, body = m._api_request("/api/streams", method="PUT")
            assert status == 400
            assert body == b"yaml: oops"

    def test_unlink_cfg_handles_missing_file(self) -> None:
        m = _mgr()
        object.__setattr__(m, "_cfg_path", "/tmp/nonexistent-xyz.yaml")
        with patch.object(gm.os, "unlink", side_effect=OSError("gone")):
            m._unlink_cfg()  # must not raise
        assert m._cfg_path is None


class TestSingleton:
    def test_get_manager_returns_same_instance(self) -> None:
        gm._manager = None
        try:
            with patch.object(gm.atexit, "register"):
                a = gm.get_manager()
                b = gm.get_manager()
                assert a is b
        finally:
            gm._manager = None

    def test_singleton_registers_atexit_and_signal(self) -> None:
        gm._manager = None
        captured: dict[str, Any] = {}

        def _fake_signal(sig: int, handler: Any) -> Any:
            captured["handler"] = handler
            return None

        with (
            patch.object(gm.atexit, "register") as atexit_reg,
            patch.object(gm.signal, "getsignal", return_value=None),
            patch.object(gm.signal, "signal", side_effect=_fake_signal),
        ):
            m = gm.get_manager()
            atexit_reg.assert_called_once_with(m.stop)
            with patch.object(m, "stop") as stop:
                captured["handler"](gm.signal.SIGTERM, None)  # fire SIGTERM handler
                stop.assert_called_once()
        gm._manager = None

    def test_singleton_signal_register_failure_swallowed(self) -> None:
        gm._manager = None
        with (
            patch.object(gm.atexit, "register"),
            patch.object(gm.signal, "getsignal", return_value=None),
            patch.object(gm.signal, "signal", side_effect=ValueError("not main thread")),
        ):
            m = gm.get_manager()  # must not raise
            assert isinstance(m, Go2rtcManager)
        gm._manager = None


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    """Keep the module-level singleton from leaking between tests."""
    gm._manager = None
    yield
    gm._manager = None
