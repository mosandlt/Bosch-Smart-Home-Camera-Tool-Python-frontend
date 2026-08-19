"""Tests for the firmware-status/install cli_bridge wrappers.

Added alongside the frontend's firmware-install feature (parity with the HA
sibling repo's Update entity + Repairs fix-flow, and the CLI's own
``firmware-update`` command). Mirrors the mocking pattern established in
test_cli_bridge_controls.py (fake bosch_camera module + fake requests.Session).
FAKE data only (SECRETS_SCAN).
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
    get_responses: list[MagicMock] | None = None,
) -> MagicMock:
    session = MagicMock()
    if get_responses is not None:
        session.get = MagicMock(side_effect=get_responses)
    elif get_response is not None:
        session.get = MagicMock(return_value=get_response)
    if put_response is not None:
        session.put = MagicMock(return_value=put_response)
    return session


# ---------------------------------------------------------------------------
# get_firmware_status
# ---------------------------------------------------------------------------


class TestGetFirmwareStatus:
    def test_200_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"current": "9.0.0", "upToDate": False, "update": "9.1.0"}
        resp = _fake_response(200, data)
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_firmware_status(session, FAKE_CAM_ID) == data

    def test_non_200_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        resp = _fake_response(444)
        session = _make_fake_session(get_response=resp)
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        assert cb.get_firmware_status(session, FAKE_CAM_ID) is None


# ---------------------------------------------------------------------------
# install_firmware
# ---------------------------------------------------------------------------


class TestInstallFirmware:
    def test_status_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(get_response=_fake_response(444))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.install_firmware(session, FAKE_CAM_ID)
        assert ok is False
        assert err == "Firmware status unavailable"

    def test_already_updating(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(200, {"current": "9.0.0", "updating": True})
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.install_firmware(session, FAKE_CAM_ID)
        assert ok is False
        assert err == "Install already in progress"

    def test_already_up_to_date_no_target(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(
                200, {"current": "9.0.0", "upToDate": True, "update": None}
            )
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.install_firmware(session, FAKE_CAM_ID)
        assert ok is False
        assert err == "Already up to date — nothing to install"

    def test_installs_pending_update(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(
                200, {"current": "9.0.0", "upToDate": False, "update": "9.1.0"}
            ),
            put_response=_fake_response(200),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.install_firmware(session, FAKE_CAM_ID)
        assert ok is True
        assert err is None
        session.put.assert_called_once()
        assert session.put.call_args.kwargs["json"] == {"id": "9.1.0"}

    def test_put_failure_maps_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(
                200, {"current": "9.0.0", "upToDate": False, "update": "9.1.0"}
            ),
            put_response=_fake_response(444),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = cb.install_firmware(session, FAKE_CAM_ID)
        assert ok is False
        assert err == "Camera offline"


# ---------------------------------------------------------------------------
# Async twins
# ---------------------------------------------------------------------------


class TestAsyncFirmware:
    async def test_async_get_firmware_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        data = {"current": "9.0.0", "upToDate": True}
        session = _make_fake_session(get_response=_fake_response(200, data))
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        result = await cb.async_get_firmware_status(session, FAKE_CAM_ID)
        assert result == data

    async def test_async_install_firmware(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as cb

        session = _make_fake_session(
            get_response=_fake_response(
                200, {"current": "9.0.0", "upToDate": False, "update": "9.1.0"}
            ),
            put_response=_fake_response(204),
        )
        monkeypatch.setattr(cb, "_bc", lambda: _make_fake_bc())

        ok, err = await cb.async_install_firmware(session, FAKE_CAM_ID)
        assert ok is True
        assert err is None
