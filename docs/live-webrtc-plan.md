# Live WebRTC/HLS player — build plan (Phase 2/3)

STATUS: planned (2026-06-15). Snapshot-tier live view already shipped
(`components/live_snapshot_player.py`); this doc is the roadmap to bring the
NiceGUI frontend's live stream to the HA card / ioBroker widget level — real
WebRTC/HLS video with audio.

## Why it's a project, not a fix
The Python CLI has NO live-stream backend (only snapshots via `snap_from_proxy` +
the cloud API). It CAN obtain the camera's `rtsps://` URL (`bosch_camera.py`
`_open_rtsps_stream`, via `PUT /v11/video_inputs/{id}/connection` → `rtspsUrl`),
but browsers cannot play `rtsps://` directly — a go2rtc bridge is required to
transcode it to WebRTC/HLS. None of that orchestration exists yet.

## Components to build
1. **CLI stream-URL accessor** — `cli_bridge.async_get_stream_url(cam_info, token, cfg)`
   returning the live `rtsps://…` (wrap the `PUT /connection` path that
   `_open_rtsps_stream` already uses). Returns the URL + the connection type.
2. **go2rtc orchestration** (`adapters/go2rtc_manager.py`):
   - detect binary (`shutil.which("go2rtc")`) — already stubbed in `hls_player.py`.
   - start a managed subprocess (one per app, not per camera); health-check.
   - register a stream per camera: `PUT {go2rtc}/api/streams?name=<cam>&src=<rtspsx-url>`
     (use `rtspsx://` so go2rtc keeps a single producer); verify via
     `GET /api/streams?src=<cam>`.
   - serve: WebRTC `{go2rtc}/api/webrtc?src=<cam>`, HLS `{go2rtc}/api/stream.m3u8?src=<cam>`.
3. **rtsps session/credential refresh** — Gen2 cameras ROTATE the Digest creds on
   each `PUT /connection`, so the `rtspsUrl` goes stale (same problem HA solves
   with `tls_proxy.py` + a heartbeat). Two options:
   - (a) periodic re-`PUT /connection` + re-register the go2rtc source (simpler,
     brief reconnect on rotation), or
   - (b) port HA's local TLS proxy (`custom_components/bosch_shc_camera/tls_proxy.py`)
     to Python-standalone so go2rtc consumes a stable local `rtsp://127.0.0.1:port`
     and the proxy owns the rotating session (robust, more work). Recommended (b)
     for Gen2; (a) is fine for Gen1.
4. **Browser player** — reuse the ioBroker `Go2rtcStream` logic (plain JS, in
   `ioBroker .../src-widgets/src/lib/go2rtc.js`): WebRTC-first + HLS fallback with
   ALL the v13.5.17 fixes already applied there (single-ontrack, ICE-failed-only,
   reconnect-audio via shared AudioContext, pause-guard, stall-checker, listener
   cleanup). Ship it as a static JS asset and drive it from a `LivePlayer`
   NiceGUI component (replaces the `hls_player.py` stub). Apply the same
   lifecycle/visibility pause the snapshot player already has.
5. **Plumbing** — `camera_detail.py`: when go2rtc is available + a stream URL
   resolves, render `LivePlayer` (WebRTC); else fall back to the shipped
   `LiveSnapshotPlayer`. Keep the audio/PiP-hidden-when-idle + corner-flicker
   (`isolation: isolate`) parity already in the snapshot player.

## v13.5.17 parity checklist for the WebRTC player (port from HA/ioBroker)
reconnect keeps sound · keydown-unmute only Enter/Space · pause-guard re-arm ·
pageshow/visibility recovery · listener-leak cleanup · isConnected/mounted guards ·
stall-checker for paused-while-live · ICE "disconnected" not fatal · single
pc.ontrack · isolation:isolate · audio+PiP hidden when idle.

## Testing
Needs go2rtc installed locally + a reachable Bosch camera with valid creds. The
unit-test layer (fake nicegui) can't exercise real WebRTC — gate on: go2rtc-manager
unit tests (subprocess mocked) + manual live verification + parity-review vs the
HA/ioBroker player (which IS live-confirmed).

## Effort
Multi-step: ~CLI accessor (S) + go2rtc manager (M) + session refresh / TLS-proxy
port (L, the hard part) + JS player port (M) + plumbing/tests (M). Sequence behind
its own version (frontend is alpha v0.1.x, PyPI parked).
