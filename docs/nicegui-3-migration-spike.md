# NiceGUI 3 Migration Spike

> STATUS: EXECUTED 2026-06-03 (commit `9f48046`). Upgraded to nicegui 3.12.1, pin
> `>=3.12.0,<4`, `sanitize=False` on 4 raw-HTML sites. Verified against real
> 3.12.1 (server boots; /, /settings, /camera/{name} → HTTP 200). Residual: a
> manual Tailwind-4 visual check in a browser.

## Summary

GO with conditions. Upgrade from `nicegui>=2.0,<3.0` (currently 2.24.2) to `nicegui>=3.12.0` is recommended. The minimum safe version is **3.12.0** (current stable: 3.12.1, released 2026-05-21 [1]). There are **17 CVEs** across nicegui ≤2.24.2 through ≤3.11.x — many affect versions we are currently pinned at. Our codebase is a Phase 1 skeleton: all pages use `@ui.page`, no auto-index code, no `ui.markdown`, no `ui.sub_pages`, no `app.add_media_files`. The XSS and path-traversal CVEs have near-zero direct impact (app binds to 127.0.0.1 by default, no user-supplied content rendered as HTML). However two CVEs (`CVE-2025-53354`, `CVE-2024-32005`) technically affect the currently installed version. The migration effort is **low** — roughly 4 mechanical changes across 3 files, no architectural rewrites needed. Python version: pyproject.toml already requires `>=3.10`, matching nicegui 3.x (requires Python ≥3.10 [1]).

## CVE Inventory

| CVE | GHSA | Severity | Affects (nicegui range) | Fixed in | Description | Our exposure |
|---|---|---|---|---|---|---|
| CVE-2024-32005 | GHSA-mwc7-64wg-pgvj | 8.2 HIGH | >=1.4.6, <1.4.21 | 1.4.21 | LFI via leaflet /_nicegui/.../resources/ route | Not exposed (no leaflet) |
| CVE-2025-21618 | — | 7.5 HIGH | <2.9.1 | 2.9.1 | On Air: login one browser logs in all | Not relevant (no On Air) |
| CVE-2025-53354 | GHSA-8c95-hpq2-w46f | 6.1 MED | ≤2.24.2 | 3.0.0 | Reflected XSS via ui.html()/ui.chat_message() — unsanitized user input | LOW — ui.html only in static strings; no user input rendered [2] |
| CVE-2025-66469 | GHSA-72qc-wxch-74mg | 6.1 MED | ≤3.3.1 | 3.4.0 | Reflected XSS in ui.add_css/add_scss/add_sass via style injection | NONE — we don't call add_css/add_scss/add_sass |
| CVE-2025-66470 | GHSA-2m4f-cg75-76w2 | 6.1 MED | ≤3.3.1 | 3.4.0 | Stored/reflected XSS in ui.interactive_image via SVG v-html | NONE — we don't use ui.interactive_image |
| CVE-2025-66645 | GHSA-hxp3-63hc-5366 | 7.5 HIGH | <3.4.0 | 3.4.0 | Path traversal in app.add_media_files() allows arbitrary file read | NONE — we never call add_media_files |
| CVE-2026-21871 | — | 6.1 MED | 2.13.0–3.4.1 | 3.5.0 | XSS via unescaped URL in ui.navigate.history.push()/replace() | NONE — we don't use navigate.history.push/replace |
| CVE-2026-21872 | GHSA-m7j5-rq9j-6jj9 | 6.1 MED | 2.22.0–3.4.1 | 3.5.0 | XSS via ui.sub_pages + user-controlled links | NONE — we don't use ui.sub_pages |
| CVE-2026-21873 | GHSA-mhpg-c27v-6mxr | 7.2 HIGH | 2.22.0–3.4.1 | 3.5.0 | Zero-click XSS via ui.sub_pages iframe fragment manipulation | NONE — we don't use ui.sub_pages |
| CVE-2026-21874 | GHSA-mp55-g7pj-rvm2 | 5.3 MED | 2.10.0–3.4.1 | 3.5.0 | Redis connection leak via tab storage (service degradation) | NONE — we use file-based storage, not Redis |
| CVE-2026-25516 | GHSA-v82v-c5x8-w282 | 6.1 MED | ≤3.6.1 | 3.7.0 | XSS via ui.markdown() — markdown2 renders raw HTML | NONE — we don't use ui.markdown |
| CVE-2026-25732 | GHSA-9ffm-fxg3-xrhh | 7.5 HIGH | ≤3.6.1 | 3.7.0 | Path traversal via unsanitized FileUpload.name — arbitrary file write | NONE — we don't handle file uploads |
| CVE-2026-27156 | GHSA-78qv-3mpx-9cqq | 6.1 MED | <3.8.0 | 3.8.0 | XSS via eval() fallback in runMethod() — code injection via method name | NONE — we don't call element.run_method() with user input |
| CVE-2026-33332 | GHSA-w5g8-5849-vj76 | 5.3 MED | <3.9.0 | 3.9.0 | Memory exhaustion via unvalidated chunk size in media routes | NONE — we don't use add_media_files |
| CVE-2026-39844 | GHSA-w8wv-vfpc-hw2w | 7.5 HIGH | <3.10.0 | 3.10.0 | Windows path traversal bypass (backslash) in FileUpload.name | NONE — we don't handle uploads |
| CVE-2026-45553 | — | 7.5 HIGH | <3.12.0 | 3.12.0 | LFI via Docutils file insertion in ui.restructured_text() | NONE — we don't use ui.restructured_text |
| CVE-2026-45554 | — | 5.3 MED | <3.12.0 | 3.12.0 | Log-flood DoS via trailing slash on ESM/per-component static routes | LOW — app binds 127.0.0.1 by default; remote attackers blocked |

Total CVEs verified: 17. All requiring nicegui <3.0 (i.e. our current pin): 1 active (CVE-2025-53354). All requiring ≥3.12.0 to fully clear: CVE-2026-45553 and CVE-2026-45554. **Minimum safe version: 3.12.0** [2][3].

## API Usage Audit (Our Code)

### app.py
- `from nicegui import app as nicegui_app, ui` — both still present in 3.x [4]
- `@nicegui_app.on_startup` — still present, same signature
- `nicegui_app.storage.general["cfg"]` / `["token"]` / `["config_path"]` — still present [4]
- `nicegui_app.storage.general["__reload_fn_name__"]` — dict assignment, still valid
- `ui.run(host, port, title, favicon, reload, show, storage_secret)` — see breaking-changes table

### pages/dashboard.py
- `@ui.page("/")` — unchanged
- `app.storage.general.get(...)` — unchanged
- `ui.page_title(...)` — unchanged
- `ui.add_head_html(...)` — unchanged
- `ui.header(elevated=False)` — unchanged
- `ui.footer(elevated=False)` — unchanged
- `ui.row()`, `ui.column()`, `ui.card()`, `ui.grid(columns=N)`, `ui.icon()`, `ui.label()`, `ui.button()` — all unchanged
- `ui.navigate.to(...)` — unchanged (replaced `ui.open()` which was removed in 2.x already)
- `.classes(...)`, `.style(...)`, `.props(...)`, `.tooltip(...)` — unchanged

### pages/camera_detail.py
- `@ui.page("/camera/{name}")` — unchanged (path parameters still work)
- `app.storage.general.get(...)` — unchanged
- `ui.timer(0.1, fn, once=True)` — unchanged (see notes)
- `ui.image(src)`, `.set_source(...)` — unchanged
- `ui.expansion("...", icon="...")` — unchanged
- `ui.switch("...", on_change=...)` — unchanged; event arg `e.value` still valid
- `ui.slider(min, max, step, value, on_change)` — unchanged
- `ui.table(columns=[...], rows=[...])` — see breaking-changes table (rows/columns mutation pattern changed)
- `ui.notify(...)` — unchanged
- `.enable()`, `.disable()` — unchanged
- `.set_value(...)`, `.set_text(...)` — unchanged

### pages/settings.py
- `@ui.page("/settings")` — unchanged
- `ui.select(options=_LANG_LABELS, value=..., label=..., on_change=...)` — see breaking-changes table
- `ui.html('<a ...>')` — requires `sanitize` arg in 3.x; BREAKING for static content
- `ui.navigate.to(...)` — unchanged

### components/camera_card.py
- `class CameraCard(ui.card)` — `ui.card` subclassing; see breaking-changes table
- `super().__init__()` — unchanged signature `(tag=None, *, _client=None)` [4]
- `with self:` context manager — unchanged
- `ui.html('<div ...>')` — requires `sanitize` arg in 3.x; BREAKING
- `ui.separator()`, `ui.switch(on_change=...)`, `ui.button(icon=..., on_click=...)` — unchanged
- `ui.timer(interval, fn)` and `ui.timer(interval, fn, once=True)` — unchanged
- `.classes(replace="...")` — unchanged
- `.set_content(...)` on `ui.html` — may be affected by sanitize requirement
- `.on("click", ...)` event binding — unchanged

### components/hls_player.py
- `class HlsPlayer(ui.element)` with `super().__init__("div")` — unchanged (tag param still accepted)
- `with self:` context manager — unchanged
- `ui.card()`, `ui.row()`, `ui.icon()`, `ui.label()`, `ui.html(...)` — ui.html breaking, others unchanged

## Breaking Changes Mapping

| API | 2.x behavior | 3.x behavior | Our impact | File(s) |
|---|---|---|---|---|
| `ui.html(content)` | Renders raw HTML string, no sanitization | Requires `sanitize=False` or a sanitize-function arg to render arbitrary HTML without escaping [5] | BREAKING — `ui.html` used in camera_card.py (status dot), hls_player.py (links), settings.py (GitHub link), camera_detail.py (none). Static HTML only — pass `sanitize=False` [5] | camera_card.py, hls_player.py, settings.py |
| `ui.select(options=dict, ...)` | Accepts `dict` `{value: label}` — this is still valid in 3.x | Still accepts `dict {value: label}` and plain `list`. The code comment in settings.py says "list-of-{label,value} is NiceGUI 3+ and raises ValueError on 2.x" — the comment is inaccurate: both forms coexist. Dict options unchanged [6] | NO CHANGE NEEDED — dict form still works | settings.py |
| `ui.table` rows/columns mutation | Mutate original list, call `table.update()` | Modify `table.rows`/`table.columns` directly — `update()` no longer needed [5] | LOW — we use `events_container.clear()` + rebuild pattern; no mutation after creation. No change needed | camera_detail.py |
| `ui.run(storage_secret=...)` | Accepted as keyword arg | Still accepted, same behavior — `storage_secret` feeds `SessionMiddleware` [4] | NO CHANGE | app.py |
| `ui.run(show=...)`, `ui.run(reload=...)`, `ui.run(favicon=...)` | Accepted | Still accepted [4] | NO CHANGE | app.py |
| `app.storage.general` | Persisted server-side dict, shared all users | Identical semantics [4] | NO CHANGE | app.py, all pages |
| `app.storage.client` | Volatile per-connection dict | Identical semantics [4] | NO CHANGE (we don't use it) | — |
| `@ui.page("/path")` async handler | Standard | Identical [5] | NO CHANGE | all pages |
| `ui.timer(interval, fn, once=True)` | One-shot timer after interval | Identical [5] | NO CHANGE | camera_card.py, camera_detail.py |
| `class X(ui.card)` subclassing | `super().__init__()` → tag="q-card", context ok | Identical — `Element.__init__(tag=None, *, _client=None)`, tag validated at construction, `with self:` works [4] | NO CHANGE | camera_card.py |
| `class X(ui.element)` subclassing | `super().__init__("div")` | Identical [4] | NO CHANGE | hls_player.py |
| `ui.element.tailwind` API | Available | REMOVED — use `.classes()` instead [5] | NONE — we never use `.tailwind()` | — |
| Auto-index page (globals at module level) | Shared singleton at "/" | REMOVED — must use `@ui.page("/")` or `root=` param [5] | NO CHANGE — we already use `@ui.page` everywhere | — |
| `nicegui.testing.conftest` import | Importable | REMOVED — use `pytest_plugins = ["nicegui.testing.plugin"]` [5] | CHECK tests/ directory | tests/ |
| `ValueChangeEventArguments` | `.value` attribute | Gains `.previous_value` (additive, not breaking) [5] | NO CHANGE | — |
| Python minimum | 3.8 | 3.10 [1] | NO CHANGE — pyproject.toml already `requires-python = ">=3.10"` | pyproject.toml |
| Tailwind 4 class names | Tailwind 3 classes | Tailwind 4 — some class names/spacing differ, especially line-height and borders [5] | LOW risk — visual layout may shift slightly in the card/grid layout | all pages |

## Migration Steps

### File-by-file changes

**pyproject.toml** — 1 change
- Change `"nicegui>=2.0,<3.0"` → `"nicegui>=3.12.0"`
- Same in requirements.txt (same line)

**src/bosch_camera_frontend/components/camera_card.py** — 1 change
- Line 88–91: `ui.html('<div style="...">')` and `.set_content(...)` calls
- Add `sanitize=False` to each `ui.html(...)` call: `ui.html('<div ...>', sanitize=False)`
- Affects: initial `_status_dot` assignment (line 88) and `_set_dot()` method (line 179)

**src/bosch_camera_frontend/components/hls_player.py** — 1 change
- Line 61–64: `ui.html('<a href="..." ...>')` anchor link
- Line 79–96: `ui.html(f"""...<video>...<script>...""")` player block
- Add `sanitize=False` to each: `ui.html("...", sanitize=False)`

**src/bosch_camera_frontend/pages/settings.py** — 1 change
- Line 169–172: `ui.html('<a href="https://github.com/..." ...>')` GitHub link
- Change to: `ui.html('<a href="..." ...>', sanitize=False)`
- Comment on line 130–131 is inaccurate ("list-of-{label,value} is NiceGUI 3+") — update or remove the comment; dict form works unchanged

**tests/** — verify
- Check if any test file imports `nicegui.testing.conftest`
- If yes, change to `pytest_plugins = ["nicegui.testing.plugin"]`

### Visual regression check
After upgrade: verify card layout, grid spacing, header/footer backdrop, separator. Tailwind 4 may shift line-height and border widths.

## Risks and Open Questions

RISK_1: `sanitize` parameter on `ui.html` — if NiceGUI 3.x imports `html-sanitizer` (optional dep) at startup and it is not installed, it may warn or error. Verify `html-sanitizer` is not an unfulfilled transitive dep. Adding it to `dependencies[]` in pyproject.toml may be needed only if `sanitize` is left at default (True). With `sanitize=False` it is not needed.

RISK_2: Tailwind 4 visual drift. All layout uses `.classes("...")` strings — some spacing/border tokens changed between Tailwind 3 and 4. No logic breakage, but a manual visual pass is required after upgrade.

RISK_3: `ui.html` `.set_content(...)` method — verify that in 3.x `set_content()` on a `ui.html` element still exists and still works (used in `_set_dot()` in camera_card.py). No evidence of removal found, but confirm.

RISK_4: Test fixtures using nicegui.testing — check tests/ for `from nicegui.testing.conftest import ...` or `import nicegui.testing.conftest`. Rename to plugin form if present.

OPEN_1: Exact `sanitize` parameter name — confirmed from release notes as `sanitize` but verify the exact call signature (`ui.html(content, sanitize=False)` vs positional) against 3.12.x source before patching.

OPEN_2: `settings.py` comment on line 130–131 claims "list-of-{label,value} is NiceGUI 3+ form and raises ValueError on 2.x" — this appears inaccurate based on research (both list and dict were supported in 2.x). Remove the misleading comment to avoid future confusion.

OPEN_3: The `CameraCard._last_snap_ts = 0.0` debounce sentinel — not a nicegui issue but flagged in project CLAUDE.md (SENTINEL_RULE: use `float('-inf')` not `0.0`). Worth fixing in the same PR.

## Sources

[1] https://pypi.org/project/nicegui/ — latest version 3.12.1, Python >=3.10, released 2026-05-21
[2] https://nvd.nist.gov/vuln/detail/CVE-2025-53354 — affected ≤2.24.2, fixed 3.0.0
[3] https://github.com/advisories/GHSA-mwc7-64wg-pgvj — CVE-2024-32005 LFI, fixed 1.4.21
[4] https://github.com/zauberzeug/nicegui/blob/main/nicegui/storage.py — storage API source
[5] https://github.com/zauberzeug/nicegui/releases/tag/v3.0.0 — v3.0.0 breaking changes
[6] https://nicegui.io/documentation/select — ui.select options formats
[7] https://github.com/advisories/GHSA-9ffm-fxg3-xrhh — CVE-2026-25732 FileUpload path traversal, fixed 3.7.0
[8] https://github.com/advisories/GHSA-hxp3-63hc-5366 — CVE-2025-66645 add_media_files, fixed 3.4.0
[9] https://github.com/zauberzeug/nicegui/security/advisories/GHSA-mp55-g7pj-rvm2 — CVE-2026-21874 Redis leak, fixed 3.5.0
[10] https://github.com/zauberzeug/nicegui/security/advisories/GHSA-mhpg-c27v-6mxr — CVE-2026-21873 zero-click XSS sub_pages, fixed 3.5.0
[11] https://github.com/zauberzeug/nicegui/security/advisories/GHSA-m7j5-rq9j-6jj9 — CVE-2026-21872 XSS sub_pages links, fixed 3.5.0
[12] https://github.com/zauberzeug/nicegui/security/advisories/GHSA-v82v-c5x8-w282 — CVE-2026-25516 ui.markdown XSS, fixed 3.7.0
[13] https://dbugs.ptsecurity.com/vulnerability/PT-2026-21771 — CVE-2026-27156 runMethod eval XSS, fixed 3.8.0
[14] https://advisories.gitlab.com/pkg/pypi/nicegui/CVE-2026-33332/ — CVE-2026-33332 memory exhaustion, fixed 3.9.0
[15] https://www.tenable.com/cve/CVE-2026-39844 — CVE-2026-39844 Windows upload traversal, fixed 3.10.0
[16] https://github.com/zauberzeug/nicegui/discussions/5331 — v3 Changes Everything migration discussion
[17] https://advisories.gitlab.com/pkg/pypi/nicegui/ — GitLab advisory database for nicegui (full list)
[18] https://nvd.nist.gov/vuln/detail/CVE-2026-21871 — CVE-2026-21871 navigate.history XSS, fixed 3.5.0
[19] https://github.com/releases/zauberzeug/nicegui — release history confirming 3.12.1 as latest stable
