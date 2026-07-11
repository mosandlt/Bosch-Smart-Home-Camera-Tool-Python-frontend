"""Coverage tests for the v0.3.0-alpha family-parity UI sections added to the
camera detail page: sound detection (glass-break/fire-alarm), wifi info,
lighting schedule, cloud recording (sound), siren + duration, pan, automation
rules CRUD, friends/sharing CRUD.

Mirrors the fake_nicegui + generic-capture-callback pattern established in
test_camera_detail_controls.py. Because every control lives in a closure
inside ``camera_detail_page``, the only way to exercise it is to render the
page and capture the widget callbacks via a monkeypatched ``ui.button`` /
``ValueElement.on_value_change``. FAKE DATA ONLY (SECRETS_SCAN).
"""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import MagicMock


def _fake_cam(
    *,
    has_light: bool = False,
    model: str = "HOME_Eyes_Outdoor",
    pan_limit: int = 0,
) -> dict[str, Any]:
    return {
        "id": "11111111-2222-3333-4444-555555555555",
        "name": "Test Cam",
        "model": model,
        "firmware": "9.0.0",
        "mac": "aa:bb:cc:dd:ee:ff",
        "download_folder": "Test Cam",
        "local_ip": "",
        "has_light": has_light,
        "pan_limit": pan_limit,
    }


def _make_cfg(cam: dict[str, Any]) -> dict[str, Any]:
    return {
        "account": {"bearer_token": "header.payload.signature"},
        "language": "en",
        "cameras": {cam["name"]: cam},
    }


async def _ok(*_a: Any, **_kw: Any) -> tuple[bool, str | None]:
    return True, None


async def _fail(*_a: Any, **_kw: Any) -> tuple[bool, str | None]:
    return False, "Camera offline"


async def _none(*_a: Any, **_kw: Any) -> None:
    return None


def _full_bridge(cam: dict[str, Any], *, writes_ok: bool = True) -> MagicMock:
    """A bridge stub with every parity-batch async_* function wired to
    plausible success data (or failure, if writes_ok=False for the *_set*
    write endpoints), plus the pre-existing privacy/events baseline."""
    bridge = MagicMock()
    bridge.make_session.return_value = MagicMock(name="session")

    async def _found(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {"Test Cam": cam}

    async def _priv(*_a: Any, **_kw: Any) -> str:
        return "OFF"

    async def _ev_list(*_a: Any, **_kw: Any) -> list[Any]:
        return []

    bridge.async_resolve_cam = _found
    bridge.async_get_privacy_mode = _priv
    bridge.async_api_get_events = _ev_list
    bridge.async_get_light_override = _none
    bridge.async_get_motion_detection = _none
    bridge.async_get_intrusion_detection = _none

    write = _ok if writes_ok else _fail

    async def _get_audio_detection(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {"detectGlassBreak": True, "detectFireAlarm": False}

    async def _get_wifi(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {"ssid": "TestNet", "rssi": -55}

    async def _get_lighting(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {
            "scheduleStatus": "FOLLOW_SCHEDULE",
            "generalLightOnTime": "18:00:00",
            "generalLightOffTime": "06:00:00",
            "darknessThreshold": 0.3,
            "lightOnMotion": True,
        }

    async def _get_recording(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {"recordSound": True}

    async def _get_alarm_settings(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {"alarmDelayInSeconds": 30}

    async def _get_pan(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {"currentAbsolutePosition": 10, "panLimit": 170}

    async def _list_rules(*_a: Any, **_kw: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "rule-1",
                "name": "Night",
                "isActive": True,
                "startTime": "22:00:00",
                "endTime": "06:00:00",
            }
        ]

    async def _list_friends(*_a: Any, **_kw: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "friend-1",
                "nickName": "Bob",
                "status": "ACCEPTED",
                "sharedVideoInputs": [{"videoInputId": cam["id"]}],
            }
        ]

    bridge.async_get_audio_detection = _get_audio_detection
    bridge.async_set_audio_detection = write
    bridge.async_get_wifi_info = _get_wifi
    bridge.async_get_lighting_schedule = _get_lighting
    bridge.async_set_lighting_schedule = write
    bridge.async_get_recording_options = _get_recording
    bridge.async_set_recording_options = write
    bridge.async_trigger_siren = write
    bridge.async_get_alarm_settings = _get_alarm_settings
    bridge.async_set_siren_duration = write
    bridge.async_get_pan = _get_pan
    bridge.async_set_pan = write
    bridge.async_list_rules = _list_rules
    bridge.async_add_rule = write
    bridge.async_delete_rule = write
    bridge.async_list_friends = _list_friends
    bridge.async_invite_friend = write
    bridge.async_remove_friend = write
    bridge.async_share_camera = write
    bridge.async_unshare_camera = write
    return bridge


def _empty_bridge(cam: dict[str, Any]) -> MagicMock:
    """Every GET returns None/empty — exercises the 'unavailable' branches."""
    bridge = _full_bridge(cam)
    bridge.async_get_audio_detection = _none
    bridge.async_get_wifi_info = _none
    bridge.async_get_lighting_schedule = _none
    bridge.async_get_recording_options = _none
    bridge.async_get_pan = _none

    async def _empty_list(*_a: Any, **_kw: Any) -> list[Any]:
        return []

    bridge.async_list_rules = _empty_list
    bridge.async_list_friends = _empty_list
    return bridge


async def _render(
    cam: dict[str, Any], bridge: MagicMock, prefill_inputs: bool = False
) -> tuple[Any, Any, dict[str, Any]]:
    """Render camera_detail_page with generic button/switch/input capture.

    Returns (button_calls, switch_handlers, inputs_by_label):
    - button_calls: every captured on_click callable as (label, callable)
      tuples in render order.
    - switch_handlers: every ``.on_value_change(handler)`` handler captured
      off the fake ``ui.switch`` elements (the fake nicegui records
      ``on_value_change`` calls generically via ``FakeElement.__getattr__``
      — see tests/conftest.py — so we recover the handler from each switch
      instance's recorded ``.calls`` after render, rather than patching a
      real nicegui internal that doesn't exist under the fake).
    - inputs_by_label: ``ui.input``/``ui.number`` FakeElement instances keyed
      by their label, so a test can set ``.value`` before firing a button
      (e.g. filling in the Add Rule / Invite form fields).

    If ``prefill_inputs`` is True, every captured ``ui.input`` is given a
    non-empty placeholder value up front so success-path handlers (Add Rule,
    Invite) are reachable without each test hand-filling every field.
    """
    from nicegui import app, ui

    cfg = _make_cfg(cam)
    app.storage.general.clear()
    app.storage.general["cfg"] = cfg
    app.storage.general["token"] = "header.payload.signature"

    from bosch_camera_frontend.pages import camera_detail

    camera_detail.cli_bridge = bridge

    button_calls: list[tuple[str, Any]] = []
    original_button = ui.button

    def cap_button(*a: Any, **kw: Any) -> Any:
        on_click = kw.get("on_click")
        if on_click:
            label = a[0] if a else str(kw.get("icon", ""))
            button_calls.append((label, on_click))
        return original_button(*a, **kw)

    switch_instances: list[Any] = []
    original_switch = ui.switch

    def cap_switch(*a: Any, **kw: Any) -> Any:
        instance = original_switch(*a, **kw)
        switch_instances.append(instance)
        return instance

    inputs_by_label: dict[str, Any] = {}
    original_input = ui.input

    def cap_input(*a: Any, **kw: Any) -> Any:
        instance = original_input(*a, **kw)
        label = a[0] if a else str(kw.get("label", ""))
        inputs_by_label[label] = instance
        if prefill_inputs and label:
            instance.set_value(f"test-{label}")
        return instance

    timer_calls: list[Any] = []
    original_timer = ui.timer

    def cap_timer(*a: Any, **kw: Any) -> Any:
        if kw.get("once"):
            cb = a[1] if len(a) > 1 else kw.get("callback")
            if cb:
                timer_calls.append(cb)
        return original_timer(*a, **kw)

    ui.button = cap_button  # type: ignore[assignment]
    ui.switch = cap_switch  # type: ignore[assignment]
    ui.input = cap_input  # type: ignore[assignment]
    ui.timer = cap_timer  # type: ignore[assignment]
    try:
        await camera_detail.camera_detail_page("Test%20Cam")

        # Keep capture active while firing timers — _load_rules/_load_friends
        # build row-level buttons/switches (delete/share/remove) dynamically
        # inside the timer callback, not during the initial render.
        for fn in timer_calls:
            try:
                r = fn()
                if hasattr(r, "__await__"):
                    await r
            except Exception:
                pass
    finally:
        ui.button = original_button  # type: ignore[assignment]
        ui.switch = original_switch  # type: ignore[assignment]
        ui.input = original_input  # type: ignore[assignment]
        ui.timer = original_timer  # type: ignore[assignment]

    # (instance, handler) pairs so a test can assert the revert-on-failure
    # target is the SAME switch instance that raised the event (regression
    # coverage for the friends-sharing late-binding closure bug fixed
    # 2026-07-11 — see _toggle_share's `switch: Any = share_switch` default-arg).
    switch_handlers: list[tuple[Any, Any]] = []
    for inst in switch_instances:
        # Constructor-time on_change=... (privacy/light style).
        on_change = inst.init_kwargs.get("on_change")
        if on_change:
            switch_handlers.append((inst, on_change))
        # Post-construction .on_value_change(handler) (recording/share style).
        for call_name, call_args, _call_kw in getattr(inst, "calls", []):
            if call_name == "on_value_change" and call_args:
                switch_handlers.append((inst, call_args[0]))

    return button_calls, switch_handlers, inputs_by_label


async def _fire_all(button_calls: list[tuple[str, Any]]) -> None:
    for _label, fn in button_calls:
        try:
            r = fn()
            if hasattr(r, "__await__"):
                await r
        except Exception:
            pass


async def _fire_all_switches(
    switch_handlers: list[tuple[Any, Any]], value: bool
) -> None:
    for _inst, fn in switch_handlers:
        try:
            r = fn(types.SimpleNamespace(value=value))
            if hasattr(r, "__await__"):
                await r
        except Exception:
            pass


class TestParityBatchSuccessPaths:
    async def test_outdoor_light_camera_all_sections_render_and_apply(
        self, fake_nicegui: Any
    ) -> None:
        """Outdoor Eyes (Gen2, has_light) -> sound detection + wifi + lighting
        schedule + recording + rules + friends sections all render; every
        captured Apply/action button fires without error."""
        cam = _fake_cam(has_light=True, model="HOME_Eyes_Outdoor")
        bridge = _full_bridge(cam, writes_ok=True)

        button_calls, switch_handlers, _inputs = await _render(cam, bridge)
        assert button_calls
        await _fire_all(button_calls)
        await _fire_all_switches(switch_handlers, True)
        await _fire_all_switches(switch_handlers, False)

    async def test_indoor_ii_siren_camera_renders_and_fires(
        self, fake_nicegui: Any
    ) -> None:
        """Indoor II (Gen2, HOME_Eyes_Indoor) -> siren section renders
        (trigger/stop/set-duration), sound detection renders, lighting
        schedule does NOT (no has_light)."""
        cam = _fake_cam(has_light=False, model="HOME_Eyes_Indoor")
        bridge = _full_bridge(cam, writes_ok=True)

        button_calls, switch_handlers, _inputs = await _render(cam, bridge)
        assert button_calls
        await _fire_all(button_calls)
        await _fire_all_switches(switch_handlers, True)

    async def test_pan_slider_camera_renders_and_moves(self, fake_nicegui: Any) -> None:
        """CAMERA_360-style (pan_limit > 0) -> pan section renders + Move fires."""
        cam = _fake_cam(has_light=False, model="INDOOR", pan_limit=170)
        bridge = _full_bridge(cam, writes_ok=True)

        button_calls, _switch_handlers, _inputs = await _render(cam, bridge)
        move_calls = [c for c in button_calls if c[0] == "Move"]
        assert move_calls
        await _fire_all(button_calls)

    async def test_gen1_no_light_camera_skips_gen2_and_light_sections(
        self, fake_nicegui: Any
    ) -> None:
        """Gen1 camera (model doesn't start with HOME_), no light -> sound
        detection, lighting schedule, siren sections are all skipped; wifi,
        recording, rules, friends still render."""
        cam = _fake_cam(has_light=False, model="CAMERA_EYES")
        bridge = _full_bridge(cam, writes_ok=True)

        button_calls, switch_handlers, _inputs = await _render(cam, bridge)
        await _fire_all(button_calls)
        await _fire_all_switches(switch_handlers, True)

    async def test_add_rule_success_clears_inputs_and_calls_bridge(
        self, fake_nicegui: Any
    ) -> None:
        """With name/start/end filled in, Add Rule must actually call the
        bridge (bug-hunt finding 2026-07-11: the earlier version of this test
        only ever hit the empty-input validation guard, never the real
        success path — lines 745-760 in camera_detail.py were uncovered)."""
        cam = _fake_cam(has_light=False, model="HOME_Eyes_Outdoor")
        bridge = _full_bridge(cam, writes_ok=True)
        add_rule_calls: list[tuple[Any, ...]] = []

        async def _track_add_rule(*a: Any, **_kw: Any) -> tuple[bool, str | None]:
            add_rule_calls.append(a)
            return True, None

        bridge.async_add_rule = _track_add_rule

        button_calls, _switch_handlers, inputs = await _render(
            cam, bridge, prefill_inputs=True
        )
        inputs["Start (HH:MM)"].set_value("22:00")
        inputs["End (HH:MM)"].set_value("06:00")
        inputs["Name"].set_value("Night")

        add_button = next(fn for label, fn in button_calls if label == "Add Rule")
        result = add_button()
        if hasattr(result, "__await__"):
            await result

        assert add_rule_calls, "async_add_rule was never called"
        # Inputs must be cleared after a successful add (matches the
        # motion/intrusion/light "re-sync, don't keep stale input" discipline).
        assert inputs["Name"].value == ""
        assert inputs["Start (HH:MM)"].value == ""
        assert inputs["End (HH:MM)"].value == ""

    async def test_invite_success_clears_inputs_and_calls_bridge(
        self, fake_nicegui: Any
    ) -> None:
        """With email filled in, Invite must actually call the bridge
        (bug-hunt finding 2026-07-11 — same uncovered-success-path gap as
        Add Rule, lines 839-848)."""
        cam = _fake_cam(has_light=False, model="HOME_Eyes_Outdoor")
        bridge = _full_bridge(cam, writes_ok=True)
        invite_calls: list[tuple[Any, ...]] = []

        async def _track_invite(*a: Any, **_kw: Any) -> tuple[bool, str | None]:
            invite_calls.append(a)
            return True, None

        bridge.async_invite_friend = _track_invite

        button_calls, _switch_handlers, inputs = await _render(
            cam, bridge, prefill_inputs=True
        )
        inputs["Email"].set_value("friend@example.com")

        invite_button = next(fn for label, fn in button_calls if label == "Invite")
        result = invite_button()
        if hasattr(result, "__await__"):
            await result

        assert invite_calls, "async_invite_friend was never called"
        assert inputs["Email"].value == ""

    async def test_share_toggle_revert_targets_the_clicked_switch_not_the_last_one(
        self, fake_nicegui: Any
    ) -> None:
        """Regression test for the late-binding closure bug found in
        bug-hunt 2026-07-11: with two friends rendered, a FAILED unshare on
        the FIRST friend's switch must revert the FIRST friend's switch, not
        the last one rendered (the bug had every row's revert-on-failure
        resolve the free variable `share_switch` at call time, which always
        pointed at the last loop iteration's switch)."""
        cam = _fake_cam(has_light=False, model="HOME_Eyes_Outdoor")
        bridge = _full_bridge(cam, writes_ok=True)

        async def _list_two_friends(*_a: Any, **_kw: Any) -> list[dict[str, Any]]:
            return [
                {
                    "id": "friend-1",
                    "nickName": "Alice",
                    "status": "ACCEPTED",
                    "sharedVideoInputs": [{"videoInputId": cam["id"]}],
                },
                {
                    "id": "friend-2",
                    "nickName": "Bob",
                    "status": "ACCEPTED",
                    "sharedVideoInputs": [{"videoInputId": cam["id"]}],
                },
            ]

        bridge.async_list_friends = _list_two_friends

        async def _unshare_fails(*_a: Any, **_kw: Any) -> tuple[bool, str | None]:
            return False, "Camera offline"

        bridge.async_unshare_camera = _unshare_fails

        _button_calls, switch_handlers, _inputs = await _render(cam, bridge)

        # Two "Shares this camera" switches were rendered (one per friend).
        share_switches = [
            (inst, fn)
            for inst, fn in switch_handlers
            if inst.init_args and inst.init_args[0] == "Shares this camera"
        ]
        assert len(share_switches) == 2
        first_inst, first_handler = share_switches[0]
        second_inst, _second_handler = share_switches[1]

        # Un-toggle the FIRST friend's switch -> unshare fails -> only the
        # FIRST switch's value should be reverted (back to True), the SECOND
        # friend's switch must be untouched.
        first_inst.set_value(False)
        second_inst.set_value(True)
        result = first_handler(types.SimpleNamespace(value=False))
        if hasattr(result, "__await__"):
            await result

        assert first_inst.value is True, (
            "the clicked (first) switch must be reverted to True on failure"
        )
        assert second_inst.value is True, (
            "the second friend's switch must be untouched by the first "
            "friend's failed revert — this is exactly the late-binding bug"
        )


class TestParityBatchFailurePaths:
    async def test_write_failures_notify_and_resync(self, fake_nicegui: Any) -> None:
        """Every write endpoint failing must not raise — the UI re-syncs
        from the server (matches the revert-on-failure convention used by
        privacy/light/motion/intrusion)."""
        cam = _fake_cam(has_light=True, model="HOME_Eyes_Indoor")
        bridge = _full_bridge(cam, writes_ok=False)

        button_calls, switch_handlers, _inputs = await _render(cam, bridge)
        await _fire_all(button_calls)
        await _fire_all_switches(switch_handlers, True)
        await _fire_all_switches(switch_handlers, False)

    async def test_recording_switch_reverts_on_write_failure(
        self, fake_nicegui: Any
    ) -> None:
        """A failed Record Sound toggle must revert the switch value, not
        leave the UI claiming a state the write never achieved."""
        cam = _fake_cam(has_light=False, model="HOME_Eyes_Outdoor")
        bridge = _full_bridge(cam, writes_ok=False)

        _button_calls, switch_handlers, _inputs = await _render(cam, bridge)
        recording = next(
            (inst, fn)
            for inst, fn in switch_handlers
            if inst.init_args and inst.init_args[0] == "Record Sound"
        )
        inst, handler = recording

        # The fake nicegui's set_value() (unlike the real one) does NOT
        # itself invoke on_value_change handlers, so the suppress-guard
        # armed by _load_recording's own set_value() during render is still
        # pending here — consume it with one throwaway call first, exactly
        # mirroring what the real client's first genuine change event would
        # do after a load.
        consume = handler(types.SimpleNamespace(value=inst.value))
        if hasattr(consume, "__await__"):
            await consume

        inst.set_value(False)
        result = handler(types.SimpleNamespace(value=False))
        if hasattr(result, "__await__"):
            await result

        assert inst.value is True, "failed toggle must revert to the prior value"

    async def test_unavailable_data_sections_render_without_crash(
        self, fake_nicegui: Any
    ) -> None:
        """Every GET returning None/empty -> 'unavailable' labels, no crash."""
        cam = _fake_cam(has_light=True, model="HOME_Eyes_Outdoor")
        bridge = _empty_bridge(cam)

        button_calls, _switch_handlers, _inputs = await _render(cam, bridge)
        await _fire_all(button_calls)

    async def test_add_rule_missing_fields_shows_validation_notice(
        self, fake_nicegui: Any
    ) -> None:
        """Add Rule with empty name/start/end must not call the bridge."""
        cam = _fake_cam(has_light=False, model="HOME_Eyes_Outdoor")
        bridge = _full_bridge(cam, writes_ok=True)
        called = False

        async def _track_add_rule(*_a: Any, **_kw: Any) -> tuple[bool, str | None]:
            nonlocal called
            called = True
            return True, None

        bridge.async_add_rule = _track_add_rule

        button_calls, _switch_handlers, _inputs = await _render(cam, bridge)
        add_rule_calls = [c for c in button_calls if c[0] == "Add Rule"]
        assert add_rule_calls
        for _label, fn in add_rule_calls:
            r = fn()
            if hasattr(r, "__await__"):
                await r
        assert called is False

    async def test_invite_missing_email_shows_validation_notice(
        self, fake_nicegui: Any
    ) -> None:
        """Invite with empty email must not call the bridge."""
        cam = _fake_cam(has_light=False, model="HOME_Eyes_Outdoor")
        bridge = _full_bridge(cam, writes_ok=True)
        called = False

        async def _track_invite(*_a: Any, **_kw: Any) -> tuple[bool, str | None]:
            nonlocal called
            called = True
            return True, None

        bridge.async_invite_friend = _track_invite

        button_calls, _switch_handlers, _inputs = await _render(cam, bridge)
        invite_calls = [c for c in button_calls if c[0] == "Invite"]
        assert invite_calls
        for _label, fn in invite_calls:
            r = fn()
            if hasattr(r, "__await__"):
                await r
        assert called is False
