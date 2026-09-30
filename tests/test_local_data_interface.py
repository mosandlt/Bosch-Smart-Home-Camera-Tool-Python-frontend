"""Local data interface: status mapping, source URL, privacy of the password.

FAKE DATA ONLY (cloud-ID 11111111-..., IP 10.0.0.x, password "test-pw").
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

CAM_ID = "11111111-2222-3333-4444-555555555555"
PW = "test-pw"


def _cam(**over: Any) -> dict[str, Any]:
    cam: dict[str, Any] = {
        "id": CAM_ID,
        "name": "Test Cam",
        "model": "HOME_Eyes_Indoor",
        "firmware": "9.40.105",
        "local_ip": "10.0.0.5",
    }
    cam.update(over)
    return cam


def _resp(status: int, body: Any = None, json_raises: bool = False) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    if json_raises:
        r.json.side_effect = ValueError("bad json")
    else:
        r.json.return_value = body
    return r


def _session(resp: Any = None, exc: Exception | None = None) -> MagicMock:
    s = MagicMock()
    if exc is not None:
        s.get.side_effect = exc
    else:
        s.get.return_value = resp
    return s


@pytest.fixture
def ldi(fake_nicegui: Any) -> Any:
    from bosch_camera_frontend.adapters import local_data_interface

    local_data_interface.clear_status_cache()
    return local_data_interface


class TestFirmware:
    @pytest.mark.parametrize(
        "version,expected",
        [
            ("9.40.105", True),
            ("9.40.202", True),
            ("9.41.0", True),
            ("10.0.0", True),
            ("9.40.104", False),
            ("9.40", False),
            ("9.39.999", False),
            (" 9.40.105 ", True),
            (None, False),
            (9, False),
            ("", False),
            ("garbage", False),
            ("9.40.x", False),
            ("9..105", False),
            ("9.40.-1", False),
            ("9.40." + "9" * 5000, False),
            ("９.40.105", False),
        ],
    )
    def test_supports(self, ldi: Any, version: object, expected: bool) -> None:
        assert ldi.firmware_supports_ldi(version) is expected

    def test_parse_none_for_non_string(self, ldi: Any) -> None:
        assert ldi.parse_firmware(None) is None
        assert ldi.parse_firmware("9.40.105") == (9, 40, 105)


class TestShouldQuery:
    def test_gen2_new_fw(self, ldi: Any) -> None:
        assert ldi.should_query(_cam())
        assert ldi.should_query(_cam(model="HOME_Eyes_Outdoor"))

    @pytest.mark.parametrize("model", ["CAMERA_EYES", "CAMERA_360", "", None, "X"])
    def test_gen1_and_unknown_skipped(self, ldi: Any, model: Any) -> None:
        assert not ldi.should_query(_cam(model=model))

    @pytest.mark.parametrize("fw", ["9.40.104", None, "garbage", "9" * 5000])
    def test_old_or_bad_fw_skipped(self, ldi: Any, fw: Any) -> None:
        assert not ldi.should_query(_cam(firmware=fw))


class TestStateFromResponse:
    def test_active(self, ldi: Any) -> None:
        assert ldi.state_from_response(200, {"username": "localuser"}) == {
            "state": "active",
            "username": "localuser",
        }

    def test_inactive(self, ldi: Any) -> None:
        assert ldi.state_from_response(404, None) == {"state": "inactive"}

    def test_unsupported(self, ldi: Any) -> None:
        assert ldi.state_from_response(449, None) == {"state": "unsupported"}

    @pytest.mark.parametrize(
        "status,body",
        [
            (200, None),
            (200, []),
            (200, {}),
            (200, {"username": 5}),
            (500, None),
            (401, {"username": "x"}),
            (403, None),
            (204, None),
        ],
    )
    def test_keep_last(self, ldi: Any, status: int, body: Any) -> None:
        assert ldi.state_from_response(status, body) is None


class TestFetchStatus:
    API = "https://cloud.invalid"

    def test_active_and_url(self, ldi: Any) -> None:
        s = _session(_resp(200, {"username": "localuser"}))
        entry = ldi.fetch_status(s, _cam(), self.API)
        assert entry == {"state": "active", "username": "localuser"}
        s.get.assert_called_once_with(
            f"{self.API}/v11/video_inputs/{CAM_ID}/{ldi.LDI_ENDPOINT}", timeout=10
        )
        assert ldi.last_status(CAM_ID) == entry

    def test_inactive_404(self, ldi: Any) -> None:
        entry = ldi.fetch_status(_session(_resp(404)), _cam(), self.API)
        assert entry == {"state": "inactive"}

    def test_unsupported_449(self, ldi: Any) -> None:
        entry = ldi.fetch_status(_session(_resp(449)), _cam(), self.API)
        assert entry == {"state": "unsupported"}

    @pytest.mark.parametrize(
        "resp,exc",
        [
            (_resp(500), None),
            (_resp(200, json_raises=True), None),
            (_resp(200, {"nope": 1}), None),
            (None, requests.ConnectionError("down")),
            (None, requests.Timeout("slow")),
        ],
    )
    def test_failure_keeps_last_value(
        self, ldi: Any, resp: Any, exc: Exception | None
    ) -> None:
        ldi.fetch_status(_session(_resp(404)), _cam(), self.API)
        entry = ldi.fetch_status(_session(resp, exc), _cam(), self.API)
        assert entry == {"state": "inactive"}

    def test_failure_without_history_is_none(self, ldi: Any) -> None:
        s = _session(exc=requests.ConnectionError("down"))
        assert ldi.fetch_status(s, _cam(), self.API) is None

    @pytest.mark.parametrize(
        "cam",
        [
            _cam(model="CAMERA_EYES"),
            _cam(model="CAMERA_360"),
            _cam(firmware="9.40.104"),
            _cam(firmware=None),
            _cam(firmware="9" * 5000),
            _cam(id=""),
            _cam(id=None),
        ],
    )
    def test_ineligible_not_queried(self, ldi: Any, cam: dict[str, Any]) -> None:
        s = _session(_resp(200, {"username": "localuser"}))
        assert ldi.fetch_status(s, cam, self.API) is None
        s.get.assert_not_called()


class TestValidation:
    @pytest.mark.parametrize("ip", ["10.0.0.5", "192.168.1.20", " 172.16.0.9 "])
    def test_valid_ip(self, ldi: Any, ip: str) -> None:
        assert ldi.valid_lan_ip(ip) == ip.strip()

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "::1",
            "169.254.1.1",
            "fe80::1",
            "0.0.0.0",
            "8.8.8.8",
            "224.0.0.1",
            "240.0.0.1",
            "",
            "camera.local",
            "10.0.0.5:9554",
            "10.0.0.5@evil",
            None,
            5,
        ],
    )
    def test_invalid_ip(self, ldi: Any, ip: Any) -> None:
        assert ldi.valid_lan_ip(ip) is None

    @pytest.mark.parametrize("pw", [PW, "AbC123xyz", "p@ss/w:rd#?", "a" * 128])
    def test_valid_password(self, ldi: Any, pw: str) -> None:
        assert ldi.valid_password(pw) == pw

    @pytest.mark.parametrize(
        "pw",
        ["", " ", "has space", "tab\t", "new\nline", "\x00", "ü", "a" * 129, None, 5],
    )
    def test_invalid_password(self, ldi: Any, pw: Any) -> None:
        assert ldi.valid_password(pw) is None


class TestSource:
    def test_url_shape_and_quoting(self, ldi: Any) -> None:
        assert ldi.source_url("10.0.0.5", PW) == (
            "rtsps://localuser:test-pw@10.0.0.5:9554/live"
        )
        assert ldi.source_url("10.0.0.5", "a@b/c:d#") == (
            "rtsps://localuser:a%40b%2Fc%3Ad%23@10.0.0.5:9554/live"
        )

    def test_resolve_ok(self, ldi: Any) -> None:
        info = ldi.resolve_local_source(_cam(local_data_password=PW))
        assert info == {
            "url": "rtsps://localuser:test-pw@10.0.0.5:9554/live",
            "type": "LOCAL_DATA",
        }

    @pytest.mark.parametrize(
        "over",
        [
            {"local_data_password": ""},
            {"local_data_password": "bad pw"},
            {},
            {"local_data_password": PW, "local_ip": ""},
            {"local_data_password": PW, "local_ip": "127.0.0.1"},
            {"local_data_password": PW, "local_ip": "8.8.8.8"},
        ],
    )
    def test_resolve_none(self, ldi: Any, over: dict[str, Any]) -> None:
        assert ldi.resolve_local_source(_cam(**over)) is None

    def test_decision_matrix(self, ldi: Any) -> None:
        with_pw = _cam(local_data_password=PW)
        no_pw = _cam()
        # no status known -> cloud path, no hint
        assert not ldi.local_source_wanted(CAM_ID, with_pw)
        assert not ldi.needs_password(CAM_ID, no_pw)
        ldi._status_cache[CAM_ID] = {"state": "active"}
        assert ldi.local_source_wanted(CAM_ID, with_pw)
        assert not ldi.needs_password(CAM_ID, with_pw)
        assert not ldi.local_source_wanted(CAM_ID, no_pw)
        assert ldi.needs_password(CAM_ID, no_pw)
        for state in ("inactive", "unsupported"):
            ldi._status_cache[CAM_ID] = {"state": state}
            assert not ldi.local_source_wanted(CAM_ID, with_pw)
            assert not ldi.needs_password(CAM_ID, no_pw)

    def test_failure_messages_never_contain_password(self, ldi: Any) -> None:
        cam = _cam(local_data_password=PW, local_ip="")
        assert PW not in ldi.local_failure_message(cam)
        assert "LAN address" in ldi.local_failure_message(cam)
        ok = _cam(local_data_password=PW)
        assert PW not in ldi.local_failure_message(ok)
        assert "privacy" in ldi.local_failure_message(ok)
        assert PW not in ldi.MSG_NEED_PASSWORD


class TestRedaction:
    def test_redact(self, ldi: Any) -> None:
        text = "boom rtspx://localuser:test-pw@10.0.0.5:9554/live failed"
        out = ldi.redact_urls(text)
        assert PW not in out
        assert "rtspx://***@10.0.0.5:9554/live" in out

    def test_go2rtc_add_stream_logs_no_password(
        self, ldi: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        from bosch_camera_frontend.adapters.go2rtc_manager import Go2rtcManager

        mgr = Go2rtcManager()
        mgr.ensure_running = lambda: True  # type: ignore[method-assign]
        url = ldi.source_url("10.0.0.5", PW)

        def _boom(*_a: Any, **_k: Any) -> tuple[int, bytes]:
            return 500, f"cannot open {url}".encode()

        mgr._api_request = _boom  # type: ignore[method-assign]
        with caplog.at_level(logging.DEBUG):
            assert mgr.add_stream("cam", url) is False

        def _urlerr(*_a: Any, **_k: Any) -> tuple[int, bytes]:
            import urllib.error

            raise urllib.error.URLError(f"failed {url}")

        mgr._api_request = _urlerr  # type: ignore[method-assign]
        with caplog.at_level(logging.DEBUG):
            assert mgr.add_stream("cam", url) is False
        assert caplog.records
        assert PW not in caplog.text

    def test_status_fetch_logs_no_password(
        self, ldi: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        cam = _cam(local_data_password=PW)
        with caplog.at_level(logging.DEBUG):
            ldi.fetch_status(
                _session(exc=requests.ConnectionError("x")), cam, "https://c"
            )
        assert PW not in caplog.text
