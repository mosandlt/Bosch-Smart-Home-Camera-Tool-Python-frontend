# Bosch Smart Camera — Python Frontend (NiceGUI)

> Desktop & mobile web UI for Bosch Smart Home cameras, built with NiceGUI.
> Replaces the official iOS/Android app with a browser-based interface.

> **Alpha — on PyPI:** `pip install bosch-camera-frontend` (self-contained, pulls the CLI). See [Installation](#installation).
> Current release: **v0.4.1-alpha** · Phase 1 working end-to-end (dashboard, camera detail, settings). Phase 2 **live video has landed**: a snapshot-tier near-live view plus an optional real **WebRTC/HLS player** (via go2rtc) with audio, Picture-in-Picture (survives a backgrounded tab) and fullscreen — plus a broad set of Phase 4 device-control cards (pan, motion/intrusion/sound detection, WiFi, lighting schedule, cloud recording, siren, automation rules, friends/sharing) and a local continuous-recording (Mini-NVR Phase 1, Beta) card. Phase 3 (FCM push events + in-app auth) is next.

> **Status:** Live cloud camera-list (no longer hostage to a stale local config), HA/Apple-style design (rounded-2xl cards, 16:9 hero snapshot, soft shadows, translucent header), structured privacy-toggle error reporting ("Camera offline" / "Auth expired" instead of "check token"), in-app Reload-from-disk button on Settings (after running `python3 bosch_camera.py token fix` in a terminal). The camera-detail Live Stream section now plays real WebRTC when [go2rtc](https://github.com/AlexxIT/go2rtc) is installed and falls back to a ~5 s snapshot loop otherwise. **Note:** the WebRTC/HLS live-player code path is implemented and unit-tested but not yet confirmed against a live go2rtc + real camera + browser session — see the Roadmap's open Phase 2 item.
>
> **Engineering:** runs on **NiceGUI 3.12** · cloud I/O is non-blocking (`asyncio.to_thread`) so the UI never freezes during network calls · the rtsps URL (with embedded creds) stays server-side — the browser only ever gets the go2rtc base URL + stream name · session secret is generated, never hardcoded · `mypy --strict` clean · **~99% test coverage** (571 tests as of v0.4.0-alpha) · CI on Python 3.11–3.13 (`ruff` + `ruff format` + `mypy --strict` + `pytest`).
>
> **Interested? Let me know!** Open an [issue](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python-frontend/issues) or start a [discussion](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python-frontend/discussions). Feature requests, ideas, and pull requests are welcome.

---

## Why NiceGUI?

| Criterion | NiceGUI | PySide6 | Flask/FastAPI | Flet | Streamlit |
|---|---|---|---|---|---|
| **Live video (HLS)** | Good (hls.js) | Excellent (native RTSP) | Excellent | Fair | Poor |
| **Snapshots** | Very good | Excellent | Excellent | Good | Good |
| **Dashboard layout** | Very good (Tailwind) | Excellent | Full control | Good | Limited |
| **Mobile access** | Yes (browser) | No | Yes (browser) | Partial | Laggy |
| **Dev speed** | Fast | Medium | Medium | Fast | Fast start, slow later |
| **Maturity** | Medium | Very high | High | Low-medium | High |
| **Lines of code needed** | Low | High | Medium-high | Low | Low |

**NiceGUI wins** because:
- Pure Python — no HTML/JS/CSS to write (Tailwind built-in)
- Runs in any browser — phone, tablet, desktop
- WebSocket bridge for real-time FCM push event updates
- HLS video via embedded hls.js player
- Single-file prototyping possible, scales to multi-page app
- Auto-reload during development

**PySide6 would be the alternative** if native desktop (no browser) + direct RTSP playback without transcoding is required. But no mobile access.

---

## Architecture

```
┌──────────────┐     WebSocket      ┌──────────────────────┐
│  Browser     │ ◄────────────────► │  NiceGUI Server      │
│  (any device)│                    │  (Python)             │
└──────────────┘                    └──────────┬───────────┘
                                               │
                              ┌────────────────┼────────────────┐
                              │                │                │
                    ┌─────────▼──────┐  ┌──────▼──────┐  ┌─────▼──────┐
                    │ Bosch Cloud API│  │ FFmpeg       │  │ FCM Push   │
                    │ (REST)         │  │ RTSP→HLS     │  │ Listener   │
                    └────────────────┘  └─────────────┘  └────────────┘
```

### Components

1. **NiceGUI web server** — serves the UI, handles all Bosch API calls
2. **API wrapper** — imports functions from existing `bosch_camera.py` (no duplication)
3. **FFmpeg transcoder** — converts RTSPS live stream to HLS segments for browser playback
4. **FCM push listener** — receives real-time events, pushes to browser via WebSocket
5. **Browser client** — renders dashboard, plays HLS video via hls.js

### Key Design Decisions

- **Do NOT duplicate API logic.** Import and wrap `bosch_camera.py` functions.
- **FFmpeg is required** for live video — browsers can't play RTSPS directly.
- **One server, many clients** — NiceGUI supports multi-user access out of the box.
- **Token management** — handled server-side, auto-renewal on expiry.

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| UI framework | [NiceGUI](https://nicegui.io/) 3.x (≥3.12) | Python web UI with Tailwind CSS |
| Video player | [hls.js](https://github.com/video-dev/hls.js/) | HLS playback in browser |
| Transcoder | FFmpeg | RTSPS → HLS segment conversion |
| API client | `requests` (from existing CLI) | Bosch Cloud API communication |
| Push notifications | `firebase-messaging` | FCM push reception |
| Auth | OAuth2 PKCE (from existing `get_token.py`) | Bosch SingleKey ID login |

### Requirements

```bash
pip install -r requirements.txt   # nicegui>=3.12, requests, urllib3, defusedxml
brew install ffmpeg               # only needed for Phase 2 live video
```

Python 3.10+ (CI runs 3.11–3.13). `defusedxml` is pulled in transitively via the
CLI bridge (`bosch_camera` → `bosch_maintenance`), so it must be installed even
though the frontend never imports it directly.

---

## File Structure

```
Bosch-Smart-Home-Camera-Tool-Python-frontend/
  src/bosch_camera_frontend/
    __init__.py            — package + CLI-path injection
    app.py                 — NiceGUI app entry point (argparse, ui.run)
    adapters/
      cli_bridge.py        — typed re-export of bosch_camera.py + async_* twins
      go2rtc_manager.py    — shared go2rtc subprocess (spawn, REST add/remove stream)
      stream_session.py    — keeps a go2rtc registration fresh vs Gen2 cred rotation
      nvr_manager.py       — local continuous-recording ffmpeg process per camera (Mini-NVR Phase 1, Beta)
    pages/
      dashboard.py         — camera overview grid
      camera_detail.py     — single-camera view (snapshot, live stream, controls, events)
      settings.py          — config / token status / language
    components/
      camera_card.py       — camera status card widget
      live_player.py       — go2rtc WebRTC/HLS player (ported from the ioBroker engine)
      live_snapshot_player.py — snapshot-refresh near-live view (no-go2rtc fallback)
      hls_player.py        — legacy hls.js placeholder (superseded by live_player)
  tests/                   — pytest suite (conftest fake-NiceGUI harness, 99% cov)
  .github/workflows/ci.yml — ruff + ruff format + mypy --strict + pytest
  requirements.txt
  pyproject.toml
```

---

## Live Video (WebRTC + HLS) — How It Works

Browsers cannot play RTSPS streams directly, so [go2rtc](https://github.com/AlexxIT/go2rtc) bridges the Bosch RTSPS feed to WebRTC (sub-second) with an automatic HLS fallback:

```
Camera → Bosch Cloud Proxy → rtsps:// stream
                                  │
                  go2rtc (one shared subprocess, managed by the app)
                                  │
            WebRTC  ─────────────┴───────────── HLS (.m3u8) fallback
                                  │
              browser <video> (LivePlayer engine: audio · PiP · fullscreen)
```

1. **Resolve** — the app asks the Python CLI (`get_stream_url`) for the camera's
   `rtsps://` URL via `PUT /connection`.
2. **Register** — `Go2rtcManager` registers it with go2rtc (`PUT /api/streams`,
   rewriting `rtsps://`→`rtspx://` so go2rtc skips the Bosch cert hostname check).
   The URL with embedded creds **stays server-side** — go2rtc consumes it on
   localhost; the browser only ever receives the go2rtc base URL + stream name.
3. **Play** — the browser `LivePlayer` (a framework-free port of the live-confirmed
   ioBroker `Go2rtcStream`: WebRTC-first, HLS fallback, reconnect-keeps-audio,
   pause-guard, stall-checker) attaches to a `<video>` and signals go2rtc over
   `POST /api/webrtc`.

**No go2rtc installed?** The Live Stream section automatically falls back to a
~5 s snapshot-refresh loop (`LiveSnapshotPlayer`) — still useful, just not video.

**Session refresh:** the Bosch session/creds rotate (Gen2 cameras rotate Digest
creds on every `PUT /connection`, and the proxy hash expires). `StreamSession`
periodically re-resolves the URL and re-registers the go2rtc source ahead of
expiry; go2rtc swaps the source in place and the player rides the brief blip.

> **TLS note:** the underlying Python CLI verifies Bosch cloud TLS using a pinned
> Bosch CA certificate (since CLI v10.10.2). The `rtspx://` rewrite only skips
> go2rtc's *RTSP-client* hostname check on the already-authenticated media hop.

---

## Supported Cameras

Same camera lineup as the rest of the Bosch Smart Home Camera Tool family — exactly four models:

| Model | Generation | Notes |
|---|---|---|
| Eyes Outdoor (SVO-1601-220) | Gen1 | outdoor, spotlight |
| 360° Indoor (SVI-1609-5) | Gen1 | indoor, pan |
| Eyes Outdoor II | Gen2 | outdoor, RGB wallwasher |
| Eyes Indoor II | Gen2 | indoor, siren |

Which controls appear on the camera-detail page (pan slider, siren, sound detection, RGB wallwasher, etc.) is derived from the camera's own reported model/generation and feature flags — cards for unsupported features are hidden rather than shown disabled.

---

## Installation

**Prerequisites:**
- Python 3.10+
- A valid `bosch_config.json` with bearer token (created by the first-run wizard in the [Python CLI](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python))

### Option A — install from PyPI (recommended)

```bash
pip install bosch-camera-frontend
```

This pulls the CLI (`bosch-smart-home-camera-tool`) in automatically, so the install is self-contained — no sibling checkout needed. Start it with the `bosch-camera-frontend` command (see [Usage](#usage)).

### Option B — from source (development)

```bash
# Clone this repo (as sibling to the Python CLI repo)
git clone https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python-frontend
cd Bosch-Smart-Home-Camera-Tool-Python-frontend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

In a source checkout the frontend auto-discovers the CLI in a sibling directory. Override with:
```bash
export BOSCH_CAMERA_CLI_PATH=/path/to/Bosch-Smart-Home-Camera-Tool-Python
```

## Usage

When installed from PyPI, use the `bosch-camera-frontend` command. From a source checkout, use `python3 -m bosch_camera_frontend.app` (both accept the same flags).

```bash
# Start on localhost:8080 (default)
bosch-camera-frontend
# or, from source:
python3 -m bosch_camera_frontend.app

# Custom port + config path
bosch-camera-frontend --port 8081 --config /path/to/bosch_config.json

# Dev mode with hot-reload
bosch-camera-frontend --reload

# Custom CLI repo path (source/dev only)
bosch-camera-frontend --cli-path /path/to/Bosch-Smart-Home-Camera-Tool-Python
```

Open http://localhost:8080 in your browser. The dashboard shows all cameras from your config.

**Security note:** Default binds to `127.0.0.1` (localhost only). Do NOT expose to the network without authentication (Phase 3 feature). The NiceGUI session cookie is signed with a secret resolved at startup: set `BOSCH_FRONTEND_STORAGE_SECRET` for a stable secret across restarts, otherwise a per-process random secret is generated (sessions reset on restart). No secret is hardcoded in the source.

---

## Development & Testing

```bash
pip install -e ".[dev]"          # runtime + pytest, pytest-asyncio, pytest-mock
pip install ruff mypy pytest-cov

ruff check src/ tests/           # lint
ruff format --check src/ tests/  # formatting
mypy --strict src/bosch_camera_frontend
pytest -q --cov=src/bosch_camera_frontend --cov-report=term-missing
```

- **Tests don't need a browser or network:** `tests/conftest.py` installs a fake
  NiceGUI and mocks the CLI bridge, so page/component handlers run headless.
  Coverage is **99% across 247 tests**; fixtures use fake IDs only.
- **CI** (`.github/workflows/ci.yml`) runs the four gates above on Python
  3.11–3.13 and checks out the sibling CLI repo so the bridge resolves.

---

## Roadmap

Mapped from iOS app v2.11.2. Phase 1 shipped in v0.1.1-alpha; the live-video core of Phase 2 landed in v0.1.2-alpha. Items marked ✅ are done.

### Phase 1 — Core Dashboard ✅ (v0.1.1-alpha)

- [x] Camera status cards (ONLINE/OFFLINE, model, firmware)
- [x] Live snapshot display (auto-refresh every 30s)
- [x] Event list with thumbnails (last 50 events)
- [x] Privacy mode toggle per camera
- [x] Camera light toggle (outdoor)
- [x] Notification toggle
- [x] Token status + auto-renewal indicator
- [x] Async snapshot refresh (non-blocking via `asyncio.to_thread`)
- [x] Random `storage_secret` generated at first run (env `BOSCH_FRONTEND_STORAGE_SECRET` or per-process random)

### Phase 2 — Live Video & Controls (in progress)

- [x] go2rtc subprocess manager (`Go2rtcManager`: spawn, REST add/remove stream)
- [x] WebRTC/HLS player wired (`LivePlayer`, ported from the ioBroker engine) with audio, Picture-in-Picture, fullscreen
- [x] Snapshot-tier near-live fallback when go2rtc is absent (`LiveSnapshotPlayer`)
- [x] Session/credential refresh vs Gen2 rotation (`StreamSession`)
- [x] Light toggle wired to live API (`cli_bridge.async_get/set_light_override`, `PUT /v11/video_inputs/{id}/lighting_override`)
- [x] Motion detection enable + sensitivity select wired to live API (`async_get/set_motion_detection`, `PUT .../motion`)
- [x] Intrusion detection enable + mode/sensitivity/distance wired to live API (`async_get/set_intrusion_detection`, `PUT .../intrusionDetectionConfig`)
- [x] Unread event badge on each camera card (`async_get_unread_count`, `GET /v11/video_inputs/{id}` → `numberOfUnreadEvents`)
- [x] Pan control slider (CAMERA_360) wired to Bosch `cmd_pan` (`async_get/set_pan`, `GET`/`PUT .../pan`)
- [x] Glass-break / fire-alarm sound detection toggle (Gen2, `async_get/set_audio_detection`, `GET`/`PUT .../audioDetectionConfig`)
- [x] WiFi signal strength display (read-only, `async_get_wifi_info`, `GET .../wifiinfo`)
- [x] Lighting schedule (read + write, outdoor Eyes cameras, `async_get/set_lighting_schedule`, `GET`/`PUT .../lighting_options`)
- [x] Recording sound toggle (`async_get/set_recording_options`, `GET`/`PUT .../recording_options`)
- [x] Siren trigger button + duration (Gen2 Indoor II only, `async_trigger_siren` / `async_get/set_alarm_settings`)
- [x] Automation rules editor (list/add/delete, `async_list/add/edit/delete_rule`, `GET`/`POST`/`PUT`/`DELETE .../rules`)
- [x] Camera sharing management (friends: list/invite/remove/share/unshare, `async_*_friend`/`async_*share_camera`, `GET`/`POST`/`DELETE`/`PUT /v11/friends*`)
- [x] Local continuous recording (Mini-NVR Phase 1, Beta): per-camera ffmpeg segment recorder (`NVRManager`), folder input + on/off switch on the camera detail page — `event_buffered` (ring-buffer preroll + motion postroll) is explicitly out of scope for Phase 1
- [ ] Notifications toggle wired to live API (currently a stub)
- [ ] Auto-follow toggle
- [ ] Audio alarm threshold slider
- [ ] Video quality select (auto/high/low)
- [ ] Live runtime verification on real hardware (go2rtc + camera + browser)

### Phase 3 — Events, Auth & Real-Time

- [ ] FCM push listener background task (reuse CLI `_watch_fcm_push`)
- [ ] Real-time event feed in camera detail via NiceGUI WebSocket
- [ ] HTTP Basic Auth middleware (env-var password)
- [ ] Event detail view: snapshot + clip download
- [ ] Clip re-request button (POST /clip_request)
- [ ] Mark as read / favorite
- [ ] Event type filter (MOVEMENT, PERSON, AUDIO_ALARM, etc.)

### Phase 4 — Advanced Features

- [ ] Intercom (listen-only audio player) — cloud connection-tunnel plumbing exists CLI-side, not yet wired here
- [ ] RCP protocol reads (camera info, clock, dimmer)
- [ ] Ambient light sensor value
- [ ] Multi-camera grid view
- [ ] Zones / privacy-masks editor (read+write UI) — needs a new canvas/SVG overlay component, no reusable drawing primitive exists in this codebase yet
- [ ] Mini-NVR event-buffered mode (ring-buffer preroll + motion postroll) — Phase 1 shipped continuous-only recording; event-buffered mode is a distinct, larger feature (see the HA integration's richer implementation) and is tracked separately
- [ ] NVR local-disk clip browse/prune UI — recordings are written to the configured folder but there's no in-app browser for them yet
- [ ] Diagnostics display (RCP/feature flags/maintenance) — `cli_bridge.get_feature_flags` exists (list-normalized) but has no UI card yet

### Phase 5 — Polish

- [ ] Dark mode
- [ ] Mobile-optimized layout (responsive cards)
- [ ] PWA support (installable on iOS/Android home screen)
- [ ] Notification sound on new event
- [ ] Settings page (token, download path, polling interval)
- [ ] German + English language toggle

---

## Legal Notes

- This is a personal side project for interoperability with user-owned hardware
- Covered by § 69e German Copyright Act (UrhG) and EU Directive 2009/24/EC
- No Bosch code is copied — only API protocol communication is reimplemented
- No Bosch trademarks in the project name (use neutral naming)
- Firebase API keys are public app identifiers (embedded in every Bosch app install)
- OAuth client secret is a public app-level key (not a personal credential)

---

## Integration Comparison

How this tool compares to the rest of the Bosch Smart Home Camera ecosystem (Home Assistant integration, Python CLI, ioBroker adapter, MCP server, this NiceGUI frontend, and the Node-RED nodes):

| Feature | [Home Assistant Integration](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-HomeAssistant) | [Python CLI Tool](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python) | [ioBroker Adapter](https://github.com/mosandlt/ioBroker.bosch-smart-home-camera) | [MCP Server](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-MCP) | [Frontend (NiceGUI)](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python-frontend) | [Node-RED](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-NodeRED) |
|---|---|---|---|---|---|---|
| **Maturity** | v15.0+ — HA Quality Scale **Platinum** | v10.12+ stable (Mini-NVR BETA) | v1.8+ stable · npm | v1.7+ stable · PyPI | v0.4.0 **alpha** · PyPI | v0.4.0 **alpha** · npm |
| **Platform** | Home Assistant (HACS) | Standalone Python 3.10+ CLI | ioBroker (npm) | Python 3.10+ · pipx / uvx · stdio + streamable-HTTP for MCP clients (Claude Desktop, Claude Code, custom) | NiceGUI web app · Python 3.10+ | Node-RED palette · npm |
| **Login** | OAuth2 PKCE (browser) | OAuth2 PKCE (browser) | OAuth2 PKCE (browser) | OAuth2 PKCE (browser, one-time) | ◑ shares CLI `bosch_config.json` | ◑ refresh-token from CLI |
| **Snapshots** | ✅ Native `Camera.image` | ✅ `snapshot` command | ✅ File-store + base64 DP | ✅ `bosch_camera_snapshot` (LAN-only) | ✅ live + event fallback | ✅ `snapshot` node |
| **Live RTSP stream (LAN)** | ✅ via HA Stream component | ✅ ffmpeg/RTSPS output | ✅ TLS proxy → local RTSP | ✅ `bosch_camera_stream_url` (LAN-only, no cloud relay) | ◑ internal (go2rtc) | ◑ `stream-url` node (URL only) |
| **WebRTC (sub-second latency)** | ✅ via integrated go2rtc | ✅ *(v10.6.0)* `live --webrtc` | ❌ | ❌ | ✅ via go2rtc (else snapshot) | ❌ |
| **Dual-stream URL (main + sub)** | ✅ `sensor.bosch_<n>_stream_url` + `_sub` *(v12.4.0, opt-in per cam)* | ✅ `info` shows both · `live --sub` *(v10.5.0)* | ✅ `stream_url` + `stream_url_sub` *(v0.5.3 experimental)* | ◑ `bosch_camera_stream_url` — main stream only | ❌ *(sub-stream only)* | ◑ URL only — no sub option |
| **External recorder (BlueIris, Frigate)** | ✅ via go2rtc | ✅ stdout pipe | ✅ Digest-creds URL + LAN bind option | ✅ URL returned, hand off to ffmpeg / go2rtc downstream | ❌ | ◑ `stream-url` → wire downstream |
| **Privacy mode** | ✅ switch entity | ✅ command | ✅ DP | ✅ `bosch_camera_privacy_set` (LAN-fallback via `prefer_local`) | ✅ toggle | ✅ `privacy` node |
| **Front spotlight (Gen1/Gen2)** | ✅ light entity | ✅ command | ✅ DP | ✅ `bosch_camera_light_set` (LAN-fallback) | ❌ *(Phase 2 stub)* | ✅ `bosch-camera-light` node *(v0.3.0-alpha)* |
| **RGB wallwasher (Gen2 Outdoor II)** | ✅ light w/ RGB | ◑ on/off only — no RGB | ✅ color + brightness DPs | ❌ *(on/off only — RGB not exposed)* | ❌ | ◑ on/off + intensity only — no RGB *(v0.3.0-alpha)* |
| **Panic-alarm siren** | ✅ button entity *(Gen2 Indoor II)* | ✅ command *(Gen2 Indoor II only)* | ✅ DP | ✅ `bosch_camera_siren_trigger` *(Gen2 Indoor II only)* | ✅ trigger + duration *(Gen2 Indoor II only)* | ❌ |
| **Firmware update** | ✅ Update-Entity + Repairs fix-flow, install button *(v14.4.10)* | ✅ status + install *(v10.11.0)* | ✅ firmware states + install trigger, write-lock guard *(v1.8.0)* | ✅ status + install tools *(v1.7.0)* | ◑ read-only status display, no install action | ✅ status + install nodes *(v0.4.0-alpha)* |
| **Image rotation 180°** | ✅ switch | ❌ | ✅ DP | ❌ | ❌ | ❌ |
| **Motion / person / audio events** | ✅ FCM push + polling fallback | ◑ `watch` command only (events cmd removed) | ✅ FCM push + polling fallback | ✅ `bosch_camera_events` (on-demand pull) | ◑ pull-only events table | ✅ `event` node (poll) |
| **Motion edge-trigger state** | ✅ `binary_sensor.motion` | n/a | ✅ `motion_active` DP *(v0.5.3)* | n/a *(request-response, no subscription)* | ❌ | ❌ |
| **Auto-snapshot on motion** | ✅ refreshes Camera entity | n/a | ✅ writes `last_event_image` base64 *(v0.5.3)* | n/a *(no background loop)* | ❌ | ❌ |
| **Synthetic motion trigger (external sensor)** | ✅ service | n/a | ✅ DP | ❌ | ❌ | ❌ |
| **Motion zones / privacy masks** | ✅ read + write | ✅ read + write | ✅ read + write *(v1.8.0)* | ✅ get / set / clear *(v1.7.0)* | ❌ *(no visual editor yet)* | ❌ |
| **Automation rules / schedules** | ✅ read + write | ✅ read + write | ✅ full CRUD *(v1.8.0)* | ✅ list / add / edit / delete *(v1.7.0)* | ✅ full CRUD (list/add/edit/delete) | ❌ |
| **Lighting schedule** | ✅ read (write via service, Gen1 Eyes Outdoor only) | ✅ read + write | ✅ read *(Gen1-only, v1.2.0)* | ✅ get / set *(v1.7.0)* | ✅ read + write *(outdoor Eyes cameras)* | ❌ |
| **Cloud clip download (history ~30 d)** | ✅ via Media Browser | ❌ | ❌ *(parked — no community request yet)* | ❌ *(intentionally not exposed — large payloads)* | ❌ *(use CLI)* | ◑ `clip_url` in event payload |
| **Mini-NVR (local recording)** | ✅ continuous + event-buffered, ring-buffer preroll *(v11.2.0 BETA → v14.7.0 modes)* | ◑ event-triggered segment muxing, no preroll ring *(v10.7.0 BETA)* | ❌ *(delegates to external recorder via credential-free RTSP endpoint)* | ❌ *(no NVR concept)* | ◑ continuous only, no event-buffered *(v0.4.0-alpha)* | ◑ continuous only via `bosch-camera-nvr-record` node *(v0.4.0-alpha)* |
| **SMB / NAS clip upload** | ✅ | ✅ *(v10.7.0 BETA)* | ❌ | ❌ | ❌ | ❌ |
| **Camera sharing (friends)** | ✅ services (share / invite / list) | ✅ command | ✅ share / invite / remove *(Gen2 only, v1.8.0)* | ✅ list / invite / share / unshare / remove *(v1.7.0)* | ✅ list/invite/remove/share/unshare | ❌ |
| **Pan / tilt (360° Gen1)** | ✅ services | ✅ command | ✅ `pan_position` DP | ✅ `bosch_camera_pan` | ✅ slider wired to live API | ❌ |
| **Named pan presets (home / left / right / back-left / back-right)** | ✅ opt-in select entity | ✅ `pan --preset` flag | ✅ `pan_preset` DP | ✅ `bosch_camera_pan preset=` | ❌ | ❌ |
| **Two-way audio / intercom** | ❌ | ✅ command | ❌ | ◑ listen-only `bosch_camera_intercom_open` *(v1.7.0)* | ❌ | ❌ |
| **Webhook delivery on events** | ✅ service + opt-in options | ✅ `watch --webhook URL` | ✅ via MQTT bridge | ❌ *(request-response model)* | ❌ | ❌ |
| **MQTT event bridge (motion / audio / person)** | n/a *(HA event bus native)* | n/a *(single-run)* | ✅ admin-config | n/a | ❌ | ❌ |
| **Apple HomeKit (via HA Core bridge)** | ✅ documented | n/a | n/a | n/a | n/a | n/a |
| **Snapshot scheduler / time-lapse** | ✅ examples/ YAML | ✅ cron + ffmpeg examples | ✅ Blockly example | n/a | ❌ | ❌ |
| **Native dashboard card / widget** | ✅ 2 Lovelace cards (single + grid) | n/a | ✅ 2 vis-2 widgets — BoschCamera + BoschOverview multi-cam | n/a | ✅ *(is itself a web dashboard)* | ❌ |
| **Picture-in-Picture survives backgrounded tab** | ✅ `hass-suspend-when-hidden` keep-alive *(v14.0.0)* | n/a (no UI) | ✅ own PiP + freeze-recovery, Web-Worker heartbeat *(v1.7.2/v1.7.3)* | n/a (no UI) | ✅ reconnect-timeout + freeze-recovery *(v0.4.0-alpha)* | n/a (no UI) |
| **Cloud-relay REMOTE fallback** | ✅ auto-switch when LAN unreachable | ✅ remote mode | ❌ *(LOCAL-only by design)* | ❌ *(media LAN-only; status/events via cloud)* | ◑ inherits CLI | ◑ REMOTE opt (manual) |
| **Browser-based admin / config UI** | ✅ HA Config Flow | n/a (CLI) | ✅ JSON-config tabs | n/a (LLM-mediated; config via CLI / MCP client) | ✅ Settings page | ◑ editor config node |
| **UI languages** | EN · DE · FR · ES · IT · NL · PL · PT · RU · UK · ZH-Hans *(v12.4.0)* | EN · DE · FR · ES · IT · NL · PL · PT · RU · UK · ZH-Hans *(v10.3.0)* | EN · DE · FR · ES · IT · NL · PL · PT · RU · UK · ZH-CN | n/a *(no UI — LLM is the front-end)* | ◑ backend i18n · UI mostly EN | n/a *(English only)* |

## Related Projects

- [Bosch Smart Home Camera — Python CLI Tool](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python) — standalone CLI with full API access, live stream, RCP protocol, FCM push. This frontend is a thin NiceGUI layer over it (see [Architecture](#architecture)) and depends on it as a PyPI package.
- [Bosch Smart Home Camera — Home Assistant Integration](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-HomeAssistant) — custom HA integration with live video, sensors, switches, alerts
- [Bosch Smart Home Camera — ioBroker Adapter](https://github.com/mosandlt/ioBroker.bosch-smart-home-camera) — ioBroker adapter with vis-2 widgets
- [Bosch Smart Home Camera — MCP Server](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-MCP) — Model Context Protocol server for LLM clients (Claude Desktop, Claude Code, etc.)
- [Bosch Smart Home Camera — Node-RED Nodes](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-NodeRED) — Node-RED palette for flow-based automation

See the [Integration Comparison](#integration-comparison) table below for a full feature-by-feature breakdown across all six projects.

## References

- [NiceGUI Documentation](https://nicegui.io/documentation)
- [hls.js Documentation](https://github.com/video-dev/hls.js/)
- [Bosch SHC API Issue #63](https://github.com/BoschSmartHome/bosch-shc-api-docs/issues/63) — community discussion on camera API
