# Bosch Smart Camera — Python Frontend (NiceGUI)

> Desktop & mobile web UI for Bosch Smart Home cameras, built with NiceGUI.
> Replaces the official iOS/Android app with a browser-based interface.

> **This is a concept / proof-of-concept.** The architecture, feature roadmap, and technical approach are documented below. No code has been written yet — this README serves as the design document.
>
> **Interested? Let me know!** Open an [issue](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python-frontend/issues) or start a [discussion](https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python-frontend/discussions) if you'd like to see this built. Feature requests, ideas, and pull requests are welcome. If there is enough community interest, I will prioritize development.

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
| UI framework | [NiceGUI](https://nicegui.io/) 2.x | Python web UI with Tailwind CSS |
| Video player | [hls.js](https://github.com/video-dev/hls.js/) | HLS playback in browser |
| Transcoder | FFmpeg | RTSPS → HLS segment conversion |
| API client | `requests` (from existing CLI) | Bosch Cloud API communication |
| Push notifications | `firebase-messaging` | FCM push reception |
| Auth | OAuth2 PKCE (from existing `get_token.py`) | Bosch SingleKey ID login |

### Requirements

```bash
pip install nicegui requests
brew install ffmpeg
```

Python 3.10+

---

## File Structure (planned)

```
python-frontend/
  main.py                  — NiceGUI app entry point
  api/
    bosch_api.py           — async wrapper around bosch_camera.py functions
    token_manager.py       — OAuth2 token auto-renewal
    fcm_listener.py        — FCM push notification receiver
  pages/
    dashboard.py           — main camera dashboard
    events.py              — event list & detail view
    settings.py            — configuration page
    live.py                — live video player page
  components/
    camera_card.py         — camera status card widget
    event_row.py           — event list row widget
    video_player.py        — HLS video player component
    pan_control.py         — pan slider widget
  static/
    hls.min.js             — hls.js library
  README.md                — this file
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

## Legal Notes

- This is a personal side project for interoperability with user-owned hardware
- Covered by § 69e German Copyright Act (UrhG) and EU Directive 2009/24/EC
- No Bosch code is copied — only API protocol communication is reimplemented
- No Bosch trademarks in the project name (use neutral naming)
- Firebase API keys are public app identifiers (embedded in every Bosch app install)
- OAuth client secret is a public app-level key (not a personal credential)
- See [legal analysis](../research/) for full details

---

## Related

- [Bosch Smart Home Camera Tool — Python CLI](../Bosch-Smart-Home-Camera-Tool-Python/) — the existing CLI tool (API logic lives here)
- [Bosch Smart Home Camera Tool — Home Assistant](../Bosch-Smart-Home-Camera-Tool-HomeAssistant/) — HA custom integration
- [NiceGUI Documentation](https://nicegui.io/documentation)
- [hls.js Documentation](https://github.com/video-dev/hls.js/)
