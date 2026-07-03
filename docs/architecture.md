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
    cli_bridge.py       re-exports CLI functions; single dependency boundary
    go2rtc_manager.py   shared go2rtc subprocess (spawn, REST add/remove stream)
    stream_session.py   keeps a go2rtc registration fresh vs Gen2 cred rotation
  pages/
    dashboard.py       / route — camera grid
    camera_detail.py   /camera/{name} route
    settings.py        /settings route
  components/
    camera_card.py            NiceGUI ui.card subclass for one camera
    live_player.py            go2rtc WebRTC/HLS player (ported from the ioBroker engine)
    live_snapshot_player.py   snapshot-refresh near-live view (no-go2rtc fallback)
    hls_player.py             legacy hls.js placeholder, superseded by live_player.py
```

See README.md § File Structure for the full annotated tree.

## sys.path Injection Pattern

RATIONALE: The Python CLI repo (`bosch_camera.py`) is the single source of truth for all Bosch API logic. Rather than duplicating or vendoring it, we inject its directory into `sys.path` at import time.

```python
# __init__.py
sys.path.insert(0, BOSCH_CAMERA_CLI_PATH)
# then in any module:
from bosch_camera import load_config, make_session, ...
```

Trade-offs:
- PRO: Zero duplication; CLI fixes apply to frontend immediately
- PRO: No packaging step; dev changes picked up on next Python import
- CON: Import order matters — `__init__` must run before any CLI import
- CON: No type stubs for IDE (bosch_camera.py has no py.typed marker)
- CON: Tight coupling to CLI repo directory structure
- MITIGATION: `cli_bridge.py` is the single import boundary; all other modules import from cli_bridge, not directly from bosch_camera

TODO_PHASE_2: Generate type stubs via `mypy --generate-stubs` or extract bosch_camera into an installable package (`pip install -e ../Bosch-Smart-Home-Camera-Tool-Python`).

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

The CLI module caches a single `requests.Session` globally. The frontend reuses this session across page renders. Safe for single-user local use. For multi-user (Phase 3), each user needs their own token and session.

## Async Story

**Current:** every `cli_bridge` call site used from an `async def` page handler goes through an `async_*` twin (`async_get_cameras`, `async_api_ping`, `async_snap_from_proxy`, `async_get_stream_url`, …) that wraps the underlying sync `requests` call in `asyncio.to_thread()`, so the event loop — and the UI — never blocks on network I/O.

**Phase 3 plan:** FCM push listener runs as a background asyncio task; pushes events to connected browsers via NiceGUI's `ui.notify()` or custom WebSocket channel.

## Threat Model

- SCOPE: Local-only tool. `--host 127.0.0.1` default binds loopback only.
- AUTH: None yet — anyone who can reach the port can control cameras. HTTP Basic Auth middleware is still on the Phase 3 roadmap (README § Roadmap).
- TOKEN: Bearer token stored in `bosch_config.json` (0o600). NiceGUI client storage holds the token in server-side dict (not sent to browser).
- STORAGE_SECRET: resolved at startup via `BOSCH_FRONTEND_STORAGE_SECRET` env var if set, otherwise a fresh `secrets.token_urlsafe(32)` per process (`app.py::_resolve_storage_secret`). No secret is hardcoded in the source.

**Phase 3 mitigations still open:**
- Replace `--host 127.0.0.1` option with explicit network binding guard
- Add HTTP Basic Auth middleware (single admin password via env var)
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
- Siren trigger (Gen2 Indoor II only)
- RCP reads (camera info, clock)
- Multi-camera grid layout

### Phase 5 — Polish
- Dark mode (NiceGUI `dark` mode)
- PWA manifest
- Mobile responsive breakpoints audit
- Settings: polling interval, download path
