# Architecture — Bosch Smart Camera Frontend (NiceGUI)

## Why NiceGUI

See README.md comparison table. Key reasons:
- Pure Python — no separate HTML/JS/CSS files
- Single-file to multi-page app without framework overhead
- Tailwind CSS built-in for responsive layout
- WebSocket bridge for real-time push (Phase 3 FCM integration)
- hls.js embed path: `ui.html()` can inject any HTML/JS snippet

## Directory Layout

```
src/bosch_camera_frontend/
  __init__.py          sys.path injection + BOSCH_CAMERA_CLI_PATH constant
  app.py               argparse + NiceGUI ui.run() entry point
  adapters/
    cli_bridge.py      re-exports CLI functions; single dependency boundary
  pages/
    dashboard.py       / route — camera grid
    camera_detail.py   /camera/{name} route
    settings.py        /settings route
  components/
    camera_card.py     NiceGUI ui.card subclass for one camera
    hls_player.py      hls.js embed (stub in Phase 1)
```

## sys.path Injection Pattern

**Rationale:** The Python CLI repo (`bosch_camera.py`) is the single source of truth for all Bosch API logic. Rather than duplicating or vendoring it, we inject its directory into `sys.path` at import time.

**Implementation:**
```python
# __init__.py
sys.path.insert(0, BOSCH_CAMERA_CLI_PATH)
# then in any module:
from bosch_camera import load_config, make_session, ...
```

**Trade-offs:**
- PRO: Zero duplication; CLI fixes apply to frontend immediately
- PRO: No packaging step; dev changes picked up on next Python import
- CON: Import order matters — `__init__` must run before any CLI import
- CON: No type stubs for IDE (bosch_camera.py has no py.typed marker)
- CON: Tight coupling to CLI repo directory structure
- MITIGATION: `cli_bridge.py` is the single import boundary; all other modules import from cli_bridge, not directly from bosch_camera

**TODO Phase 2:** Generate type stubs via `mypy --generate-stubs` or extract bosch_camera into an installable package (`pip install -e ../Bosch-Smart-Home-Camera-Tool-Python`).

## Config/Session Lifecycle

```
app.py: argparse → load_config(path) → get_token(cfg)
           ↓
   @ui.middleware → inject cfg + token into app.storage.client
           ↓
   Each page: app.storage.client.get("cfg"), .get("token")
           ↓
   cli_bridge.make_session(token) → requests.Session (module-level cached)
```

The CLI module caches a single `requests.Session` globally. The frontend reuses this session across page renders. This is safe for single-user local use. For multi-user (Phase 3), each user needs their own token and session.

## Async Story

**Phase 1 (current):** Synchronous. NiceGUI runs in an asyncio event loop, but snapshot fetches and API calls use `requests` (sync). NiceGUI wraps sync functions in `asyncio.get_event_loop().run_in_executor()` automatically for `async def` page functions. Heavy calls (snapshot, events) block the executor thread briefly.

**Phase 2 plan:** Replace `requests` calls in hot paths with `aiohttp` or wrap in `asyncio.to_thread()`. Key paths: `snap_from_proxy`, `api_get_events`, `api_ping`.

**Phase 3 plan:** FCM push listener runs as a background asyncio task; pushes events to connected browsers via NiceGUI's `ui.notify()` or custom WebSocket channel.

## Threat Model (Phase 1)

- **Scope:** Local-only tool. `--host 127.0.0.1` default binds loopback only.
- **Auth:** None in Phase 1. Anyone who can reach the port can control cameras.
- **Token exposure:** Bearer token stored in `bosch_config.json` (0o600). NiceGUI client storage holds the token in server-side dict (not sent to browser).
- **Storage secret:** `storage_secret` in `ui.run()` is a placeholder (`CHANGE-ME-PHASE3`). Must be replaced with a random secret before any network exposure.

**Phase 3 mitigations:**
- Replace `--host 127.0.0.1` option with explicit network binding guard
- Add HTTP Basic Auth middleware (single admin password via env var)
- Generate `storage_secret` from `secrets.token_hex(32)` on first run, persist in config
- Add `--no-auth` flag for local-only use

## HLS Live Stream Path (Phase 2)

```
Bosch Cloud API
    └── PUT /v11/video_inputs/{id}/connection → RTSPS URL + proxy hash
              ↓ (hash valid ~60s, auto-refresh loop)
         FFmpeg subprocess (server-side)
              -i "rtsps://proxy-NN.live.cbs.boschsecurity.com:443/{hash}/rtsp_tunnel"
              -c:v copy -c:a aac -f hls
              → /tmp/bosch_hls/{cam_id}/stream.m3u8 + *.ts files
              ↓
         NiceGUI static file server
              /hls/{cam_id}/stream.m3u8
              ↓
         hls.js in browser (HlsPlayer component)
              ~3-5s latency
```

go2rtc is the preferred Phase 2 path (simpler than raw FFmpeg management). See `knowledge-base/python-webrtc-go2rtc.md` for caveats.

## Migration Path

### Phase 2 — Live Video + Async
- Implement go2rtc subprocess manager (see `_start_go2rtc_with_camera` in CLI)
- HlsPlayer: replace stub with real hls.js player
- Convert snap fetch to `asyncio.to_thread()`
- Pan slider wired to `cmd_pan` equivalent

### Phase 3 — Events + Auth
- FCM push listener background task (reuse CLI `_watch_fcm_push`)
- Real-time event table updates via NiceGUI reactive state
- HTTP Basic Auth middleware
- Random `storage_secret` generation

### Phase 4 — Advanced Features
- Intercom (listen-only audio)
- Siren trigger (CAMERA_360)
- RCP reads (camera info, clock)
- Multi-camera grid layout

### Phase 5 — Polish
- Dark mode (NiceGUI `dark` mode)
- PWA manifest
- Mobile responsive breakpoints audit
- Settings: polling interval, download path
