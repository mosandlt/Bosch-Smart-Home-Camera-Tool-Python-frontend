"""CLI Bridge — clean re-export of bosch_camera.py functions for the frontend.

Performs sys.path injection (via __init__._inject_cli_path) and then imports
only the public surface this UI actually needs.  All other frontend modules
import from here instead of from bosch_camera directly, keeping the dependency
boundary explicit and easy to mock in tests.

Each network-bound function has an ``async_*`` twin that runs the blocking
``requests`` call in a worker thread via :func:`asyncio.to_thread`, so NiceGUI
page handlers can ``await`` them without freezing the event loop (ASYNC_FIRST).

Trade-offs of sys.path injection vs. packaging:
  PRO: no duplication of API logic; CLI repo is single source of truth
  PRO: CLI updates are picked up immediately (no re-install step)
  CON: import order matters (injection must happen before first import)
  CON: tight coupling to CLI repo directory structure
  CON: no type stubs for IDE support (the CLI module is typed as Any here)
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from types import ModuleType
from typing import TYPE_CHECKING, Any, Callable, TypeVar, cast

# Ensure CLI path is injected before we attempt any import.
from bosch_camera_frontend import _inject_cli_path, BOSCH_CAMERA_CLI_PATH

if TYPE_CHECKING:
    import requests

_T = TypeVar("_T")

# Type aliases for the loosely-typed CLI surface.
ConfigDict = dict[str, Any]
CameraDict = dict[str, Any]


def _ensure_cli_available(cli_path: str | None = None) -> None:
    """Inject CLI path and verify bosch_camera is importable.

    Args:
        cli_path: Override path (e.g. from --cli-path arg). Uses
                  BOSCH_CAMERA_CLI_PATH env / default if None.

    Raises:
        FileNotFoundError: CLI directory missing.
        ImportError: bosch_camera.py not found or not importable.
    """
    _inject_cli_path(cli_path)
    if "bosch_camera" not in sys.modules:
        try:
            importlib.import_module("bosch_camera")
        except ImportError as exc:
            raise ImportError(
                f"Could not import bosch_camera from {cli_path or BOSCH_CAMERA_CLI_PATH!r}. "
                f"Original error: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Lazy-imported references — populated on first call to ensure_cli_available().
# This prevents import-time side effects (e.g. urllib3 warnings, argparse
# registrations inside bosch_camera.py) when running tests with CLI mocked.
# ---------------------------------------------------------------------------


def _bc() -> ModuleType:
    """Return the bosch_camera module (import on first call)."""
    if "bosch_camera" not in sys.modules:
        _ensure_cli_available()
    return sys.modules["bosch_camera"]


def _i18n() -> ModuleType:
    """Return the bosch_i18n module (import on first call)."""
    if "bosch_i18n" not in sys.modules:
        _ensure_cli_available()
    return sys.modules.get("bosch_i18n") or importlib.import_module("bosch_i18n")


async def _to_thread(func: Callable[..., _T], /, *args: Any, **kwargs: Any) -> _T:
    """Run a blocking CLI call in a worker thread (keeps the UI loop free)."""
    return await asyncio.to_thread(func, *args, **kwargs)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config(config_path: str | None = None) -> ConfigDict:
    """Load bosch_config.json.  Uses CLI default path if *config_path* is None."""
    bc = _bc()
    if config_path:
        # Temporarily override the module-level CONFIG_FILE constant.
        # getattr/setattr keep mypy happy about the dynamic module attribute.
        original = getattr(bc, "CONFIG_FILE", None)
        setattr(bc, "CONFIG_FILE", config_path)
        try:
            return cast(ConfigDict, bc.load_config())
        finally:
            setattr(bc, "CONFIG_FILE", original)
    return cast(ConfigDict, bc.load_config())


def save_config(cfg: ConfigDict) -> None:
    _bc().save_config(cfg)


def check_token_age(cfg: ConfigDict) -> str:
    return cast(str, _bc().check_token_age(cfg))


# ---------------------------------------------------------------------------
# Session / Token
# ---------------------------------------------------------------------------


def make_session(token: str) -> "requests.Session":
    return cast("requests.Session", _bc().make_session(token))


def get_token(cfg: ConfigDict) -> str:
    """Return the current bearer token (does NOT prompt for a new one)."""
    token: str = cfg.get("account", {}).get("bearer_token", "").strip()
    if not token:
        raise ValueError(
            "No bearer token in config. Run: python3 bosch_camera.py token fix"
        )
    return token


# ---------------------------------------------------------------------------
# Camera discovery & state
# ---------------------------------------------------------------------------


def get_cameras(cfg: ConfigDict, session: "requests.Session") -> dict[str, CameraDict]:
    """Always live from /v11/video_inputs — the cloud is authoritative for
    names/firmware/mac. Pre-2026-05-24 we returned cfg["cameras"] which hid
    cloud-side renames and any cameras added since the last `rescan`.
    Local-only fields (local_ip / creds / download_folder) are preserved
    across refresh, keyed by camera id.
    """
    bc = _bc()
    cached: dict[str, CameraDict] = cfg.get("cameras", {}) or {}
    try:
        r = session.get(f"{bc.CLOUD_API}/v11/video_inputs", timeout=15)
        if r.status_code != 200:
            return cached or cast("dict[str, CameraDict]", bc.get_cameras(cfg, session))
        by_id = {info.get("id"): info for info in cached.values() if info.get("id")}
        fresh: dict[str, CameraDict] = {}
        for cam in r.json():
            cam_id = cam.get("id", "")
            name = cam.get("title") or cam_id or "unknown"
            prev = by_id.get(cam_id, {})
            fresh[name] = {
                "id": cam_id,
                "name": name,
                "model": cam.get("hardwareVersion", "CAMERA"),
                "firmware": cam.get("firmwareVersion", ""),
                "mac": cam.get("macAddress", ""),
                "download_folder": prev.get("download_folder", name),
                "local_ip": prev.get("local_ip", ""),
                "local_username": prev.get("local_username", ""),
                "local_password": prev.get("local_password", ""),
                "has_light": prev.get("has_light", False),
                "pan_limit": prev.get("pan_limit", 0),
            }
        cfg["cameras"] = fresh
        return fresh
    except Exception:
        return cached or cast("dict[str, CameraDict]", bc.get_cameras(cfg, session))


def discover_cameras(
    cfg: ConfigDict, session: "requests.Session"
) -> dict[str, CameraDict]:
    return cast("dict[str, CameraDict]", _bc().discover_cameras(cfg, session))


def resolve_cam(cfg: ConfigDict, key: str | None) -> dict[str, CameraDict]:
    return cast("dict[str, CameraDict]", _bc().resolve_cam(cfg, key))


def api_ping(session: "requests.Session", cam_id: str) -> str:
    return cast(str, _bc().api_ping(session, cam_id))


def api_get_events(
    session: "requests.Session", cam_id: str, limit: int = 10
) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", _bc().api_get_events(session, cam_id, limit))


def api_get_camera(session: "requests.Session", cam_id: str) -> CameraDict | None:
    return cast("CameraDict | None", _bc().api_get_camera(session, cam_id))


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def snap_from_proxy(
    cam_info: CameraDict, token: str, hq: bool = False, cfg: ConfigDict | None = None
) -> bytes | None:
    return cast("bytes | None", _bc().snap_from_proxy(cam_info, token, hq=hq, cfg=cfg))


def get_stream_url(
    cam_info: CameraDict,
    token: str,
    hq: bool = False,
    cfg: ConfigDict | None = None,
    conn_type: str | None = None,
) -> dict[str, Any] | None:
    """Resolve a live RTSP(S) stream URL (go2rtc source) — see live-webrtc-plan.md.

    Returns ``{"url", "type", "user", "password"}`` or ``None``. The Digest creds
    in a Gen2 URL rotate per call, so callers re-resolve on stream failure.
    """
    return cast(
        "dict[str, Any] | None",
        _bc().get_stream_url(cam_info, token, hq=hq, cfg=cfg, conn_type=conn_type),
    )


def snap_from_events(
    session: "requests.Session", cam_info: CameraDict
) -> tuple[bytes | None, str]:
    return cast("tuple[bytes | None, str]", _bc().snap_from_events(session, cam_info))


# ---------------------------------------------------------------------------
# Camera controls
# ---------------------------------------------------------------------------


def set_privacy_mode(
    session: "requests.Session", cam_id: str, on: bool
) -> tuple[bool, str | None]:
    """Set privacy mode ON or OFF. Returns (ok, error_reason).

    error_reason is None on success, a short human-readable string on failure
    (e.g. "Camera offline (444)", "Auth expired (401)"). Pre-2026-05-24 the
    bool-only return surfaced every non-204 as "check token", which masked the
    common case of an offline camera.
    """
    bc = _bc()
    payload = {"privacyMode": "ON" if on else "OFF", "durationInSeconds": None}
    r = session.put(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/privacy",
        json=payload,
        timeout=10,
    )
    if r.status_code == 204:
        return True, None
    return False, _map_write_error(r)


def get_privacy_mode(session: "requests.Session", cam_id: str) -> str | None:
    """Return "ON", "OFF", or None on error."""
    bc = _bc()
    r = session.get(f"{bc.CLOUD_API}/v11/video_inputs", timeout=10)
    if r.status_code != 200:
        return None
    for cam in r.json():
        if cam.get("id") == cam_id:
            return cast(str, cam.get("privacyMode", "UNKNOWN"))
    return None


def get_all_cameras_status(session: "requests.Session") -> list[dict[str, Any]]:
    """Return raw list from GET /v11/video_inputs (all cameras + privacyMode)."""
    bc = _bc()
    r = session.get(f"{bc.CLOUD_API}/v11/video_inputs", timeout=10)
    if r.status_code != 200:
        return []
    return cast("list[dict[str, Any]]", r.json())


def _map_write_error(r: "requests.Response") -> str:
    """Shared HTTP-status -> human-readable error mapping for write endpoints."""
    try:
        err = r.json().get("error", "").removeprefix("sh:")
    except Exception:
        err = ""
    if r.status_code == 444 or "camera.unavailable" in err:
        return "Camera offline"
    if r.status_code == 401:
        return "Auth expired — refresh token"
    if r.status_code == 403:
        return "Permission denied"
    if r.status_code == 442:
        return "Not supported on this camera model"
    return f"HTTP {r.status_code} {err or 'unknown error'}"


def get_light_override(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    """GET current light-override state (frontLightOn/wallwasherOn/frontLightIntensity).

    Returns None on error/HTTP != 200. Mirrors ``cmd_light``'s GET.
    """
    bc = _bc()
    r = session.get(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/lighting_override", timeout=10
    )
    if r.status_code != 200:
        return None
    return cast("dict[str, Any]", r.json())


def set_light_override(
    session: "requests.Session",
    cam_id: str,
    front_on: bool,
    wall_on: bool | None = None,
    intensity: float | None = None,
) -> tuple[bool, str | None]:
    """Set the camera light override. Returns (ok, error_reason).

    Mirrors ``cmd_light``'s PUT body: {"frontLightOn", "wallwasherOn",
    "frontLightIntensity"}. If wall_on/intensity are omitted, they follow
    front_on (both-on / both-off), matching the CLI's ``on``/``off`` shorthand.
    """
    bc = _bc()
    if wall_on is None:
        wall_on = front_on
    if intensity is None:
        intensity = 1.0 if front_on else 0.0
    payload = {
        "frontLightOn": front_on,
        "wallwasherOn": wall_on,
        "frontLightIntensity": intensity,
    }
    r = session.put(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/lighting_override",
        json=payload,
        timeout=10,
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def get_unread_count(session: "requests.Session", cam_id: str) -> int | None:
    """GET unread event count for a camera. Returns None on error.

    API: GET /v11/video_inputs/{id} -> field numberOfUnreadEvents. Mirrors
    ``cmd_unread`` (the dedicated /unread_events_count endpoint 404s in prod).
    """
    bc = _bc()
    r = session.get(f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}", timeout=10)
    if r.status_code != 200:
        return None
    return cast(int, r.json().get("numberOfUnreadEvents", 0))


def get_motion_detection(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    """GET motion-detection config (enabled/motionAlarmConfiguration). None on error."""
    bc = _bc()
    r = session.get(f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/motion", timeout=10)
    if r.status_code != 200:
        return None
    return cast("dict[str, Any]", r.json())


def set_motion_detection(
    session: "requests.Session",
    cam_id: str,
    enabled: bool,
    sensitivity: str | None = None,
) -> tuple[bool, str | None]:
    """Set motion detection enabled + optional sensitivity. Returns (ok, error_reason).

    sensitivity one of OFF/LOW/MEDIUM_LOW/MEDIUM_HIGH/HIGH/SUPER_HIGH. Mirrors
    ``cmd_motion``'s PUT body: {"enabled", "motionAlarmConfiguration"}.
    """
    bc = _bc()
    payload: dict[str, Any] = {"enabled": enabled}
    if sensitivity is not None:
        payload["motionAlarmConfiguration"] = sensitivity
    r = session.put(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/motion",
        json=payload,
        timeout=10,
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def get_intrusion_detection(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    """GET intrusion-detection config. Returns None on error/442 (unsupported)."""
    bc = _bc()
    r = session.get(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/intrusionDetectionConfig",
        timeout=10,
    )
    if r.status_code != 200:
        return None
    return cast("dict[str, Any]", r.json())


def set_intrusion_detection(
    session: "requests.Session",
    cam_id: str,
    enabled: bool,
    detection_mode: str | None = None,
    sensitivity: int | None = None,
    distance: int | None = None,
) -> tuple[bool, str | None]:
    """Set intrusion-detection config. Returns (ok, error_reason).

    Mirrors ``cmd_intrusion``'s PUT body: {"enabled", "detectionMode",
    "sensitivity" (0-7), "distance" (1-8)}. HTTP 442 = unsupported model.
    """
    bc = _bc()
    payload: dict[str, Any] = {"enabled": enabled}
    if detection_mode is not None:
        payload["detectionMode"] = detection_mode
    if sensitivity is not None:
        payload["sensitivity"] = sensitivity
    if distance is not None:
        payload["distance"] = distance
    r = session.put(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/intrusionDetectionConfig",
        json=payload,
        timeout=10,
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


# ---------------------------------------------------------------------------
# v0.3.0-alpha family-parity batch: glass-break/fire-alarm, wifi, lighting
# schedule, recording (sound), siren+duration, diagnostics reads, friends
# CRUD, rules CRUD, pan. Endpoints/fields mirror bosch_camera.py's cmd_*
# handlers 1:1 (see each function's docstring for the exact CLI source).
# ---------------------------------------------------------------------------


def get_audio_detection(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    """GET glass-break/fire-alarm sound detection config. None on error.

    API: GET /v11/video_inputs/{id}/audioDetectionConfig -> {detectGlassBreak,
    detectFireAlarm}. Gen2 Audio-Plus only (HTTP 442 elsewhere). Mirrors
    ``cmd_audio_detection``'s GET.
    """
    bc = _bc()
    r = session.get(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/audioDetectionConfig", timeout=10
    )
    if r.status_code != 200:
        return None
    return cast("dict[str, Any]", r.json())


def set_audio_detection(
    session: "requests.Session",
    cam_id: str,
    glass_break: bool,
    fire_alarm: bool,
) -> tuple[bool, str | None]:
    """Set glass-break + fire-alarm detection. Returns (ok, error_reason).

    Both fields are ALWAYS sent together — Bosch's API silently resets
    whichever field is omitted (mirrors ``cmd_audio_detection``'s PUT body:
    {"detectGlassBreak", "detectFireAlarm"}).
    """
    bc = _bc()
    payload = {"detectGlassBreak": glass_break, "detectFireAlarm": fire_alarm}
    r = session.put(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/audioDetectionConfig",
        json=payload,
        timeout=10,
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def get_wifi_info(session: "requests.Session", cam_id: str) -> dict[str, Any] | None:
    """GET WiFi signal info. None on error (e.g. HTTP 442 = wired camera).

    API: GET /v11/video_inputs/{id}/wifiinfo. Field names vary by camera
    model (ssid/SSID, rssi/RSSI/signalLevel) — the caller reads with
    fallback chaining, mirroring ``cmd_wifi``.
    """
    bc = _bc()
    r = session.get(f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/wifiinfo", timeout=10)
    if r.status_code != 200:
        return None
    return cast("dict[str, Any]", r.json())


def get_lighting_schedule(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    """GET the LED lighting schedule (outdoor Eyes cameras only). None on error.

    API: GET /v11/video_inputs/{id}/lighting_options. HTTP 442 = not
    supported on this model, HTTP 444 = camera offline. Mirrors
    ``cmd_lighting_schedule``'s GET.
    """
    bc = _bc()
    r = session.get(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/lighting_options", timeout=10
    )
    if r.status_code != 200:
        return None
    return cast("dict[str, Any]", r.json())


def set_lighting_schedule(
    session: "requests.Session",
    cam_id: str,
    on_time: str | None = None,
    off_time: str | None = None,
    light_on_motion: bool | None = None,
    darkness_threshold: float | None = None,
) -> tuple[bool, str | None]:
    """Update the lighting schedule. Returns (ok, error_reason).

    Read-modify-write: fetches the current schedule, merges provided fields,
    forces scheduleStatus="FOLLOW_SCHEDULE" (mirrors ``cmd_lighting_schedule``
    — writing a schedule implies following it), then PUTs the full body.
    on_time/off_time: "HH:MM" or "HH:MM:SS" (":00" appended if seconds missing).
    """
    bc = _bc()
    current = get_lighting_schedule(session, cam_id) or {}
    if on_time is not None:
        current["generalLightOnTime"] = (
            on_time if len(on_time.split(":")) == 3 else f"{on_time}:00"
        )
    if off_time is not None:
        current["generalLightOffTime"] = (
            off_time if len(off_time.split(":")) == 3 else f"{off_time}:00"
        )
    if light_on_motion is not None:
        current["lightOnMotion"] = light_on_motion
    if darkness_threshold is not None:
        current["darknessThreshold"] = float(darkness_threshold)
    current["scheduleStatus"] = "FOLLOW_SCHEDULE"
    r = session.put(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/lighting_options",
        json=current,
        timeout=10,
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def get_recording_options(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    """GET cloud recording options ({recordSound}). None on error.

    API: GET /v11/video_inputs/{id}/recording_options. Mirrors
    ``cmd_recording``'s GET.
    """
    bc = _bc()
    r = session.get(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/recording_options", timeout=10
    )
    if r.status_code != 200:
        return None
    return cast("dict[str, Any]", r.json())


def set_recording_options(
    session: "requests.Session", cam_id: str, sound_on: bool
) -> tuple[bool, str | None]:
    """Set whether cloud recordings include audio. Returns (ok, error_reason).

    API: PUT /v11/video_inputs/{id}/recording_options body {"recordSound"}.
    Mirrors ``cmd_recording``'s PUT.
    """
    bc = _bc()
    r = session.put(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/recording_options",
        json={"recordSound": sound_on},
        timeout=10,
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def trigger_siren(
    session: "requests.Session", cam_id: str, stop: bool = False
) -> tuple[bool, str | None]:
    """Trigger or stop the Gen2 Indoor II panic alarm. Returns (ok, error_reason).

    API: PUT /v11/video_inputs/{id}/panic_alarm body {"status":"ON"|"OFF"}.
    Only HOME_Eyes_Indoor has a working siren endpoint — caller must gate on
    ``model``. Mirrors ``cmd_siren``.
    """
    bc = _bc()
    r = session.put(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/panic_alarm",
        json={"status": "OFF" if stop else "ON"},
        timeout=10,
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def get_alarm_settings(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    """GET alarm_settings ({alarmDelayInSeconds, ...}). None on error.

    API: GET /v11/video_inputs/{id}/alarm_settings. Mirrors
    ``cmd_siren --set-duration``'s GET.
    """
    bc = _bc()
    r = session.get(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/alarm_settings", timeout=10
    )
    if r.status_code != 200:
        return None
    return cast("dict[str, Any]", r.json())


def set_siren_duration(
    session: "requests.Session", cam_id: str, duration_secs: int
) -> tuple[bool, str | None]:
    """Set the siren alarm duration (10-300s, Gen2 Indoor II only).

    Read-modify-write on /alarm_settings, field alarmDelayInSeconds. A failed
    GET (best-effort) still proceeds with just the new field, mirroring
    ``cmd_siren --set-duration``. Returns (ok, error_reason).
    """
    bc = _bc()
    current = get_alarm_settings(session, cam_id) or {}
    current["alarmDelayInSeconds"] = duration_secs
    r = session.put(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/alarm_settings",
        json=current,
        timeout=10,
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def get_pan(session: "requests.Session", cam_id: str) -> dict[str, Any] | None:
    """GET current pan position ({currentAbsolutePosition, panLimit}). None on error.

    API: GET /v11/video_inputs/{id}/pan. Only CAMERA_360 (pan_limit > 0).
    Mirrors ``cmd_pan``'s GET.
    """
    bc = _bc()
    r = session.get(f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/pan", timeout=10)
    if r.status_code != 200:
        return None
    return cast("dict[str, Any]", r.json())


def set_pan(
    session: "requests.Session", cam_id: str, absolute_position: int
) -> tuple[bool, str | None]:
    """Set absolute pan position in degrees. Returns (ok, error_reason).

    API: PUT /v11/video_inputs/{id}/pan body {"absolutePosition": int}.
    Mirrors ``cmd_pan``'s PUT.
    """
    bc = _bc()
    r = session.put(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/pan",
        json={"absolutePosition": absolute_position},
        timeout=10,
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def get_feature_flags(session: "requests.Session") -> dict[str, Any] | None:
    """GET account-level feature flags, normalised to dict[str, Any]. None on error.

    API: GET /v11/feature_flags (not per-camera). Bosch has been observed to
    return either a dict OR a list of ``{name/key, value/enabled}`` objects
    here — a bare ``cast("dict", ...)`` on a list response would silently
    produce a dict-typed list that crashes on the first ``.get()`` call
    (bug-hunt finding 2026-07-11). Mirrors ``cmd_feature_flags``'s own
    normalisation exactly (dict passthrough / list-of-dicts flattened by
    name+value / list-of-scalars each treated as an enabled flag / anything
    else wrapped as ``{"raw": ...}``).
    """
    bc = _bc()
    r = session.get(f"{bc.CLOUD_API}/v11/feature_flags", timeout=10)
    if r.status_code != 200:
        return None
    flags = r.json()
    if isinstance(flags, dict):
        return cast("dict[str, Any]", flags)
    if isinstance(flags, list):
        flags_dict: dict[str, Any] = {}
        for item in flags:
            if isinstance(item, dict):
                key = str(item.get("name", item.get("key", "?")))
                flags_dict[key] = item.get("value", item.get("enabled", "?"))
            else:
                flags_dict[str(item)] = True
        return flags_dict
    return {"raw": flags}


def list_rules(session: "requests.Session", cam_id: str) -> list[dict[str, Any]] | None:
    """GET automation rules for one camera. None on error.

    API: GET /v11/video_inputs/{id}/rules. Mirrors ``cmd_rules``'s list.
    """
    bc = _bc()
    r = session.get(f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/rules", timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    return cast(
        "list[dict[str, Any]]",
        data if isinstance(data, list) else data.get("items", []),
    )


def add_rule(
    session: "requests.Session",
    cam_id: str,
    name: str,
    start: str,
    end: str,
    weekdays: list[int],
    active: bool = True,
) -> tuple[bool, str | None]:
    """Create a new automation rule. Returns (ok, error_reason).

    API: POST /v11/video_inputs/{id}/rules body {"id": null, "name",
    "isActive", "startTime", "endTime", "weekdays"}. Mirrors ``cmd_rules add``.
    """
    bc = _bc()
    payload = {
        "id": None,
        "name": name,
        "isActive": active,
        "startTime": start if len(start.split(":")) == 3 else f"{start}:00",
        "endTime": end if len(end.split(":")) == 3 else f"{end}:00",
        "weekdays": weekdays,
    }
    r = session.post(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/rules", json=payload, timeout=10
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def edit_rule(
    session: "requests.Session",
    cam_id: str,
    rule_id: str,
    name: str | None = None,
    start: str | None = None,
    end: str | None = None,
    weekdays: list[int] | None = None,
    active: bool | None = None,
) -> tuple[bool, str | None]:
    """Edit an existing rule (read-modify-write). Returns (ok, error_reason).

    API: PUT /v11/video_inputs/{id}/rules/{rule_id} with the full rule
    object. Mirrors ``cmd_rules edit``.
    """
    bc = _bc()
    rules = list_rules(session, cam_id) or []
    current = next((r for r in rules if str(r.get("id")) == str(rule_id)), None)
    if current is None:
        return False, "Rule not found"
    if name is not None:
        current["name"] = name
    if start is not None:
        current["startTime"] = start if len(start.split(":")) == 3 else f"{start}:00"
    if end is not None:
        current["endTime"] = end if len(end.split(":")) == 3 else f"{end}:00"
    if weekdays is not None:
        current["weekdays"] = weekdays
    if active is not None:
        current["isActive"] = active
    r = session.put(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/rules/{rule_id}",
        json=current,
        timeout=10,
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def delete_rule(
    session: "requests.Session", cam_id: str, rule_id: str
) -> tuple[bool, str | None]:
    """Delete a rule. Returns (ok, error_reason).

    API: DELETE /v11/video_inputs/{id}/rules/{rule_id}. Mirrors
    ``cmd_rules delete``.
    """
    bc = _bc()
    r = session.delete(
        f"{bc.CLOUD_API}/v11/video_inputs/{cam_id}/rules/{rule_id}", timeout=10
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def list_friends(session: "requests.Session") -> list[dict[str, Any]] | None:
    """GET all camera-sharing friends/invitations. None on error.

    API: GET /v11/friends. Mirrors ``cmd_friends``'s list.
    """
    bc = _bc()
    r = session.get(f"{bc.CLOUD_API}/v11/friends", timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    return cast(
        "list[dict[str, Any]]",
        data if isinstance(data, list) else data.get("items", []),
    )


def invite_friend(
    session: "requests.Session", email: str, nickname: str = ""
) -> tuple[bool, str | None]:
    """Invite a new friend by email. Returns (ok, error_reason).

    API: POST /v11/friends body {"invitationEmail", "nickName"}. Mirrors
    ``cmd_friends invite``.
    """
    bc = _bc()
    r = session.post(
        f"{bc.CLOUD_API}/v11/friends",
        json={"invitationEmail": email, "nickName": nickname},
        timeout=10,
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def remove_friend(
    session: "requests.Session", friend_id: str
) -> tuple[bool, str | None]:
    """Remove a friend / revoke an invitation. Returns (ok, error_reason).

    API: DELETE /v11/friends/{friend_id}. Mirrors ``cmd_friends remove``.
    """
    bc = _bc()
    r = session.delete(f"{bc.CLOUD_API}/v11/friends/{friend_id}", timeout=10)
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def share_camera(
    session: "requests.Session", friend_id: str, cam_id: str
) -> tuple[bool, str | None]:
    """Share one camera with a friend (adds to their existing shares).

    API: PUT /v11/friends/{friend_id}/share body = full array of
    {"videoInputId", ...} entries. Mirrors ``cmd_friends share`` — fetches
    the friend's current shares first, appends cam_id if not already present.
    """
    bc = _bc()
    friends = list_friends(session) or []
    friend = next((f for f in friends if str(f.get("id")) == str(friend_id)), None)
    shares: list[dict[str, Any]] = (
        list(friend.get("sharedVideoInputs", [])) if friend else []
    )
    if not any(str(s.get("videoInputId")) == str(cam_id) for s in shares):
        shares.append({"videoInputId": cam_id})
    r = session.put(
        f"{bc.CLOUD_API}/v11/friends/{friend_id}/share", json=shares, timeout=10
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


def unshare_camera(
    session: "requests.Session", friend_id: str, cam_id: str
) -> tuple[bool, str | None]:
    """Stop sharing one camera with a friend. Returns (ok, error_reason).

    API: PUT /v11/friends/{friend_id}/share with cam_id removed from the
    array. Mirrors ``cmd_friends unshare``.
    """
    bc = _bc()
    friends = list_friends(session) or []
    friend = next((f for f in friends if str(f.get("id")) == str(friend_id)), None)
    shares: list[dict[str, Any]] = (
        list(friend.get("sharedVideoInputs", [])) if friend else []
    )
    shares = [s for s in shares if str(s.get("videoInputId")) != str(cam_id)]
    r = session.put(
        f"{bc.CLOUD_API}/v11/friends/{friend_id}/share", json=shares, timeout=10
    )
    if r.status_code in (200, 201, 204):
        return True, None
    return False, _map_write_error(r)


# ---------------------------------------------------------------------------
# Async twins — run the blocking call above in a worker thread.
# Use these from `async def` NiceGUI handlers so the event loop stays free.
# ---------------------------------------------------------------------------


async def async_get_cameras(
    cfg: ConfigDict, session: "requests.Session"
) -> dict[str, CameraDict]:
    return await _to_thread(get_cameras, cfg, session)


async def async_resolve_cam(cfg: ConfigDict, key: str | None) -> dict[str, CameraDict]:
    return await _to_thread(resolve_cam, cfg, key)


async def async_api_ping(session: "requests.Session", cam_id: str) -> str:
    return await _to_thread(api_ping, session, cam_id)


async def async_api_get_events(
    session: "requests.Session", cam_id: str, limit: int = 10
) -> list[dict[str, Any]]:
    return await _to_thread(api_get_events, session, cam_id, limit)


async def async_snap_from_proxy(
    cam_info: CameraDict, token: str, hq: bool = False, cfg: ConfigDict | None = None
) -> bytes | None:
    return await _to_thread(snap_from_proxy, cam_info, token, hq=hq, cfg=cfg)


async def async_get_stream_url(
    cam_info: CameraDict,
    token: str,
    hq: bool = False,
    cfg: ConfigDict | None = None,
    conn_type: str | None = None,
) -> dict[str, Any] | None:
    """Async resolve of a live RTSP(S) stream URL (go2rtc source)."""
    return await _to_thread(
        get_stream_url, cam_info, token, hq=hq, cfg=cfg, conn_type=conn_type
    )


async def async_snap_from_events(
    session: "requests.Session", cam_info: CameraDict
) -> tuple[bytes | None, str]:
    return await _to_thread(snap_from_events, session, cam_info)


async def async_set_privacy_mode(
    session: "requests.Session", cam_id: str, on: bool
) -> tuple[bool, str | None]:
    return await _to_thread(set_privacy_mode, session, cam_id, on)


async def async_get_privacy_mode(
    session: "requests.Session", cam_id: str
) -> str | None:
    return await _to_thread(get_privacy_mode, session, cam_id)


async def async_check_token_age(cfg: ConfigDict) -> str:
    return await _to_thread(check_token_age, cfg)


async def async_get_light_override(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    return await _to_thread(get_light_override, session, cam_id)


async def async_set_light_override(
    session: "requests.Session",
    cam_id: str,
    front_on: bool,
    wall_on: bool | None = None,
    intensity: float | None = None,
) -> tuple[bool, str | None]:
    return await _to_thread(
        set_light_override, session, cam_id, front_on, wall_on, intensity
    )


async def async_get_unread_count(
    session: "requests.Session", cam_id: str
) -> int | None:
    return await _to_thread(get_unread_count, session, cam_id)


async def async_get_motion_detection(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    return await _to_thread(get_motion_detection, session, cam_id)


async def async_set_motion_detection(
    session: "requests.Session",
    cam_id: str,
    enabled: bool,
    sensitivity: str | None = None,
) -> tuple[bool, str | None]:
    return await _to_thread(set_motion_detection, session, cam_id, enabled, sensitivity)


async def async_get_intrusion_detection(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    return await _to_thread(get_intrusion_detection, session, cam_id)


async def async_set_intrusion_detection(
    session: "requests.Session",
    cam_id: str,
    enabled: bool,
    detection_mode: str | None = None,
    sensitivity: int | None = None,
    distance: int | None = None,
) -> tuple[bool, str | None]:
    return await _to_thread(
        set_intrusion_detection,
        session,
        cam_id,
        enabled,
        detection_mode,
        sensitivity,
        distance,
    )


# ---------------------------------------------------------------------------
# Async twins for the v0.3.0-alpha family-parity batch.
# ---------------------------------------------------------------------------


async def async_get_audio_detection(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    return await _to_thread(get_audio_detection, session, cam_id)


async def async_set_audio_detection(
    session: "requests.Session", cam_id: str, glass_break: bool, fire_alarm: bool
) -> tuple[bool, str | None]:
    return await _to_thread(
        set_audio_detection, session, cam_id, glass_break, fire_alarm
    )


async def async_get_wifi_info(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    return await _to_thread(get_wifi_info, session, cam_id)


async def async_get_lighting_schedule(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    return await _to_thread(get_lighting_schedule, session, cam_id)


async def async_set_lighting_schedule(
    session: "requests.Session",
    cam_id: str,
    on_time: str | None = None,
    off_time: str | None = None,
    light_on_motion: bool | None = None,
    darkness_threshold: float | None = None,
) -> tuple[bool, str | None]:
    return await _to_thread(
        set_lighting_schedule,
        session,
        cam_id,
        on_time,
        off_time,
        light_on_motion,
        darkness_threshold,
    )


async def async_get_recording_options(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    return await _to_thread(get_recording_options, session, cam_id)


async def async_set_recording_options(
    session: "requests.Session", cam_id: str, sound_on: bool
) -> tuple[bool, str | None]:
    return await _to_thread(set_recording_options, session, cam_id, sound_on)


async def async_trigger_siren(
    session: "requests.Session", cam_id: str, stop: bool = False
) -> tuple[bool, str | None]:
    return await _to_thread(trigger_siren, session, cam_id, stop)


async def async_get_alarm_settings(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    return await _to_thread(get_alarm_settings, session, cam_id)


async def async_set_siren_duration(
    session: "requests.Session", cam_id: str, duration_secs: int
) -> tuple[bool, str | None]:
    return await _to_thread(set_siren_duration, session, cam_id, duration_secs)


async def async_get_pan(
    session: "requests.Session", cam_id: str
) -> dict[str, Any] | None:
    return await _to_thread(get_pan, session, cam_id)


async def async_set_pan(
    session: "requests.Session", cam_id: str, absolute_position: int
) -> tuple[bool, str | None]:
    return await _to_thread(set_pan, session, cam_id, absolute_position)


async def async_get_feature_flags(session: "requests.Session") -> dict[str, Any] | None:
    return await _to_thread(get_feature_flags, session)


async def async_list_rules(
    session: "requests.Session", cam_id: str
) -> list[dict[str, Any]] | None:
    return await _to_thread(list_rules, session, cam_id)


async def async_add_rule(
    session: "requests.Session",
    cam_id: str,
    name: str,
    start: str,
    end: str,
    weekdays: list[int],
    active: bool = True,
) -> tuple[bool, str | None]:
    return await _to_thread(
        add_rule, session, cam_id, name, start, end, weekdays, active
    )


async def async_edit_rule(
    session: "requests.Session",
    cam_id: str,
    rule_id: str,
    name: str | None = None,
    start: str | None = None,
    end: str | None = None,
    weekdays: list[int] | None = None,
    active: bool | None = None,
) -> tuple[bool, str | None]:
    return await _to_thread(
        edit_rule, session, cam_id, rule_id, name, start, end, weekdays, active
    )


async def async_delete_rule(
    session: "requests.Session", cam_id: str, rule_id: str
) -> tuple[bool, str | None]:
    return await _to_thread(delete_rule, session, cam_id, rule_id)


async def async_list_friends(
    session: "requests.Session",
) -> list[dict[str, Any]] | None:
    return await _to_thread(list_friends, session)


async def async_invite_friend(
    session: "requests.Session", email: str, nickname: str = ""
) -> tuple[bool, str | None]:
    return await _to_thread(invite_friend, session, email, nickname)


async def async_remove_friend(
    session: "requests.Session", friend_id: str
) -> tuple[bool, str | None]:
    return await _to_thread(remove_friend, session, friend_id)


async def async_share_camera(
    session: "requests.Session", friend_id: str, cam_id: str
) -> tuple[bool, str | None]:
    return await _to_thread(share_camera, session, friend_id, cam_id)


async def async_unshare_camera(
    session: "requests.Session", friend_id: str, cam_id: str
) -> tuple[bool, str | None]:
    return await _to_thread(unshare_camera, session, friend_id, cam_id)


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------


def t(msg_key: str, **kwargs: Any) -> str:
    return cast(str, _i18n().t(msg_key, **kwargs))


def set_lang(lang: str) -> None:
    _i18n().set_lang(lang)


def detect_lang(cfg: ConfigDict) -> str:
    return cast(str, _i18n().detect_lang(cfg))


AVAILABLE_LANGS: tuple[str, ...] = (
    "en",
    "de",
    "fr",
    "es",
    "it",
    "nl",
    "pl",
    "pt",
    "ru",
    "uk",
    "zh-Hans",
)
