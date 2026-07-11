"""Tests for the light / motion / intrusion / unread-count cli_bridge wrappers.

Added alongside the frontend's feature-parity wiring (light control, motion
detection, intrusion detection, unread-event badge). Mirrors the mocking
pattern established in test_cli_bridge.py (fake bosch_camera module + fake
requests.Session), kept in a separate file per this repo's per-concern test
file convention. FAKE data only (SECRETS_SCAN).
"""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import MagicMock

import pytest

FAKE_CLOUD_API = "https://api.example.com"
FAKE_CAM_ID = "11111111-2222-3333-4444-555555555555"


def _make_fake_bc(**overrides: Any) -> types.SimpleNamespace:
    ns = types.SimpleNamespace(CLOUD_API=FAKE_CLOUD_API)
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _fake_response(status_code: int = 200, json_data: Any = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data if json_data is not None else {})
    return resp


def _make_fake_session(
    get_response: MagicMock | None = None,
    put_response: MagicMock | None = None,
) -> MagicMock:
    session = MagicMock()
    if get_response is not None:
        session.get = MagicMock(return_value=get_response)
    if put_response is not None:
        session.put = MagicMock(return_value=put_response)
    return session


# ---------------------------------------------------------------------------
# Light override
# ---------------------------------------------------------------------------


class TestGetLightOverride:
    def test_200_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"frontLightOn": True, "wallwasherOn": False, "frontLightIntensity": 0.5}
        resp = _fake_response(200, data)
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        result = cb.get_light_override(session, FAKE_CAM_ID)
        assert result == data

    def test_non_200_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(503)
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_light_override(session, FAKE_CAM_ID) is None


class TestSetLightOverride:
    def test_204_returns_true_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(204)
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_light_override(session, FAKE_CAM_ID, front_on=True)
        assert ok is True
        assert err is None

    def test_on_payload_defaults_wall_and_intensity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(204)
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        cb.set_light_override(session, FAKE_CAM_ID, front_on=True)
        payload = session.put.call_args[1]["json"]
        assert payload == {
            "frontLightOn": True,
            "wallwasherOn": True,
            "frontLightIntensity": 1.0,
        }

    def test_off_payload_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(204)
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        cb.set_light_override(session, FAKE_CAM_ID, front_on=False)
        payload = session.put.call_args[1]["json"]
        assert payload == {
            "frontLightOn": False,
            "wallwasherOn": False,
            "frontLightIntensity": 0.0,
        }

    def test_explicit_wall_and_intensity_override_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(204)
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        cb.set_light_override(
            session, FAKE_CAM_ID, front_on=True, wall_on=False, intensity=0.3
        )
        payload = session.put.call_args[1]["json"]
        assert payload == {
            "frontLightOn": True,
            "wallwasherOn": False,
            "frontLightIntensity": 0.3,
        }

    def test_444_returns_camera_offline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(444, {"error": "sh:camera.busy"})
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_light_override(session, FAKE_CAM_ID, front_on=True)
        assert ok is False
        assert err == "Camera offline"

    def test_401_returns_auth_expired(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(401, {"error": ""})
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_light_override(session, FAKE_CAM_ID, front_on=True)
        assert ok is False
        assert err is not None
        assert "Auth expired" in err

    def test_403_returns_permission_denied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(403, {"error": ""})
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_light_override(session, FAKE_CAM_ID, front_on=True)
        assert ok is False
        assert err == "Permission denied"

    def test_other_status_http_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(500, {"error": "sh:server.error"})
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_light_override(session, FAKE_CAM_ID, front_on=True)
        assert ok is False
        assert err is not None
        assert "500" in err


# ---------------------------------------------------------------------------
# Unread count
# ---------------------------------------------------------------------------


class TestGetUnreadCount:
    def test_200_returns_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(200, {"numberOfUnreadEvents": 7})
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_unread_count(session, FAKE_CAM_ID) == 7

    def test_200_missing_field_defaults_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(200, {})
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_unread_count(session, FAKE_CAM_ID) == 0

    def test_non_200_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(401)
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_unread_count(session, FAKE_CAM_ID) is None


# ---------------------------------------------------------------------------
# Motion detection
# ---------------------------------------------------------------------------


class TestGetMotionDetection:
    def test_200_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"enabled": True, "motionAlarmConfiguration": "HIGH"}
        resp = _fake_response(200, data)
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_motion_detection(session, FAKE_CAM_ID) == data

    def test_non_200_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(500)
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_motion_detection(session, FAKE_CAM_ID) is None


class TestSetMotionDetection:
    def test_204_enable_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(204)
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_motion_detection(session, FAKE_CAM_ID, enabled=True)
        assert ok is True
        assert err is None
        payload = session.put.call_args[1]["json"]
        assert payload == {"enabled": True}

    def test_with_sensitivity_included_in_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(204)
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        cb.set_motion_detection(
            session, FAKE_CAM_ID, enabled=True, sensitivity="SUPER_HIGH"
        )
        payload = session.put.call_args[1]["json"]
        assert payload == {"enabled": True, "motionAlarmConfiguration": "SUPER_HIGH"}

    def test_disable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(204)
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_motion_detection(session, FAKE_CAM_ID, enabled=False)
        assert ok is True
        payload = session.put.call_args[1]["json"]
        assert payload == {"enabled": False}

    def test_error_status_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(401, {"error": ""})
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_motion_detection(session, FAKE_CAM_ID, enabled=True)
        assert ok is False
        assert err is not None


# ---------------------------------------------------------------------------
# Intrusion detection
# ---------------------------------------------------------------------------


class TestGetIntrusionDetection:
    def test_200_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {
            "enabled": True,
            "detectionMode": "ZONES",
            "sensitivity": 4,
            "distance": 6,
        }
        resp = _fake_response(200, data)
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_intrusion_detection(session, FAKE_CAM_ID) == data

    def test_442_unsupported_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(442)
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_intrusion_detection(session, FAKE_CAM_ID) is None


class TestSetIntrusionDetection:
    def test_204_enable_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(204)
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_intrusion_detection(session, FAKE_CAM_ID, enabled=True)
        assert ok is True
        assert err is None
        payload = session.put.call_args[1]["json"]
        assert payload == {"enabled": True}

    def test_full_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(204)
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        cb.set_intrusion_detection(
            session,
            FAKE_CAM_ID,
            enabled=True,
            detection_mode="ALL_MOTIONS",
            sensitivity=5,
            distance=7,
        )
        payload = session.put.call_args[1]["json"]
        assert payload == {
            "enabled": True,
            "detectionMode": "ALL_MOTIONS",
            "sensitivity": 5,
            "distance": 7,
        }

    def test_442_returns_not_supported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(442, {"error": ""})
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_intrusion_detection(session, FAKE_CAM_ID, enabled=True)
        assert ok is False
        assert err == "Not supported on this camera model"


# ---------------------------------------------------------------------------
# Async twins
# ---------------------------------------------------------------------------


class TestAsyncControlTwins:
    async def test_async_get_light_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"frontLightOn": True}
        resp = _fake_response(200, data)
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        result = await cb.async_get_light_override(session, FAKE_CAM_ID)
        assert result == data

    async def test_async_set_light_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(204)
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_set_light_override(session, FAKE_CAM_ID, True)
        assert ok is True
        assert err is None

    async def test_async_get_unread_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(200, {"numberOfUnreadEvents": 3})
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        result = await cb.async_get_unread_count(session, FAKE_CAM_ID)
        assert result == 3

    async def test_async_get_motion_detection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"enabled": False, "motionAlarmConfiguration": "OFF"}
        resp = _fake_response(200, data)
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        result = await cb.async_get_motion_detection(session, FAKE_CAM_ID)
        assert result == data

    async def test_async_set_motion_detection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(204)
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_set_motion_detection(session, FAKE_CAM_ID, True, "LOW")
        assert ok is True
        assert err is None

    async def test_async_get_intrusion_detection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"enabled": True, "sensitivity": 3, "distance": 5}
        resp = _fake_response(200, data)
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        result = await cb.async_get_intrusion_detection(session, FAKE_CAM_ID)
        assert result == data

    async def test_async_set_intrusion_detection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(204)
        session = _make_fake_session(put_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_set_intrusion_detection(
            session, FAKE_CAM_ID, True, "ZONES", 4, 6
        )
        assert ok is True
        assert err is None
