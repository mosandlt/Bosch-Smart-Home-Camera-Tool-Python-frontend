"""Tests for the v0.3.0-alpha family-parity batch cli_bridge wrappers:

glass-break/fire-alarm sound detection, wifi info, lighting schedule,
cloud recording (sound), siren + duration, pan, feature flags, automation
rules CRUD, friends/sharing CRUD.

Mirrors the mocking pattern established in test_cli_bridge_controls.py (fake
bosch_camera module + fake requests.Session). FAKE data only (SECRETS_SCAN).
"""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import MagicMock

import pytest

FAKE_CLOUD_API = "https://api.example.com"
FAKE_CAM_ID = "11111111-2222-3333-4444-555555555555"
FAKE_FRIEND_ID = "friend-aaaa-bbbb"
FAKE_RULE_ID = "rule-cccc-dddd"


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
    get_responses: list[MagicMock] | None = None,
    put_response: MagicMock | None = None,
    post_response: MagicMock | None = None,
    delete_response: MagicMock | None = None,
) -> MagicMock:
    session = MagicMock()
    if get_responses is not None:
        session.get = MagicMock(side_effect=get_responses)
    elif get_response is not None:
        session.get = MagicMock(return_value=get_response)
    if put_response is not None:
        session.put = MagicMock(return_value=put_response)
    if post_response is not None:
        session.post = MagicMock(return_value=post_response)
    if delete_response is not None:
        session.delete = MagicMock(return_value=delete_response)
    return session


# ---------------------------------------------------------------------------
# Glass-break / fire-alarm sound detection
# ---------------------------------------------------------------------------


class TestAudioDetection:
    def test_get_200_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"detectGlassBreak": True, "detectFireAlarm": False}
        session = _make_fake_session(get_response=_fake_response(200, data))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_audio_detection(session, FAKE_CAM_ID) == data

    def test_get_442_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(442))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_audio_detection(session, FAKE_CAM_ID) is None

    def test_set_sends_both_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(put_response=_fake_response(204))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_audio_detection(
            session, FAKE_CAM_ID, glass_break=True, fire_alarm=False
        )
        assert ok is True
        assert err is None
        payload = session.put.call_args[1]["json"]
        assert payload == {"detectGlassBreak": True, "detectFireAlarm": False}

    def test_set_442_returns_not_supported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(put_response=_fake_response(442, {"error": ""}))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_audio_detection(session, FAKE_CAM_ID, True, True)
        assert ok is False
        assert err == "Not supported on this camera model"


# ---------------------------------------------------------------------------
# WiFi info
# ---------------------------------------------------------------------------


class TestWifiInfo:
    def test_200_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"ssid": "TestNet", "rssi": -60}
        session = _make_fake_session(get_response=_fake_response(200, data))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_wifi_info(session, FAKE_CAM_ID) == data

    def test_442_wired_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(442))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_wifi_info(session, FAKE_CAM_ID) is None


# ---------------------------------------------------------------------------
# Lighting schedule
# ---------------------------------------------------------------------------


class TestLightingSchedule:
    def test_get_200_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"scheduleStatus": "FOLLOW_SCHEDULE", "generalLightOnTime": "18:00:00"}
        session = _make_fake_session(get_response=_fake_response(200, data))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_lighting_schedule(session, FAKE_CAM_ID) == data

    def test_get_444_offline_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(444))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_lighting_schedule(session, FAKE_CAM_ID) is None

    def test_set_merges_and_appends_seconds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        current = {
            "generalLightOnTime": "18:00:00",
            "generalLightOffTime": "06:00:00",
            "darknessThreshold": 0.3,
            "lightOnMotion": False,
        }
        session = _make_fake_session(
            get_response=_fake_response(200, current),
            put_response=_fake_response(204),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_lighting_schedule(session, FAKE_CAM_ID, on_time="19:00")
        assert ok is True
        assert err is None
        payload = session.put.call_args[1]["json"]
        assert payload["generalLightOnTime"] == "19:00:00"
        assert payload["generalLightOffTime"] == "06:00:00"  # preserved
        assert payload["scheduleStatus"] == "FOLLOW_SCHEDULE"

    def test_set_get_fails_still_proceeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed GET (best-effort fetch) shouldn't block the PUT."""
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(500),
            put_response=_fake_response(204),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_lighting_schedule(session, FAKE_CAM_ID, off_time="05:30:00")
        assert ok is True
        payload = session.put.call_args[1]["json"]
        assert payload["generalLightOffTime"] == "05:30:00"

    def test_set_put_failure_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, {}),
            put_response=_fake_response(500, {"error": "x"}),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_lighting_schedule(session, FAKE_CAM_ID, on_time="19:00")
        assert ok is False
        assert err is not None

    def test_set_light_on_motion_and_darkness_threshold(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, {}),
            put_response=_fake_response(204),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_lighting_schedule(
            session, FAKE_CAM_ID, light_on_motion=True, darkness_threshold=0.6
        )
        assert ok is True
        payload = session.put.call_args[1]["json"]
        assert payload["lightOnMotion"] is True
        assert payload["darknessThreshold"] == 0.6


# ---------------------------------------------------------------------------
# Cloud recording options (sound)
# ---------------------------------------------------------------------------


class TestRecordingOptions:
    def test_get_200_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, {"recordSound": True})
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_recording_options(session, FAKE_CAM_ID) == {"recordSound": True}

    def test_get_non_200_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(500))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_recording_options(session, FAKE_CAM_ID) is None

    def test_set_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(put_response=_fake_response(204))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_recording_options(session, FAKE_CAM_ID, sound_on=False)
        assert ok is True
        assert session.put.call_args[1]["json"] == {"recordSound": False}

    def test_set_failure_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(put_response=_fake_response(500, {"error": "x"}))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_recording_options(session, FAKE_CAM_ID, sound_on=True)
        assert ok is False
        assert err is not None


# ---------------------------------------------------------------------------
# Siren + alarm duration
# ---------------------------------------------------------------------------


class TestSiren:
    def test_trigger_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(put_response=_fake_response(204))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.trigger_siren(session, FAKE_CAM_ID)
        assert ok is True
        assert session.put.call_args[1]["json"] == {"status": "ON"}

    def test_trigger_stop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(put_response=_fake_response(204))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        cb.trigger_siren(session, FAKE_CAM_ID, stop=True)
        assert session.put.call_args[1]["json"] == {"status": "OFF"}

    def test_trigger_443_privacy_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            put_response=_fake_response(443, {"error": "sh:camera.in.privacy.mode"})
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.trigger_siren(session, FAKE_CAM_ID)
        assert ok is False
        assert err is not None

    def test_get_alarm_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, {"alarmDelayInSeconds": 30})
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_alarm_settings(session, FAKE_CAM_ID) == {
            "alarmDelayInSeconds": 30
        }

    def test_set_duration_preserves_other_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, {"alarmDelayInSeconds": 30, "other": "x"}),
            put_response=_fake_response(204),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_siren_duration(session, FAKE_CAM_ID, 120)
        assert ok is True
        payload = session.put.call_args[1]["json"]
        assert payload == {"alarmDelayInSeconds": 120, "other": "x"}

    def test_set_duration_get_fails_still_proceeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(500),
            put_response=_fake_response(204),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_siren_duration(session, FAKE_CAM_ID, 60)
        assert ok is True
        assert session.put.call_args[1]["json"] == {"alarmDelayInSeconds": 60}

    def test_set_duration_put_failure_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, {}),
            put_response=_fake_response(500, {"error": "x"}),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_siren_duration(session, FAKE_CAM_ID, 60)
        assert ok is False
        assert err is not None


# ---------------------------------------------------------------------------
# Pan
# ---------------------------------------------------------------------------


class TestPan:
    def test_get_200_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"currentAbsolutePosition": 45, "panLimit": 170}
        session = _make_fake_session(get_response=_fake_response(200, data))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_pan(session, FAKE_CAM_ID) == data

    def test_get_442_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(442))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_pan(session, FAKE_CAM_ID) is None

    def test_set_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(put_response=_fake_response(204))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_pan(session, FAKE_CAM_ID, -60)
        assert ok is True
        assert session.put.call_args[1]["json"] == {"absolutePosition": -60}

    def test_set_failure_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(put_response=_fake_response(442, {"error": ""}))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.set_pan(session, FAKE_CAM_ID, 999)
        assert ok is False
        assert err is not None


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------


class TestFeatureFlags:
    def test_200_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"someFlag": True}
        session = _make_fake_session(get_response=_fake_response(200, data))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_feature_flags(session) == data

    def test_non_200_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(500))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_feature_flags(session) is None

    def test_list_of_dicts_normalized_by_name_and_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bug-hunt finding 2026-07-11: Bosch can return a LIST here instead
        of a dict — a bare cast() would silently produce a dict-typed list
        that crashes on the first .get() call. Must be flattened like the
        CLI's cmd_feature_flags does."""
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = [
            {"name": "featureA", "value": True},
            {"key": "featureB", "enabled": False},
        ]
        session = _make_fake_session(get_response=_fake_response(200, data))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        result = cb.get_feature_flags(session)
        assert result == {"featureA": True, "featureB": False}

    def test_list_of_scalars_treated_as_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, ["featureA", "featureB"])
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        result = cb.get_feature_flags(session)
        assert result == {"featureA": True, "featureB": True}

    def test_unexpected_type_wrapped_as_raw(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(200, "unexpected"))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        result = cb.get_feature_flags(session)
        assert result == {"raw": "unexpected"}


# ---------------------------------------------------------------------------
# Rules CRUD
# ---------------------------------------------------------------------------


class TestRules:
    def test_list_returns_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = [{"id": FAKE_RULE_ID, "name": "Night", "isActive": True}]
        session = _make_fake_session(get_response=_fake_response(200, data))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.list_rules(session, FAKE_CAM_ID) == data

    def test_list_dict_wrapped_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"items": [{"id": FAKE_RULE_ID}]}
        session = _make_fake_session(get_response=_fake_response(200, data))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.list_rules(session, FAKE_CAM_ID) == [{"id": FAKE_RULE_ID}]

    def test_list_non_200_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(500))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.list_rules(session, FAKE_CAM_ID) is None

    def test_add_rule_payload_and_time_padding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(post_response=_fake_response(201))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.add_rule(
            session,
            FAKE_CAM_ID,
            name="Night",
            start="22:00",
            end="06:00",
            weekdays=[0, 1],
        )
        assert ok is True
        payload = session.post.call_args[1]["json"]
        assert payload == {
            "id": None,
            "name": "Night",
            "isActive": True,
            "startTime": "22:00:00",
            "endTime": "06:00:00",
            "weekdays": [0, 1],
        }

    def test_edit_rule_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(200, []))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.edit_rule(session, FAKE_CAM_ID, "nonexistent", name="X")
        assert ok is False
        assert err == "Rule not found"

    def test_edit_rule_merges_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        existing = [
            {
                "id": FAKE_RULE_ID,
                "name": "Old",
                "isActive": True,
                "startTime": "22:00:00",
                "endTime": "06:00:00",
                "weekdays": [0],
            }
        ]
        session = _make_fake_session(
            get_response=_fake_response(200, existing),
            put_response=_fake_response(204),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.edit_rule(session, FAKE_CAM_ID, FAKE_RULE_ID, name="New")
        assert ok is True
        payload = session.put.call_args[1]["json"]
        assert payload["name"] == "New"
        assert payload["startTime"] == "22:00:00"  # preserved

    def test_edit_rule_all_fields_and_time_padding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        existing = [
            {
                "id": FAKE_RULE_ID,
                "name": "Old",
                "isActive": False,
                "startTime": "22:00:00",
                "endTime": "06:00:00",
                "weekdays": [0],
            }
        ]
        session = _make_fake_session(
            get_response=_fake_response(200, existing),
            put_response=_fake_response(204),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.edit_rule(
            session,
            FAKE_CAM_ID,
            FAKE_RULE_ID,
            start="21:00",
            end="07:00",
            weekdays=[1, 2],
            active=True,
        )
        assert ok is True
        payload = session.put.call_args[1]["json"]
        assert payload["startTime"] == "21:00:00"
        assert payload["endTime"] == "07:00:00"
        assert payload["weekdays"] == [1, 2]
        assert payload["isActive"] is True

    def test_edit_rule_put_failure_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        existing = [{"id": FAKE_RULE_ID, "name": "Old"}]
        session = _make_fake_session(
            get_response=_fake_response(200, existing),
            put_response=_fake_response(500, {"error": "x"}),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.edit_rule(session, FAKE_CAM_ID, FAKE_RULE_ID, name="New")
        assert ok is False
        assert err is not None

    def test_add_rule_failure_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(post_response=_fake_response(500, {"error": "x"}))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.add_rule(
            session, FAKE_CAM_ID, name="N", start="22:00", end="06:00", weekdays=[0]
        )
        assert ok is False
        assert err is not None

    def test_delete_rule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(delete_response=_fake_response(204))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.delete_rule(session, FAKE_CAM_ID, FAKE_RULE_ID)
        assert ok is True
        session.delete.assert_called_once()

    def test_delete_rule_failure_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            delete_response=_fake_response(500, {"error": "x"})
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.delete_rule(session, FAKE_CAM_ID, FAKE_RULE_ID)
        assert ok is False
        assert err is not None


# ---------------------------------------------------------------------------
# Friends / sharing CRUD
# ---------------------------------------------------------------------------


class TestFriends:
    def test_list_returns_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = [{"id": FAKE_FRIEND_ID, "nickName": "Bob"}]
        session = _make_fake_session(get_response=_fake_response(200, data))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.list_friends(session) == data

    def test_list_non_200_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(401))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.list_friends(session) is None

    def test_invite_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(post_response=_fake_response(201))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.invite_friend(session, "bob@example.com", "Bob")
        assert ok is True
        assert session.post.call_args[1]["json"] == {
            "invitationEmail": "bob@example.com",
            "nickName": "Bob",
        }

    def test_invite_failure_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(post_response=_fake_response(500, {"error": "x"}))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.invite_friend(session, "bob@example.com")
        assert ok is False
        assert err is not None

    def test_remove_friend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(delete_response=_fake_response(204))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.remove_friend(session, FAKE_FRIEND_ID)
        assert ok is True
        session.delete.assert_called_once()

    def test_remove_friend_failure_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            delete_response=_fake_response(500, {"error": "x"})
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.remove_friend(session, FAKE_FRIEND_ID)
        assert ok is False
        assert err is not None

    def test_share_camera_appends_when_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        friends = [{"id": FAKE_FRIEND_ID, "sharedVideoInputs": []}]
        session = _make_fake_session(
            get_response=_fake_response(200, friends),
            put_response=_fake_response(204),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.share_camera(session, FAKE_FRIEND_ID, FAKE_CAM_ID)
        assert ok is True
        payload = session.put.call_args[1]["json"]
        assert payload == [{"videoInputId": FAKE_CAM_ID}]

    def test_share_camera_no_duplicate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        friends = [
            {"id": FAKE_FRIEND_ID, "sharedVideoInputs": [{"videoInputId": FAKE_CAM_ID}]}
        ]
        session = _make_fake_session(
            get_response=_fake_response(200, friends),
            put_response=_fake_response(204),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        cb.share_camera(session, FAKE_FRIEND_ID, FAKE_CAM_ID)
        payload = session.put.call_args[1]["json"]
        assert payload == [{"videoInputId": FAKE_CAM_ID}]

    def test_unshare_camera_removes_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        friends = [
            {
                "id": FAKE_FRIEND_ID,
                "sharedVideoInputs": [
                    {"videoInputId": FAKE_CAM_ID},
                    {"videoInputId": "other-cam"},
                ],
            }
        ]
        session = _make_fake_session(
            get_response=_fake_response(200, friends),
            put_response=_fake_response(204),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.unshare_camera(session, FAKE_FRIEND_ID, FAKE_CAM_ID)
        assert ok is True
        payload = session.put.call_args[1]["json"]
        assert payload == [{"videoInputId": "other-cam"}]

    def test_share_camera_friend_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, []),
            put_response=_fake_response(204),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.share_camera(session, "nonexistent", FAKE_CAM_ID)
        assert ok is True  # PUT still sent with just the new entry, no crash
        payload = session.put.call_args[1]["json"]
        assert payload == [{"videoInputId": FAKE_CAM_ID}]

    def test_share_camera_failure_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, []),
            put_response=_fake_response(500, {"error": "x"}),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.share_camera(session, FAKE_FRIEND_ID, FAKE_CAM_ID)
        assert ok is False
        assert err is not None

    def test_unshare_camera_failure_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, []),
            put_response=_fake_response(500, {"error": "x"}),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.unshare_camera(session, FAKE_FRIEND_ID, FAKE_CAM_ID)
        assert ok is False
        assert err is not None


# ---------------------------------------------------------------------------
# Async twins (smoke coverage for the whole batch)
# ---------------------------------------------------------------------------


class TestAsyncParityBatchTwins:
    async def test_async_get_audio_detection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"detectGlassBreak": True, "detectFireAlarm": True}
        session = _make_fake_session(get_response=_fake_response(200, data))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert await cb.async_get_audio_detection(session, FAKE_CAM_ID) == data

    async def test_async_set_audio_detection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(put_response=_fake_response(204))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_set_audio_detection(session, FAKE_CAM_ID, True, False)
        assert ok is True

    async def test_async_get_wifi_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(200, {"ssid": "x"}))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert await cb.async_get_wifi_info(session, FAKE_CAM_ID) == {"ssid": "x"}

    async def test_async_get_lighting_schedule(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, {"scheduleStatus": "X"})
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert await cb.async_get_lighting_schedule(session, FAKE_CAM_ID) == {
            "scheduleStatus": "X"
        }

    async def test_async_set_lighting_schedule(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, {}), put_response=_fake_response(204)
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_set_lighting_schedule(
            session, FAKE_CAM_ID, on_time="18:00"
        )
        assert ok is True

    async def test_async_get_recording_options(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, {"recordSound": True})
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert await cb.async_get_recording_options(session, FAKE_CAM_ID) == {
            "recordSound": True
        }

    async def test_async_set_recording_options(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(put_response=_fake_response(204))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_set_recording_options(session, FAKE_CAM_ID, True)
        assert ok is True

    async def test_async_trigger_siren(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(put_response=_fake_response(204))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_trigger_siren(session, FAKE_CAM_ID)
        assert ok is True

    async def test_async_get_alarm_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, {"alarmDelayInSeconds": 30})
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        result = await cb.async_get_alarm_settings(session, FAKE_CAM_ID)
        assert result == {"alarmDelayInSeconds": 30}

    async def test_async_set_siren_duration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, {}), put_response=_fake_response(204)
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_set_siren_duration(session, FAKE_CAM_ID, 90)
        assert ok is True

    async def test_async_get_pan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, {"currentAbsolutePosition": 0})
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        result = await cb.async_get_pan(session, FAKE_CAM_ID)
        assert result == {"currentAbsolutePosition": 0}

    async def test_async_set_pan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(put_response=_fake_response(204))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_set_pan(session, FAKE_CAM_ID, 30)
        assert ok is True

    async def test_async_get_feature_flags(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(200, {"flag": True}))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert await cb.async_get_feature_flags(session) == {"flag": True}

    async def test_async_list_rules(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(200, []))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert await cb.async_list_rules(session, FAKE_CAM_ID) == []

    async def test_async_add_rule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(post_response=_fake_response(201))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_add_rule(
            session, FAKE_CAM_ID, "N", "22:00", "06:00", [0]
        )
        assert ok is True

    async def test_async_edit_rule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(200, []))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_edit_rule(session, FAKE_CAM_ID, "missing", name="X")
        assert ok is False

    async def test_async_delete_rule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(delete_response=_fake_response(204))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_delete_rule(session, FAKE_CAM_ID, FAKE_RULE_ID)
        assert ok is True

    async def test_async_list_friends(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(200, []))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert await cb.async_list_friends(session) == []

    async def test_async_invite_friend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(post_response=_fake_response(201))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_invite_friend(session, "a@example.com", "A")
        assert ok is True

    async def test_async_remove_friend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(delete_response=_fake_response(204))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_remove_friend(session, FAKE_FRIEND_ID)
        assert ok is True

    async def test_async_share_camera(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, []), put_response=_fake_response(204)
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_share_camera(session, FAKE_FRIEND_ID, FAKE_CAM_ID)
        assert ok is True

    async def test_async_unshare_camera(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, []), put_response=_fake_response(204)
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_unshare_camera(session, FAKE_FRIEND_ID, FAKE_CAM_ID)
        assert ok is True
