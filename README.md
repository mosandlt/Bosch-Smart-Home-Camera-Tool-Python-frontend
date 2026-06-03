# Bosch Smart Camera — Python Frontend (NiceGUI)

> Desktop & mobile web UI for Bosch Smart Home cameras, built with NiceGUI.
> Replaces the official iOS/Android app with a browser-based interface.

> **Status: Phase 1 working e2e (v0.1.1-alpha)** — dashboard, camera detail, settings. Live cloud camera-list (no longer hostage to a stale local config), HA/Apple-style design (rounded-2xl cards, 16:9 hero snapshot, soft shadows, translucent header), structured privacy-toggle error reporting ("Camera offline" / "Auth expired" instead of "check token"), in-app Reload-from-disk button on Settings (after running `python3 bosch_camera.py token fix` in a terminal). Phase 2 (live stream) and Phase 3 (events + auth) are next.
>
> **Engineering:** runs on **NiceGUI 3.12** · cloud I/O is non-blocking (`asyncio.to_thread`) so the UI never freezes during network calls · session secret is generated, never hardcoded · `mypy --strict` clean · **99% test coverage (247 tests)** · CI on Python 3.11–3.13 (`ruff` + `ruff format` + `mypy --strict` + `pytest`).
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

## Planned Features (mapped from iOS app v2.11.2)

### Phase 1 — Core Dashboard

- [ ] Camera status cards (ONLINE/OFFLINE, model, firmware)
- [ ] Live snapshot display (auto-refresh every 30s)
- [ ] Event list with thumbnails (last 50 events)
- [ ] Privacy mode toggle per camera
- [ ] Camera light toggle (outdoor)
- [ ] Notification toggle
- [ ] Token status + auto-renewal indicator

### Phase 2 — Live Video & Controls

- [ ] HLS live video player (FFmpeg RTSP→HLS transcoding)
- [ ] Pan control slider (CAMERA_360, ±120°)
- [ ] Auto-follow toggle
- [ ] Motion sensitivity select
- [ ] Audio alarm threshold slider
- [ ] Recording sound toggle
- [ ] Video quality select (auto/high/low)

### Phase 3 — Events & Alerts

- [ ] Real-time event feed via FCM push
- [ ] Event detail view (snapshot + video clip)
- [ ] Clip re-request button (POST /clip_request)
- [ ] Mark as read / favorite
- [ ] Event type filter (MOVEMENT, PERSON, AUDIO_ALARM, etc.)
- [ ] Download events (JPEG + MP4)
- [ ] Unread event badge

### Phase 4 — Advanced Features

- [ ] Intercom (listen-only audio player)
- [ ] Siren trigger button (CAMERA_360)
- [ ] RCP protocol reads (camera info, clock, dimmer)
- [ ] WiFi signal strength display
- [ ] Ambient light sensor value
- [ ] Camera sharing management (friends)
- [ ] Automation rules editor
- [ ] Multi-camera grid view

### Phase 5 — Polish

- [ ] Dark mode
- [ ] Mobile-optimized layout (responsive cards)
- [ ] PWA support (installable on iOS/Android home screen)
- [ ] Notification sound on new event
- [ ] Settings page (token, download path, polling interval)
- [ ] German + English language toggle

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
    pages/
      dashboard.py         — camera overview grid
      camera_detail.py     — single-camera view (snapshot, controls, events)
      settings.py          — config / token status / language
    components/
      camera_card.py       — camera status card widget
      hls_player.py         — hls.js video player component (Phase 2 stub)
  tests/                   — pytest suite (conftest fake-NiceGUI harness, 99% cov)
  .github/workflows/ci.yml — ruff + ruff format + mypy --strict + pytest
  requirements.txt
  pyproject.toml
```

---

## HLS Live Video — How It Works

Browsers cannot play RTSPS streams directly. The solution:

```
Camera → Bosch Cloud Proxy → RTSPS stream
                                  │
                           FFmpeg (server-side)
                                  │
                        HLS segments (.m3u8 + .ts)
                                  │
                           NiceGUI serves files
                                  │
                        hls.js plays in browser
```

FFmpeg command (server-side):
```bash
ffmpeg -rtsp_transport tcp -tls_verify 0 \
  -i "rtsps://proxy-NN.live.cbs.boschsecurity.com:443/{hash}/rtsp_tunnel?inst=2&enableaudio=1&fmtp=1&maxSessionDuration=3600" \
  -c:v copy -c:a aac -f hls \
  -hls_time 2 -hls_list_size 5 -hls_flags delete_segments \
  /tmp/camera_stream/stream.m3u8
```

The NiceGUI server serves the HLS segments, and hls.js in the browser plays them with ~3-5s latency.

**Proxy session refresh:** The Bosch proxy hash expires after ~60s. The server must call `PUT /connection` periodically to get a fresh hash and restart FFmpeg with the new URL.

---

## Installation

**Prerequisites:**
- Python 3.10+
- [Bosch Smart Home Camera Python CLI](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python) cloned as a sibling directory
- A valid `bosch_config.json` with bearer token (created by first-run wizard in the CLI)

```bash
# Clone this repo (as sibling to the Python CLI repo)
git clone https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python-frontend

# Create venv and install dependencies
cd Bosch-Smart-Home-Camera-Tool-Python-frontend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The frontend auto-discovers the CLI repo in the sibling directory. Override with:
```bash
export BOSCH_CAMERA_CLI_PATH=/path/to/Bosch-Smart-Home-Camera-Tool-Python
```

## Usage

```bash
# Start on localhost:8080 (default)
python3 -m bosch_camera_frontend.app

# Custom port + config path
python3 -m bosch_camera_frontend.app --port 8081 --config /path/to/bosch_config.json

# Dev mode with hot-reload
python3 -m bosch_camera_frontend.app --reload

# Custom CLI repo path
python3 -m bosch_camera_frontend.app --cli-path /path/to/Bosch-Smart-Home-Camera-Tool-Python
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

## Migration to Phase 2/3

### Phase 2 — Live Video + Async (next milestone)
- [ ] go2rtc subprocess manager (RTSPS → HLS segments)
- [ ] HlsPlayer component fully wired (no-go2rtc prompt → real player)
- [x] Async snapshot refresh (non-blocking via `asyncio.to_thread`) ✅ done in v0.1.1-alpha
- [ ] Pan slider wired to Bosch `cmd_pan` equivalent
- [ ] Light toggle + notifications toggle wired to live API

### Phase 3 — Events, Auth, Real-Time
- [ ] FCM push listener background task (reuse CLI `_watch_fcm_push`)
- [ ] Real-time event feed in camera detail via NiceGUI WebSocket
- [ ] HTTP Basic Auth middleware (env-var password)
- [x] Random `storage_secret` generated at first run ✅ done in v0.1.1-alpha (env `BOSCH_FRONTEND_STORAGE_SECRET` or per-process random)
- [ ] Event detail view: snapshot + clip download

### Phase 4+ — Advanced Features
See full roadmap in [Planned Features](#planned-features-mapped-from-ios-app-v2112).

---

## Legal Notes

- This is a personal side project for interoperability with user-owned hardware
- Covered by § 69e German Copyright Act (UrhG) and EU Directive 2009/24/EC
- No Bosch code is copied — only API protocol communication is reimplemented
- No Bosch trademarks in the project name (use neutral naming)
- Firebase API keys are public app identifiers (embedded in every Bosch app install)
- OAuth client secret is a public app-level key (not a personal credential)
- See [legal analysis](../research/) for full details

---

## Related Projects

- [Bosch Smart Home Camera — Python CLI Tool](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python) — standalone CLI with full API access, live stream, RCP protocol, FCM push
- [Bosch Smart Home Camera — Home Assistant Integration](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-HomeAssistant) — custom HA integration with live video, sensors, switches, alerts

## References

- [NiceGUI Documentation](https://nicegui.io/documentation)
- [hls.js Documentation](https://github.com/video-dev/hls.js/)
- [Bosch SHC API Issue #63](https://github.com/BoschSmartHome/bosch-shc-api-docs/issues/63) — community discussion on camera API
