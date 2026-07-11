# Changelog

## 0.3.0-alpha — family-parity batch: sound detection, wifi, lighting schedule, recording, siren, pan, rules, friends

Second family-parity wiring pass (docs/family-parity-plan.md §2b), following
0.2.0's light/motion/intrusion/unread-count. Nine capabilities newly wired to
the camera detail page, all following the existing GET-then-render /
Apply-writes-back convention, all backed by new `cli_bridge.py` sync +
`async_*` wrapper pairs mirroring the Python CLI's `cmd_*` handlers 1:1:

- **Glass-break / fire-alarm sound detection** (Gen2 only): `async_get/set_audio_detection`, `GET`/`PUT .../audioDetectionConfig` — both fields always sent together (server resets the omitted one otherwise)
- **WiFi signal info** (read-only): `async_get_wifi_info`, `GET .../wifiinfo`
- **Lighting schedule** (read + write, outdoor Eyes cameras): `async_get/set_lighting_schedule`, `GET`/`PUT .../lighting_options` — read-modify-write, forces `scheduleStatus=FOLLOW_SCHEDULE` on write
- **Cloud recording sound toggle**: `async_get/set_recording_options`, `GET`/`PUT .../recording_options`
- **Siren trigger/stop + duration** (Gen2 Indoor II only): `async_trigger_siren` (existing `/panic_alarm` pattern) + new `async_get/set_alarm_settings` for the 10-300s duration field
- **Pan control**: the pre-existing Phase-2 slider stub is now wired to `async_get/set_pan`, `GET`/`PUT .../pan`
- **Automation rules editor**: list/add/delete (`async_list/add/edit/delete_rule`, full CRUD `GET`/`POST`/`PUT`/`DELETE .../rules`)
- **Friends / camera sharing**: list/invite/remove/share/unshare (`GET`/`POST`/`DELETE`/`PUT /v11/friends*`)
- **Account-level feature flags** (`cli_bridge.get_feature_flags` only, no UI card yet — normalizes Bosch's dict-or-list response shape, mirroring `cmd_feature_flags`)

Bug-hunt (3 parallel agents, mandatory before release) found and fixed 3 real
issues before shipping:
1. **Late-binding closure bug** in the friends-sharing row's revert-on-failure
   (`_toggle_share` referenced the free variable `share_switch`, which by the
   time any row's callback actually fired had already been reassigned to the
   LAST friend's switch — a failed unshare on any earlier row would revert
   the wrong switch). Fixed via a default-arg capture, same pattern already
   used for `friend_id`/`rule_id`.
2. **Re-entrant write recursion**: NiceGUI's `ValueElement` fires
   `on_value_change` for ANY value change regardless of source — so the
   recording/share switches' own `set_value(not e.value)` revert-on-failure
   re-triggered the same write handler, which (during a sustained outage)
   recurses indefinitely, hammering the API from one failed toggle. The
   recording switch's initial-load `set_value()` had the same landmine (an
   unsolicited write could fire on page load whenever the server's real
   value differed from the switch's `False` default). Fixed with a
   suppress-next-firing guard on both switches (this pre-existing pattern
   from the 0.2.0 privacy/light switches was NOT touched — out of scope for
   this diff, flagged as a known landmine there too).
3. **`get_feature_flags` type-safety gap**: a bare `cast("dict", ...)` on a
   list-shaped API response would produce a dict-typed list that crashes on
   first `.get()` call. Now normalizes list-of-dicts / list-of-scalars / dict
   exactly like the CLI's own `cmd_feature_flags`.

Cross-checked every new endpoint/payload against `bosch_camera.py`'s
`cmd_audio_detection`/`cmd_wifi`/`cmd_lighting_schedule`/`cmd_recording`/
`cmd_siren`/`cmd_pan`/`cmd_feature_flags`/`cmd_rules`/`cmd_friends` — no
mismatches found. `share_camera`/`unshare_camera` correctly preserve other
share-entry fields (e.g. `shareTime`) when rebuilding the array.

Scoped out of this release (tracked in README Phase 4): two-way intercom
(the CLI itself is listen-only — no bidirectional media tunnel via the cloud
API), zones/privacy-masks visual editor (needs a new canvas/SVG overlay
component — no drawing primitive exists in this codebase yet), local-disk
NVR/recording browse (a different feature from the cloud `recording_options`
sound toggle shipped here — no local recording pipeline in this frontend),
and a diagnostics UI card for `get_feature_flags` (function exists, wired to
nothing yet).

56 new `cli_bridge.py` functions (28 sync + 28 async twins) + 13 new UI
sections/wirings in `camera_detail.py`. 505 tests (was 416), 99.23% coverage
(gate 98%), mypy --strict / ruff / ruff format / codespell / pip-audit clean.

## 0.2.0-alpha — CI uplift to Gold tier + light/motion/intrusion/unread-count wiring

- **CI uplift** (family Gold-tier parity, reference: HA integration): coverage
  gate enforced (`--cov-fail-under=98`, was measured/unenforced); blocking
  `pip-audit` step; new `codeql.yml` (CodeQL SAST); new `secret-scan.yml` +
  `.gitleaks.toml` (gitleaks, allowlisted for this repo's own FAKE test
  fixtures only); new `dependency-review.yml` (PR-time dependency-review
  action); `[tool.ruff]`/`[tool.mypy]` sections added to `pyproject.toml` so
  a bare local `ruff check`/`mypy` run resolves identically to CI instead of
  relying on CLI-flags-only config that could silently diverge
- **Camera light control** wired end-to-end: `cli_bridge.get_light_override`/
  `set_light_override` (mirrors the CLI's `cmd_light` `GET`/`PUT
  .../lighting_override`), with a live-state toggle on the camera detail page
  (was a `# TODO Phase 2` no-op notify)
- **Unread event-count badge** wired end-to-end: `cli_bridge.get_unread_count`
  (mirrors `cmd_unread`'s `GET .../video_inputs/{id}` →
  `numberOfUnreadEvents`), shown as a badge on each dashboard camera card
  (was a `# TODO Phase 3` stub). A failed fetch (401/5xx) leaves the badge
  untouched rather than hiding it, so a transient auth/network blip can't be
  mistaken for "no unread events"
- **Motion detection** (enable + sensitivity) wired end-to-end: new
  "Motion Detection" card on the camera detail page, backed by
  `cli_bridge.get/set_motion_detection` (mirrors `cmd_motion`'s
  `GET`/`PUT .../motion`)
- **Intrusion detection** (enable + mode + sensitivity + distance) wired
  end-to-end: new "Intrusion Detection" card, backed by
  `cli_bridge.get/set_intrusion_detection` (mirrors `cmd_intrusion`'s
  `GET`/`PUT .../intrusionDetectionConfig`); `detectionMode` is always
  forwarded on Apply since this is a full-object PUT (like light/motion) —
  omitting it risked the server silently resetting the zone/all-motions mode
  on every Apply (caught by a 3-agent bug-hunt before release)
- A failed "Apply" on motion/intrusion now re-syncs from the server instead
  of leaving the UI showing unconfirmed values, matching the pre-existing
  privacy/light toggle revert-on-failure behavior
- 416 tests (was 397), mypy --strict / ruff / ruff format clean, 99.35%
  coverage, `pip-audit` clean

---

## 0.1.6-alpha — Sticky-HLS fallback + bounded hls.js fatal-error retry

- Live player reliability, ported from the HA integration's v13.7.9 fix: once
  the existing freeze detection confirms a dead WebRTC track, the player
  latches onto HLS for the rest of the session instead of endlessly retrying
  WebRTC — this breaks the "connecting/live" flip loop that could occur on
  networks unable to decode WebRTC frames (e.g. CGNAT/5G)
- Fatal hls.js network/media errors now get up to 3 bounded in-place retries
  before falling back to a full reconnect, instead of one error ending
  playback (parity with HA v14.4.0)
- CI: fixed a release-workflow bug where editing an existing GitHub release
  with `--generate-notes` would crash (create-only flag), closed a shell
  command-injection vector in changelog extraction, and a missing
  CHANGELOG.md section now hard-fails release notes generation instead of
  silently falling back to auto-generated notes
- Docs: corrected siren support scope (Gen2 Indoor II only, not the older
  360° indoor camera) and tidied the architecture/WebRTC-plan docs

---

## 0.1.5-alpha — Web-Worker heartbeat for PiP-freeze detection

- Web-Worker heartbeat: detects Picture-in-Picture freeze after tab backgrounding and auto-recovers; parity with HA v13.7.5

---

## 0.1.4-alpha

- Recover frozen Picture-in-Picture after a background tab switch

---

## 0.1.3-alpha

- Fix event timestamp formatting (offset bracket)
