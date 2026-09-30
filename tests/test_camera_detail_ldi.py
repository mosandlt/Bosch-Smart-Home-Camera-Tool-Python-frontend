"""Camera detail page + settings page wiring of the local data interface.

FAKE DATA ONLY (cloud-ID 11111111-..., IP 10.0.0.x, password "test-pw").
"""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

TOKEN = "header.payload.signature"
PW = "test-pw"
CAM_ID = "11111111-2222-3333-4444-555555555555"
CLOUD_URL = "rtsps://proxy.invalid:443/abc/rtsp_tunnel"
LOCAL_URL = "rtsps://localuser:test-pw@10.0.0.5:9554/live"


def _cam(**over: Any) -> dict[str, Any]:
    cam: dict[str, Any] = {
        "id": CAM_ID,
        "name": "Test Cam",
        "model": "HOME_Eyes_Indoor",
        "firmware": "9.40.202",
        "local_ip": "10.0.0.5",
        "has_light": False,
        "pan_limit": 0,
        "nvr_recording_folder": "",
        "nvr_recording_enabled": False,
    }
    cam.update(over)
    return cam


class Rig:
    """Everything a test needs after rendering the page once."""

    def __init__(self) -> None:
        self.bridge = MagicMock()
        self.mgr = MagicMock()
        self.nvr = MagicMock()
        self.labels: list[Any] = []
        self.timers: list[Any] = []
        self.switches: list[Any] = []
        self.registered: list[str] = []
        self.snapshot_mounts = 0


async def _render(
    fake_nicegui: Any,
    monkeypatch: pytest.MonkeyPatch,
    cam: dict[str, Any],
    status: dict[str, Any] | None,
    *,
    go2rtc: bool = True,
    add_ok: bool = True,
    status_raises: bool = False,
) -> Rig:
    from nicegui import app, ui

    from bosch_camera_frontend.adapters import local_data_interface as ldi
    from bosch_camera_frontend.pages import camera_detail

    rig = Rig()
    app.storage.general.clear()
    app.storage.general["cfg"] = {
        "account": {"bearer_token": TOKEN},
        "cameras": {"Test Cam": cam},
    }
    app.storage.general["token"] = TOKEN

    b = rig.bridge
    b.make_session.return_value = MagicMock()

    async def _resolve(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"Test Cam": cam}

    async def _none(*_a: Any, **_k: Any) -> Any:
        return None

    async def _list(*_a: Any, **_k: Any) -> list[Any]:
        return []

    async def _status(*_a: Any, **_k: Any) -> dict[str, Any] | None:
        if status_raises:
            raise RuntimeError("boom")
        if status is not None:
            ldi._status_cache[CAM_ID] = status
        return status

    b.async_resolve_cam = _resolve
    b.async_snap_from_proxy = _none
    b.async_snap_from_events = AsyncMock(return_value=(None, ""))
    b.async_get_privacy_mode = AsyncMock(return_value="OFF")
    b.async_api_get_events = _list
    b.async_get_local_data_status = _status
    b.async_get_stream_url = AsyncMock(
        return_value={"url": CLOUD_URL, "type": "REMOTE"}
    )
    b.get_stream_url = MagicMock(return_value={"url": CLOUD_URL, "type": "LOCAL"})
    b.save_config = MagicMock()
    monkeypatch.setattr(camera_detail, "cli_bridge", b)

    rig.mgr.available = go2rtc
    rig.mgr.base_url = "http://127.0.0.1:1984"

    async def _add(name: str, url: str) -> bool:
        rig.registered.append(url)
        return add_ok

    rig.mgr.async_add_stream = MagicMock(side_effect=_add)
    rig.mgr.async_remove_stream = AsyncMock(return_value=True)
    monkeypatch.setattr(camera_detail, "get_manager", lambda: rig.mgr)
    rig.nvr.available = True
    rig.nvr.is_recording.return_value = False
    rig.nvr.async_start_recording = AsyncMock(return_value=True)
    monkeypatch.setattr(camera_detail, "get_nvr_manager", lambda: rig.nvr)

    class _Snap:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            rig.snapshot_mounts += 1

        def __enter__(self) -> "_Snap":
            return self

        def __exit__(self, *_e: Any) -> bool:
            return False

    monkeypatch.setattr(camera_detail, "LiveSnapshotPlayer", _Snap)

    orig_label, orig_timer, orig_switch = ui.label, ui.timer, ui.switch

    def cap_label(*a: Any, **k: Any) -> Any:
        inst = orig_label(*a, **k)
        rig.labels.append(inst)
        return inst

    def cap_timer(*a: Any, **k: Any) -> Any:
        cb = a[1] if len(a) > 1 else k.get("callback")
        if cb is not None and k.get("once"):
            rig.timers.append(cb)
        return orig_timer(*a, **k)

    def cap_switch(*a: Any, **k: Any) -> Any:
        inst = orig_switch(*a, **k)
        rig.switches.append(inst)
        return inst

    ui.label, ui.timer, ui.switch = cap_label, cap_timer, cap_switch  # type: ignore[assignment]
    try:
        await camera_detail.camera_detail_page("Test%20Cam")
        for cb in rig.timers:
            if getattr(cb, "__name__", "") == "_setup_live":
                await cb()
    finally:
        ui.label, ui.timer, ui.switch = orig_label, orig_timer, orig_switch  # type: ignore[assignment]
    return rig


def _texts(rig: Rig) -> list[str]:
    out: list[str] = []
    for lab in rig.labels:
        for name, args, _kw in lab.calls:
            if name == "set_text" and args:
                out.append(str(args[0]))
    return out


ACTIVE = {"state": "active", "username": "localuser"}


class TestLocalSource:
    async def test_active_with_password_reads_local_once(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cam = _cam(local_data_password=PW)
        rig = await _render(fake_nicegui, monkeypatch, cam, ACTIVE)
        assert rig.registered == [LOCAL_URL]
        rig.bridge.async_get_stream_url.assert_not_called()
        rig.bridge.get_stream_url.assert_not_called()
        assert rig.snapshot_mounts == 0
        assert not any(PW in t for t in _texts(rig))
        assert any("Local data interface: active" in t for t in _texts(rig))

    async def test_active_without_password_stays_on_cloud(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rig = await _render(fake_nicegui, monkeypatch, _cam(), ACTIVE)
        assert rig.registered == [CLOUD_URL]
        rig.bridge.async_get_stream_url.assert_awaited()
        assert any("set its password in Settings" in t for t in _texts(rig))

    @pytest.mark.parametrize("bad", ["bad pw", "x" * 200, "tab\t"])
    async def test_active_with_malformed_password_stays_on_cloud(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch, bad: str
    ) -> None:
        rig = await _render(
            fake_nicegui, monkeypatch, _cam(local_data_password=bad), ACTIVE
        )
        assert rig.registered == [CLOUD_URL]

    @pytest.mark.parametrize(
        "state", [{"state": "inactive"}, {"state": "unsupported"}, None]
    )
    async def test_not_active_is_unchanged_cloud_path(
        self,
        fake_nicegui: Any,
        monkeypatch: pytest.MonkeyPatch,
        state: dict[str, Any] | None,
    ) -> None:
        rig = await _render(
            fake_nicegui, monkeypatch, _cam(local_data_password=PW), state
        )
        assert rig.registered == [CLOUD_URL]
        assert not any("set its password" in t for t in _texts(rig))

    async def test_status_error_keeps_cloud_path(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rig = await _render(
            fake_nicegui,
            monkeypatch,
            _cam(local_data_password=PW),
            None,
            status_raises=True,
        )
        assert rig.registered == [CLOUD_URL]

    async def test_gen1_never_reads_local(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # status lookup returns nothing for ineligible cameras
        cam = _cam(model="CAMERA_EYES", local_data_password=PW)
        rig = await _render(fake_nicegui, monkeypatch, cam, None)
        assert rig.registered == [CLOUD_URL]

    async def test_fail_closed_when_go2rtc_missing(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rig = await _render(
            fake_nicegui,
            monkeypatch,
            _cam(local_data_password=PW),
            ACTIVE,
            go2rtc=False,
        )
        assert rig.registered == []
        assert rig.snapshot_mounts == 0
        rig.bridge.async_get_stream_url.assert_not_called()
        assert any("no cloud fallback" in t for t in _texts(rig))

    async def test_fail_closed_when_camera_refuses(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rig = await _render(
            fake_nicegui,
            monkeypatch,
            _cam(local_data_password=PW),
            ACTIVE,
            add_ok=False,
        )
        assert rig.snapshot_mounts == 0
        rig.bridge.async_get_stream_url.assert_not_called()
        texts = _texts(rig)
        assert any("privacy mode" in t for t in texts)
        assert not any(PW in t for t in texts)

    async def test_fail_closed_without_lan_ip(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cam = _cam(local_data_password=PW, local_ip="127.0.0.1")
        rig = await _render(fake_nicegui, monkeypatch, cam, ACTIVE)
        assert rig.registered == []
        rig.bridge.async_get_stream_url.assert_not_called()
        assert any("LAN address" in t for t in _texts(rig))

    async def test_failed_cloud_start_still_falls_back_to_snapshot(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rig = await _render(fake_nicegui, monkeypatch, _cam(), None, add_ok=False)
        assert rig.snapshot_mounts == 1


class TestNvrSource:
    async def _resolver(
        self,
        fake_nicegui: Any,
        monkeypatch: pytest.MonkeyPatch,
        cam: dict[str, Any],
        status: dict[str, Any] | None,
    ) -> tuple[Rig, Any]:
        rig = await _render(fake_nicegui, monkeypatch, cam, status)
        sw = next(
            s
            for s in rig.switches
            if s.init_args and s.init_args[0] == "Continuous Recording"
        )
        handler = next(c[1][0] for c in reversed(sw.calls) if c[0] == "on_value_change")
        res = handler(types.SimpleNamespace(value=True))
        if hasattr(res, "__await__"):
            await res
        return rig, rig.nvr.async_start_recording.call_args[0][1]

    async def test_local_when_active_with_password(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rig, resolver = await self._resolver(
            fake_nicegui, monkeypatch, _cam(local_data_password=PW), ACTIVE
        )
        assert resolver() == {"url": LOCAL_URL, "type": "LOCAL_DATA"}
        rig.bridge.get_stream_url.assert_not_called()

    async def test_fail_closed_with_bad_ip(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cam = _cam(local_data_password=PW, local_ip="8.8.8.8")
        rig, resolver = await self._resolver(fake_nicegui, monkeypatch, cam, ACTIVE)
        assert resolver() is None
        rig.bridge.get_stream_url.assert_not_called()

    @pytest.mark.parametrize("state", [{"state": "inactive"}, None])
    async def test_cloud_otherwise(
        self,
        fake_nicegui: Any,
        monkeypatch: pytest.MonkeyPatch,
        state: dict[str, Any] | None,
    ) -> None:
        rig, resolver = await self._resolver(
            fake_nicegui, monkeypatch, _cam(local_data_password=PW), state
        )
        assert resolver() == {"url": CLOUD_URL, "type": "LOCAL"}


class TestSettingsCard:
    async def _render(
        self, fake_nicegui: Any, cameras: dict[str, dict[str, Any]]
    ) -> tuple[dict[str, Any], MagicMock, list[Any], list[Any]]:
        from nicegui import app, ui

        from bosch_camera_frontend.pages import settings

        cfg: dict[str, Any] = {"language": "en", "cameras": cameras}
        app.storage.general.clear()
        app.storage.general["cfg"] = cfg
        bridge = MagicMock()
        bridge.detect_lang.return_value = "en"
        bridge.check_token_age.return_value = "ok"
        settings.cli_bridge = bridge

        inputs: list[Any] = []
        buttons: list[Any] = []
        orig_input, orig_button = ui.input, ui.button

        def cap_input(*a: Any, **k: Any) -> Any:
            inst = orig_input(*a, **k)
            inputs.append(inst)
            return inst

        def cap_button(*a: Any, **k: Any) -> Any:
            inst = orig_button(*a, **k)
            buttons.append(inst)
            return inst

        ui.input, ui.button = cap_input, cap_button  # type: ignore[assignment]
        try:
            await settings.settings_page()
        finally:
            ui.input, ui.button = orig_input, orig_button  # type: ignore[assignment]
        return cfg, bridge, inputs, buttons

    @staticmethod
    def _save_click(buttons: list[Any]) -> Any:
        save = next(b for b in buttons if b.init_args and b.init_args[0] == "Save")
        return save.init_kwargs["on_click"]

    async def test_only_gen2_listed_and_masked(self, fake_nicegui: Any) -> None:
        cams = {
            "Gen2": _cam(local_data_password=PW),
            "Gen1": _cam(model="CAMERA_EYES"),
        }
        _cfg, _b, inputs, _btn = await self._render(fake_nicegui, cams)
        pw_inputs = [i for i in inputs if i.init_kwargs.get("label") == "Password"]
        assert len(pw_inputs) == 1
        field = pw_inputs[0]
        assert field.init_kwargs["password"] is True
        assert field.init_kwargs["placeholder"] == "saved"
        assert field.value is None  # stored value never prefilled
        assert PW not in repr(field.init_kwargs)

    async def test_no_supported_cameras(self, fake_nicegui: Any) -> None:
        _cfg, _b, inputs, _btn = await self._render(
            fake_nicegui, {"Gen1": _cam(model="CAMERA_EYES")}
        )
        assert not [i for i in inputs if i.init_kwargs.get("label") == "Password"]

    async def test_save_persists(self, fake_nicegui: Any) -> None:
        cfg, bridge, inputs, buttons = await self._render(
            fake_nicegui, {"Gen2": _cam()}
        )
        field = next(i for i in inputs if i.init_kwargs.get("label") == "Password")
        assert field.init_kwargs["placeholder"] == "not set"
        field.value = f"  {PW}  "
        self._save_click(buttons)()
        assert cfg["cameras"]["Gen2"]["local_data_password"] == PW
        bridge.save_config.assert_called_once_with(cfg)
        assert field.value == ""

    async def test_clear(self, fake_nicegui: Any) -> None:
        cfg, bridge, inputs, buttons = await self._render(
            fake_nicegui, {"Gen2": _cam(local_data_password=PW)}
        )
        field = next(i for i in inputs if i.init_kwargs.get("label") == "Password")
        field.value = ""
        self._save_click(buttons)()
        assert cfg["cameras"]["Gen2"]["local_data_password"] == ""
        bridge.save_config.assert_called_once()

    @pytest.mark.parametrize("bad", ["two words", "x" * 200, "ü"])
    async def test_invalid_format_rejected(self, fake_nicegui: Any, bad: str) -> None:
        cfg, bridge, inputs, buttons = await self._render(
            fake_nicegui, {"Gen2": _cam()}
        )
        field = next(i for i in inputs if i.init_kwargs.get("label") == "Password")
        field.value = bad
        self._save_click(buttons)()
        assert "local_data_password" not in cfg["cameras"]["Gen2"]
        bridge.save_config.assert_not_called()

    async def test_save_error_reported_without_password(
        self, fake_nicegui: Any
    ) -> None:
        from nicegui import ui

        cfg, bridge, inputs, buttons = await self._render(
            fake_nicegui, {"Gen2": _cam()}
        )
        bridge.save_config.side_effect = OSError("disk")
        notes: list[tuple[Any, ...]] = []
        orig = ui.notify
        ui.notify = lambda *a, **k: notes.append(a)  # type: ignore[assignment]
        try:
            field = next(i for i in inputs if i.init_kwargs.get("label") == "Password")
            field.value = PW
            self._save_click(buttons)()
        finally:
            ui.notify = orig  # type: ignore[assignment]
        assert notes
        assert all(PW not in str(n) for n in notes)


class TestBridge:
    def test_get_local_data_status_uses_cloud_api(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bosch_camera_frontend.adapters import cli_bridge as cb
        from bosch_camera_frontend.adapters.local_data_interface import LDI_ENDPOINT

        monkeypatch.setattr(
            cb, "_bc", lambda: types.SimpleNamespace(CLOUD_API="https://c.invalid")
        )
        resp = MagicMock(status_code=404)
        session = MagicMock()
        session.get.return_value = resp
        assert cb.get_local_data_status(session, _cam()) == {"state": "inactive"}
        assert session.get.call_args[0][0] == (
            f"https://c.invalid/v11/video_inputs/{CAM_ID}/{LDI_ENDPOINT}"
        )

    async def test_async_twin(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bosch_camera_frontend.adapters import cli_bridge as cb

        monkeypatch.setattr(
            cb, "_bc", lambda: types.SimpleNamespace(CLOUD_API="https://c.invalid")
        )
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=449)
        assert await cb.async_get_local_data_status(session, _cam()) == {
            "state": "unsupported"
        }

    def test_get_cameras_preserves_password(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bosch_camera_frontend.adapters import cli_bridge as cb

        monkeypatch.setattr(
            cb, "_bc", lambda: types.SimpleNamespace(CLOUD_API="https://c.invalid")
        )
        resp = MagicMock(status_code=200)
        resp.json.return_value = [{"id": CAM_ID, "title": "Test Cam"}]
        session = MagicMock()
        session.get.return_value = resp
        cfg = {"cameras": {"Test Cam": {"id": CAM_ID, "local_data_password": PW}}}
        out = cb.get_cameras(cfg, session)
        assert out["Test Cam"]["local_data_password"] == PW
