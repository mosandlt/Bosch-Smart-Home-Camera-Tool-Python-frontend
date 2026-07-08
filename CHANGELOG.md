# Changelog

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
