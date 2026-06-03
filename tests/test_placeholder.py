"""Regression test for the camera-card snapshot placeholder.

Bug (found via headless visual check, 2026-06-03): _PLACEHOLDER_B64 decoded to a
half-opaque GREEN pixel (RGBA 0,255,0,127). With object-fit:cover the card
stretched it into a solid green block for offline / not-yet-loaded cameras,
instead of letting the grey #f1f3f5 background show through.

Fix: a genuinely transparent 1x1 RGBA PNG (verified out-of-band to decode to
RGBA (0,0,0,0)). These checks are dependency-free (no Pillow): they pin that the
PNG is a valid 1x1 *RGBA* image and is no longer the old green value.
"""

from __future__ import annotations

import base64

from bosch_camera_frontend.components.camera_card import (
    _PLACEHOLDER_B64,
    _PLACEHOLDER_SRC,
)

# The exact buggy value that rendered as a green block — must never come back.
_OLD_GREEN_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwAD"
    "hgGAWjR9awAAAABJRU5ErkJgCC=="
)


def test_placeholder_is_not_the_old_green_pixel() -> None:
    assert _PLACEHOLDER_B64 != _OLD_GREEN_B64


def test_placeholder_is_valid_1x1_rgba_png() -> None:
    raw = base64.b64decode(_PLACEHOLDER_B64)
    # PNG signature + IEND chunk present.
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"IEND" in raw
    # IHDR: width(4) height(4) bit_depth(1) color_type(1) starting at offset 16.
    width = int.from_bytes(raw[16:20], "big")
    height = int.from_bytes(raw[20:24], "big")
    bit_depth = raw[24]
    color_type = raw[25]
    assert (width, height) == (1, 1)
    assert bit_depth == 8
    # color_type 6 == truecolour with alpha (RGBA) — the placeholder must carry
    # an alpha channel so it can be fully transparent.
    assert color_type == 6


def test_placeholder_src_is_png_data_uri() -> None:
    assert _PLACEHOLDER_SRC == f"data:image/png;base64,{_PLACEHOLDER_B64}"
    assert _PLACEHOLDER_SRC.startswith("data:image/png;base64,")
