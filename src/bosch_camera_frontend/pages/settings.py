"""Settings page — /settings

Shows config path, token status, language selector.
Language change persists to cfg["language"] via save_config().

TODO Phase 3: add login button that launches OAuth2 PKCE flow.
TODO Phase 3: add download path selector.
TODO Phase 3: add polling interval slider.
TODO Phase 4: dark mode toggle.
"""

from __future__ import annotations

from nicegui import app, ui

from bosch_camera_frontend.adapters import cli_bridge


@ui.page("/settings")
async def settings_page() -> None:
    """Settings and token status page."""
    cfg = app.storage.client.get("cfg")
    config_path = app.storage.client.get("config_path", "bosch_config.json")

    ui.page_title("Settings — Bosch Camera Frontend")

    with ui.header().classes("items-center px-4 gap-2"):
        ui.button(
            icon="arrow_back",
            on_click=lambda: ui.navigate.to("/"),
        ).props("flat color=white dense")
        # TODO: use t("nav.settings") once CLI key confirmed
        ui.label("Settings").classes("text-white font-bold text-lg")

    with ui.column().classes("w-full p-4 gap-4 max-w-2xl mx-auto"):

        # ── Config section ────────────────────────────────────────────────
        with ui.card().classes("w-full p-4"):
            ui.label("Configuration").classes("font-semibold text-base mb-2")

            with ui.row().classes("items-center gap-2"):
                ui.icon("folder", color="grey")
                ui.label("Config file:").classes("text-sm text-gray-500")
                ui.label(config_path).classes("text-sm font-mono")

            if cfg:
                cameras = cfg.get("cameras", {})
                with ui.row().classes("items-center gap-2 mt-1"):
                    ui.icon("videocam", color="grey")
                    ui.label("Cameras in config:").classes("text-sm text-gray-500")
                    ui.label(str(len(cameras))).classes("text-sm font-semibold")
            else:
                ui.label("No config loaded.").classes("text-sm text-red-500")

        # ── Token section ─────────────────────────────────────────────────
        with ui.card().classes("w-full p-4"):
            ui.label("Token Status").classes("font-semibold text-base mb-2")

            if cfg:
                token_status = cli_bridge.check_token_age(cfg)
                # Determine color from status text
                if "✅" in token_status:
                    color = "positive"
                    icon = "check_circle"
                elif "⚠️" in token_status:
                    color = "warning"
                    icon = "warning"
                else:
                    color = "negative"
                    icon = "error"

                with ui.row().classes("items-center gap-2"):
                    ui.icon(icon, color=color)
                    ui.label(token_status).classes("text-sm")

                ui.label(
                    "To refresh token: run python3 bosch_camera.py token fix"
                ).classes("text-xs text-gray-400 mt-2")
            else:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("help_outline", color="grey")
                    ui.label("Token status unavailable — no config loaded.").classes(
                        "text-sm text-gray-500"
                    )

            # TODO Phase 3: add "Login" button that opens OAuth2 PKCE flow
            # ui.button("Login / Refresh Token", icon="login", ...).props("outline")

        # ── Language section ───────────────────────────────────────────────
        with ui.card().classes("w-full p-4"):
            # TODO: use t("settings.language") once key confirmed
            ui.label("Language").classes("font-semibold text-base mb-2")

            _LANG_LABELS = {
                "en": "English",
                "de": "Deutsch",
                "fr": "Français",
                "es": "Español",
                "it": "Italiano",
                "nl": "Nederlands",
                "pl": "Polski",
                "pt": "Português",
                "ru": "Русский",
                "uk": "Українська",
                "zh-Hans": "中文 (简体)",
            }

            current_lang = (
                cli_bridge.detect_lang(cfg) if cfg else "en"
            )

            lang_options = [
                {"label": label, "value": code}
                for code, label in _LANG_LABELS.items()
            ]

            lang_select = ui.select(
                options=lang_options,
                value=current_lang,
                label="UI Language",
                on_change=lambda e: _save_language(e.value),
            ).classes("w-48")

            lang_saved_note = ui.label("").classes("text-xs text-green-600 mt-1")

            def _save_language(lang: str) -> None:
                if cfg:
                    cfg["language"] = lang
                    try:
                        cli_bridge.save_config(cfg)
                        cli_bridge.set_lang(lang)
                        lang_saved_note.set_text(f"Saved — restart app to apply fully")
                        ui.notify(f"Language set to {_LANG_LABELS.get(lang, lang)}", color="info")
                    except Exception as exc:
                        lang_saved_note.set_text(f"Save failed: {exc}")
                        ui.notify(f"Could not save config: {exc}", color="negative")
                else:
                    ui.notify("No config loaded — cannot save language", color="warning")

        # ── About section ─────────────────────────────────────────────────
        with ui.card().classes("w-full p-4"):
            ui.label("About").classes("font-semibold text-base mb-2")
            with ui.row().classes("items-center gap-2"):
                ui.icon("info_outline", color="grey")
                ui.label("Bosch Smart Camera Frontend v0.1.0-alpha").classes("text-sm")
            ui.label(
                "Phase 1 skeleton — dashboard, detail, settings. "
                "Phase 2: live stream + async. Phase 3: events + auth."
            ).classes("text-xs text-gray-400 mt-1")
            ui.html(
                '<a href="https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python-frontend" '
                'target="_blank" class="text-blue-600 underline text-xs">GitHub Repository</a>'
            )
