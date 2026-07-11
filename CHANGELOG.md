# Changelog

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
