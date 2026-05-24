"""CLI Bridge — clean re-export of bosch_camera.py functions for the frontend.

Performs sys.path injection (via __init__._inject_cli_path) and then imports
only the public surface this UI actually needs.  All other frontend modules
import from here instead of from bosch_camera directly, keeping the dependency
boundary explicit and easy to mock in tests.

Trade-offs of sys.path injection vs. packaging:
  PRO: no duplication of API logic; CLI repo is single source of truth
  PRO: CLI updates are picked up immediately (no re-install step)
  CON: import order matters (injection must happen before first import)
  CON: tight coupling to CLI repo directory structure
  CON: no type stubs for IDE support (TODO Phase 2: generate stubs via mypy)
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import TYPE_CHECKING

# Ensure CLI path is injected before we attempt any import.
from bosch_camera_frontend import _inject_cli_path, BOSCH_CAMERA_CLI_PATH

if TYPE_CHECKING:
    import requests


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

def _bc():
    """Return the bosch_camera module (import on first call)."""
    if "bosch_camera" not in sys.modules:
        _ensure_cli_available()
    return sys.modules["bosch_camera"]


def _i18n():
    """Return the bosch_i18n module (import on first call)."""
    if "bosch_i18n" not in sys.modules:
        _ensure_cli_available()
    return sys.modules.get("bosch_i18n") or importlib.import_module("bosch_i18n")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: str | None = None) -> dict:
    """Load bosch_config.json.  Uses CLI default path if *config_path* is None."""
    bc = _bc()
    if config_path:
        # Temporarily override the module-level CONFIG_FILE constant.
        original = bc.CONFIG_FILE
        bc.CONFIG_FILE = config_path
        try:
            return bc.load_config()
        finally:
            bc.CONFIG_FILE = original
    return bc.load_config()


def save_config(cfg: dict) -> None:
    _bc().save_config(cfg)


def check_token_age(cfg: dict) -> str:
    return _bc().check_token_age(cfg)


# ---------------------------------------------------------------------------
# Session / Token
# ---------------------------------------------------------------------------

def make_session(token: str) -> "requests.Session":
    return _bc().make_session(token)


def get_token(cfg: dict) -> str:
    """Return the current bearer token (does NOT prompt for a new one)."""
    token = cfg.get("account", {}).get("bearer_token", "").strip()
    if not token:
        raise ValueError("No bearer token in config. Run: python3 bosch_camera.py token fix")
    return token


# ---------------------------------------------------------------------------
# Camera discovery & state
# ---------------------------------------------------------------------------

def get_cameras(cfg: dict, session: "requests.Session") -> dict:
    """Always live from /v11/video_inputs — the cloud is authoritative for
    names/firmware/mac. Pre-2026-05-24 we returned cfg["cameras"] which hid
    cloud-side renames and any cameras added since the last `rescan`.
    Local-only fields (local_ip / creds / download_folder) are preserved
    across refresh, keyed by camera id.
    """
    bc = _bc()
    cached = cfg.get("cameras", {}) or {}
    try:
        r = session.get(f"{bc.CLOUD_API}/v11/video_inputs", timeout=15)
        if r.status_code != 200:
            return cached or bc.get_cameras(cfg, session)
        by_id = {info.get("id"): info for info in cached.values() if info.get("id")}
        fresh: dict = {}
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
        return cached or bc.get_cameras(cfg, session)


def discover_cameras(cfg: dict, session: "requests.Session") -> dict:
    return _bc().discover_cameras(cfg, session)


def resolve_cam(cfg: dict, key: str | None) -> dict:
    return _bc().resolve_cam(cfg, key)


def api_ping(session: "requests.Session", cam_id: str) -> str:
    return _bc().api_ping(session, cam_id)


def api_get_events(
    session: "requests.Session", cam_id: str, limit: int = 10
) -> list:
    return _bc().api_get_events(session, cam_id, limit)


def api_get_camera(session: "requests.Session", cam_id: str) -> dict | None:
    return _bc().api_get_camera(session, cam_id)


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def snap_from_proxy(
    cam_info: dict, token: str, hq: bool = False, cfg: dict | None = None
) -> bytes | None:
    return _bc().snap_from_proxy(cam_info, token, hq=hq, cfg=cfg)


def snap_from_events(
    session: "requests.Session", cam_info: dict
) -> tuple[bytes | None, str]:
    return _bc().snap_from_events(session, cam_info)


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
    try:
        err = r.json().get("error", "").removeprefix("sh:")
    except Exception:
        err = ""
    if r.status_code == 444 or "camera.unavailable" in err:
        return False, "Camera offline"
    if r.status_code == 401:
        return False, "Auth expired — refresh token"
    if r.status_code == 403:
        return False, "Permission denied"
    return False, f"HTTP {r.status_code} {err or 'unknown error'}"


def get_privacy_mode(session: "requests.Session", cam_id: str) -> str | None:
    """Return "ON", "OFF", or None on error."""
    bc = _bc()
    r = session.get(f"{bc.CLOUD_API}/v11/video_inputs", timeout=10)
    if r.status_code != 200:
        return None
    for cam in r.json():
        if cam.get("id") == cam_id:
            return cam.get("privacyMode", "UNKNOWN")
    return None


def get_all_cameras_status(session: "requests.Session") -> list[dict]:
    """Return raw list from GET /v11/video_inputs (all cameras + privacyMode)."""
    bc = _bc()
    r = session.get(f"{bc.CLOUD_API}/v11/video_inputs", timeout=10)
    if r.status_code != 200:
        return []
    return r.json()


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------

def t(msg_key: str, **kwargs) -> str:
    return _i18n().t(msg_key, **kwargs)


def set_lang(lang: str) -> None:
    _i18n().set_lang(lang)


def detect_lang(cfg: dict) -> str:
    return _i18n().detect_lang(cfg)


AVAILABLE_LANGS: tuple[str, ...] = (
    "en", "de", "fr", "es", "it", "nl", "pl", "pt", "ru", "uk", "zh-Hans",
)
