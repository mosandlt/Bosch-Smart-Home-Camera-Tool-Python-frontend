"""Regression: _format_event_ts must parse Bosch's offset-bearing timestamps.

Bosch event timestamps are in Java ZonedDateTime form, e.g.
"2026-06-18T06:06:30.499+02:00[Europe/Berlin]". fromisoformat cannot parse the
trailing RFC-9557 "[zone]" suffix, so before the fix every event time fell into
the except branch and the raw string was shown verbatim. Cross-version of HA #34.
"""

from __future__ import annotations

from bosch_camera_frontend.pages.camera_detail import _format_event_ts


def test_offset_with_zone_bracket_is_formatted() -> None:
    out = _format_event_ts("2026-06-18T06:06:30.499+02:00[Europe/Berlin]")
    # Formatted (not the raw fallback) and shows the camera-local wall clock.
    assert out == "2026-06-18 06:06:30"
    assert "[" not in out and "+" not in out


def test_z_suffix_is_formatted() -> None:
    assert _format_event_ts("2026-03-22T14:30:00Z") == "2026-03-22 14:30:00"


def test_plain_offset_without_bracket() -> None:
    assert _format_event_ts("2026-06-18T06:06:30+02:00") == "2026-06-18 06:06:30"


def test_garbage_falls_back_to_raw() -> None:
    assert _format_event_ts("not-a-date") == "not-a-date"
