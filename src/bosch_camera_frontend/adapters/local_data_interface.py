"""Local data interface: status lookup and credential-free-of-cloud stream source.

Cloud status endpoint (per camera, GET, read-only, never returns a password):
  200 {"username": str}            -> active
  404                              -> inactive (normal "off" state)
  449                              -> unsupported firmware
Any other status / network error / malformed body keeps the last known value.
Only Gen2 cameras on firmware >= LDI_MIN_FIRMWARE are queried.

When the interface is active and a password is stored for the camera, the
stream is read straight from the camera (video only, no cloud session).
The password only ever appears inside the source URL handed to go2rtc/ffmpeg;
use :func:`redact_urls` before logging anything that could contain it.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any
from urllib.parse import quote

import requests

_LOGGER = logging.getLogger(__name__)

LDI_ENDPOINT = "onvif_user"
LDI_MIN_FIRMWARE: tuple[int, ...] = (9, 40, 105)
LDI_USER = "localuser"
LDI_RTSP_PORT = 9554
LDI_STREAM_PATH = "/live"
LDI_PASSWORD_KEY = "local_data_password"
LDI_SOURCE_TYPE = "LOCAL_DATA"

STATE_ACTIVE = "active"
STATE_INACTIVE = "inactive"
STATE_UNSUPPORTED = "unsupported"

GEN2_MODELS = frozenset({"HOME_Eyes_Outdoor", "HOME_Eyes_Indoor"})
_MAX_PASSWORD_LEN = 128
_PASSWORD_RE = re.compile(r"[\x21-\x7e]+")
_URL_USERINFO_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@")

MSG_NEED_PASSWORD = "Local data interface is active - set its password in Settings."
MSG_NO_LAN_IP = "Local data interface: no usable LAN address known for this camera."

# cam_id -> last known status entry
_status_cache: dict[str, dict[str, Any]] = {}


def parse_firmware(version: object) -> tuple[int, ...] | None:
    """Parse a dotted numeric firmware string; None for anything else."""
    if not isinstance(version, str):
        return None
    parts = version.strip().split(".")
    # Length cap: int() raises ValueError on absurdly long digit strings.
    if not all(p.isascii() and p.isdigit() and len(p) <= 9 for p in parts):
        return None
    return tuple(int(p) for p in parts)


def firmware_supports_ldi(version: object) -> bool:
    """True when the installed firmware is at or above the interface gate."""
    parsed = parse_firmware(version)
    return parsed is not None and parsed >= LDI_MIN_FIRMWARE


def is_gen2(cam_info: dict[str, Any]) -> bool:
    """True for Gen2 camera models (Gen1 and unknown models never qualify)."""
    return cam_info.get("model") in GEN2_MODELS


def should_query(cam_info: dict[str, Any]) -> bool:
    """Only Gen2 cameras with a new-enough firmware are asked for status."""
    return is_gen2(cam_info) and firmware_supports_ldi(cam_info.get("firmware"))


def state_from_response(status: int, body: object) -> dict[str, Any] | None:
    """Map an HTTP result to a cache entry, or None to keep the last value."""
    if status == 200:
        if isinstance(body, dict) and isinstance(body.get("username"), str):
            return {"state": STATE_ACTIVE, "username": body["username"]}
        return None
    if status == 404:
        return {"state": STATE_INACTIVE}
    if status == 449:
        return {"state": STATE_UNSUPPORTED}
    return None


def last_status(cam_id: str) -> dict[str, Any] | None:
    """Last known status entry for a camera, None if never fetched."""
    return _status_cache.get(cam_id)


def clear_status_cache() -> None:
    """Forget all cached status entries."""
    _status_cache.clear()


def fetch_status(
    session: requests.Session, cam_info: dict[str, Any], cloud_api: str
) -> dict[str, Any] | None:
    """Query the status endpoint and return the (possibly kept) cache entry.

    None when the camera is not eligible or no value is known yet. Failures of
    any kind leave the previous value untouched.
    """
    cam_id = cam_info.get("id")
    if not isinstance(cam_id, str) or not cam_id or not should_query(cam_info):
        return None
    try:
        resp = session.get(
            f"{cloud_api}/v11/video_inputs/{cam_id}/{LDI_ENDPOINT}", timeout=10
        )
        body: object = None
        if resp.status_code == 200:
            body = resp.json()
        entry = state_from_response(resp.status_code, body)
    except (requests.RequestException, ValueError):
        _LOGGER.debug("local data interface status fetch failed")
        return _status_cache.get(cam_id)
    if entry is not None:
        _status_cache[cam_id] = entry
    return _status_cache.get(cam_id)


def valid_lan_ip(value: object) -> str | None:
    """Return the address when it is a plain private LAN IP, else None."""
    if not isinstance(value, str):
        return None
    try:
        addr = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_unspecified
        or addr.is_multicast
        or addr.is_reserved
        or not addr.is_private
    ):
        return None
    return str(addr)


def valid_password(value: object) -> str | None:
    """Return the password when it has a plausible sticker format, else None."""
    if not isinstance(value, str) or len(value) > _MAX_PASSWORD_LEN:
        return None
    return value if _PASSWORD_RE.fullmatch(value) else None


def stored_password(cam_info: dict[str, Any]) -> str | None:
    """The camera's stored, format-valid password, or None."""
    return valid_password(cam_info.get(LDI_PASSWORD_KEY))


def source_url(ip: str, password: str) -> str:
    """Stream source URL for the camera; the password is percent-encoded."""
    return (
        f"rtsps://{LDI_USER}:{quote(password, safe='')}@{ip}:{LDI_RTSP_PORT}"
        f"{LDI_STREAM_PATH}"
    )


def redact_urls(text: str) -> str:
    """Replace the userinfo of every URL in `text`."""
    return _URL_USERINFO_RE.sub(r"\g<scheme>***@", text)


def local_source_wanted(cam_id: str, cam_info: dict[str, Any]) -> bool:
    """True when the camera must be read locally (active + password set)."""
    entry = last_status(cam_id)
    return (
        entry is not None
        and entry.get("state") == STATE_ACTIVE
        and stored_password(cam_info) is not None
    )


def needs_password(cam_id: str, cam_info: dict[str, Any]) -> bool:
    """Active interface but no usable password: stays on the cloud path."""
    entry = last_status(cam_id)
    return (
        entry is not None
        and entry.get("state") == STATE_ACTIVE
        and stored_password(cam_info) is None
    )


def resolve_local_source(cam_info: dict[str, Any]) -> dict[str, object] | None:
    """Stream-info dict for the local source, None when it cannot be built.

    Same shape as the cloud resolver's result; never contacts the cloud.
    """
    password = stored_password(cam_info)
    ip = valid_lan_ip(cam_info.get("local_ip"))
    if password is None or ip is None:
        return None
    return {"url": source_url(ip, password), "type": LDI_SOURCE_TYPE}


def local_failure_message(cam_info: dict[str, Any]) -> str:
    """User-facing reason why a required local source is unavailable."""
    if valid_lan_ip(cam_info.get("local_ip")) is None:
        return MSG_NO_LAN_IP
    return (
        "Local stream unavailable - check the password and that privacy mode "
        "is off (the camera closes the stream while privacy mode is on)."
    )
