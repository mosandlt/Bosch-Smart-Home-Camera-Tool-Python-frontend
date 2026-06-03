"""Smoke tests for Phase 1 skeleton.

These tests verify:
- Package imports cleanly (no side effects)
- Page modules can be imported with NiceGUI mocked
- cli_bridge finds bosch_camera module when BOSCH_CAMERA_CLI_PATH is set
- cli_bridge raises clearly when CLI path is missing

NiceGUI is mocked throughout — no real browser sessions are started.
"""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock, patch
import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

CLI_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",  # frontend repo root
        "..",  # bosch kamera/
        "Bosch-Smart-Home-Camera-Tool-Python",
    )
)


def _mock_nicegui():
    """Insert a minimal NiceGUI mock into sys.modules so page imports don't fail."""
    # Build a mock module tree for nicegui
    ng = types.ModuleType("nicegui")
    ng.ui = MagicMock()
    ng.app = MagicMock()
    ng.app.storage = MagicMock()
    ng.app.storage.client = {}
    ng.app.on_startup = MagicMock(return_value=lambda f: f)  # passthrough decorator
    # ui.page, ui.middleware must work as decorators
    ng.ui.page = MagicMock(return_value=lambda f: f)
    ng.ui.middleware = MagicMock(return_value=lambda f: f)
    ng.ui.run = MagicMock()
    ng.ui.navigate = MagicMock()
    ng.ui.notify = MagicMock()
    ng.ui.timer = MagicMock()
    ng.ui.label = MagicMock(return_value=MagicMock())
    ng.ui.image = MagicMock(return_value=MagicMock())
    ng.ui.card = MagicMock(
        return_value=MagicMock(__enter__=lambda s, *a: s, __exit__=MagicMock())
    )
    ng.ui.row = MagicMock(
        return_value=MagicMock(__enter__=lambda s, *a: s, __exit__=MagicMock())
    )
    ng.ui.column = MagicMock(
        return_value=MagicMock(__enter__=lambda s, *a: s, __exit__=MagicMock())
    )
    ng.ui.grid = MagicMock(
        return_value=MagicMock(__enter__=lambda s, *a: s, __exit__=MagicMock())
    )
    ng.ui.expansion = MagicMock(
        return_value=MagicMock(__enter__=lambda s, *a: s, __exit__=MagicMock())
    )
    ng.ui.button = MagicMock(return_value=MagicMock())
    ng.ui.switch = MagicMock(return_value=MagicMock())
    ng.ui.select = MagicMock(return_value=MagicMock())
    ng.ui.badge = MagicMock(return_value=MagicMock())
    ng.ui.icon = MagicMock(return_value=MagicMock())
    ng.ui.header = MagicMock(
        return_value=MagicMock(__enter__=lambda s, *a: s, __exit__=MagicMock())
    )
    ng.ui.footer = MagicMock(
        return_value=MagicMock(__enter__=lambda s, *a: s, __exit__=MagicMock())
    )
    ng.ui.html = MagicMock(return_value=MagicMock())
    ng.ui.table = MagicMock(
        return_value=MagicMock(__enter__=lambda s, *a: s, __exit__=MagicMock())
    )
    ng.ui.slider = MagicMock(return_value=MagicMock())
    ng.ui.tooltip = MagicMock(return_value=MagicMock())
    ng.ui.element = type(
        "element",
        (),
        {
            "__init__": lambda self, *a, **kw: None,
            "clear": MagicMock(),
            "__enter__": lambda s, *a: s,
            "__exit__": MagicMock(),
        },
    )

    # NiceGUI context manager helpers
    class _FakeCard:
        def __init__(self, *a, **kw):
            pass

        def classes(self, *a, **kw):
            return self

        def style(self, *a, **kw):
            return self

        def props(self, *a, **kw):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    ng.ui.card = _FakeCard

    sys.modules["nicegui"] = ng
    sys.modules["nicegui.ui"] = ng.ui
    return ng


@pytest.fixture(autouse=True)
def mock_nicegui_module():
    """Ensure NiceGUI is mocked for all tests in this file."""
    if "nicegui" not in sys.modules:
        _mock_nicegui()
    yield
    # Clean up page/adapter modules so they re-import cleanly in next test
    for mod_name in list(sys.modules.keys()):
        if "bosch_camera_frontend" in mod_name:
            del sys.modules[mod_name]


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestAppImportsCleanly:
    """test_app_imports_cleanly: package import must have no side effects."""

    def test_package_importable(self):
        """bosch_camera_frontend package imports without error."""
        import bosch_camera_frontend  # noqa: F401

        assert hasattr(bosch_camera_frontend, "__version__")

    def test_version_is_alpha(self):
        import bosch_camera_frontend

        # Must match the released pyproject version and stay an alpha ("a").
        assert bosch_camera_frontend.__version__ == "0.1.1a0"
        assert "a" in bosch_camera_frontend.__version__

    def test_no_sys_exit_on_import(self):
        """Importing the package must not call sys.exit even if CLI path is missing."""
        with patch.dict(os.environ, {"BOSCH_CAMERA_CLI_PATH": "/nonexistent/path"}):
            # Should not raise SystemExit
            try:
                import bosch_camera_frontend  # noqa: F401
            except SystemExit:
                pytest.fail("Package import triggered sys.exit")


class TestCliBridgeFindsModule:
    """test_cli_bridge_finds_bosch_camera_module: adapter must locate CLI with env set."""

    def test_finds_module_with_env_var(self):
        """cli_bridge._ensure_cli_available succeeds when BOSCH_CAMERA_CLI_PATH is valid."""
        with patch.dict(os.environ, {"BOSCH_CAMERA_CLI_PATH": CLI_PATH}):
            from bosch_camera_frontend import _inject_cli_path

            # Should not raise
            _inject_cli_path(CLI_PATH)
            assert CLI_PATH in sys.path

    def test_bosch_camera_importable_after_inject(self):
        """bosch_camera module is importable after path injection."""
        if CLI_PATH not in sys.path:
            sys.path.insert(0, CLI_PATH)
        import bosch_camera  # type: ignore[import]

        assert hasattr(bosch_camera, "load_config")

    def test_bosch_i18n_importable_after_inject(self):
        """bosch_i18n module is importable after path injection."""
        if CLI_PATH not in sys.path:
            sys.path.insert(0, CLI_PATH)
        import bosch_i18n  # type: ignore[import]

        assert hasattr(bosch_i18n, "t")
        assert hasattr(bosch_i18n, "set_lang")
        assert hasattr(bosch_i18n, "detect_lang")


class TestCliBridgeRaisesIfMissing:
    """test_cli_bridge_raises_if_cli_path_missing: adapter must raise clearly."""

    def test_raises_file_not_found_for_bad_path(self):
        """_inject_cli_path raises FileNotFoundError for non-existent path."""
        # Remove any previously injected valid path from sys.path
        bad_path = "/nonexistent/path/cli"
        if bad_path in sys.path:
            sys.path.remove(bad_path)

        from bosch_camera_frontend import _inject_cli_path

        with pytest.raises(FileNotFoundError, match="Bosch CLI path not found"):
            _inject_cli_path(bad_path)

    def test_raises_import_error_for_path_without_bosch_camera(self, tmp_path):
        """_inject_cli_path raises ImportError when dir exists but bosch_camera.py absent."""
        empty_dir = str(tmp_path / "empty_cli")
        os.makedirs(empty_dir, exist_ok=True)

        from bosch_camera_frontend import _inject_cli_path

        with pytest.raises(ImportError, match="bosch_camera.py not found"):
            _inject_cli_path(empty_dir)


class TestDashboardPageConstructs:
    """test_dashboard_page_constructs: dashboard module imports and page registers."""

    def test_dashboard_module_importable(self):
        """dashboard.py imports without raising (NiceGUI mocked)."""
        _mock_nicegui()
        # Ensure CLI path is injected first
        if CLI_PATH not in sys.path:
            sys.path.insert(0, CLI_PATH)
        try:
            from bosch_camera_frontend.pages import dashboard  # noqa: F401
        except Exception as exc:
            pytest.fail(f"dashboard import raised: {exc}")

    def test_dashboard_has_page_function(self):
        """dashboard module exposes dashboard_page function."""
        _mock_nicegui()
        if CLI_PATH not in sys.path:
            sys.path.insert(0, CLI_PATH)
        from bosch_camera_frontend.pages import dashboard

        assert callable(dashboard.dashboard_page)


class TestCameraDetailPageConstructs:
    """test_camera_detail_page_constructs: camera_detail module imports cleanly."""

    def test_camera_detail_importable(self):
        """camera_detail.py imports without raising (NiceGUI mocked)."""
        _mock_nicegui()
        if CLI_PATH not in sys.path:
            sys.path.insert(0, CLI_PATH)
        try:
            from bosch_camera_frontend.pages import camera_detail  # noqa: F401
        except Exception as exc:
            pytest.fail(f"camera_detail import raised: {exc}")

    def test_camera_detail_has_page_function(self):
        """camera_detail module exposes camera_detail_page function."""
        _mock_nicegui()
        if CLI_PATH not in sys.path:
            sys.path.insert(0, CLI_PATH)
        from bosch_camera_frontend.pages import camera_detail

        assert callable(camera_detail.camera_detail_page)


class TestSettingsPageConstructs:
    """test_settings_page_constructs: settings module imports cleanly."""

    def test_settings_importable(self):
        """settings.py imports without raising (NiceGUI mocked)."""
        _mock_nicegui()
        if CLI_PATH not in sys.path:
            sys.path.insert(0, CLI_PATH)
        try:
            from bosch_camera_frontend.pages import settings  # noqa: F401
        except Exception as exc:
            pytest.fail(f"settings import raised: {exc}")

    def test_settings_has_page_function(self):
        """settings module exposes settings_page function."""
        _mock_nicegui()
        if CLI_PATH not in sys.path:
            sys.path.insert(0, CLI_PATH)
        from bosch_camera_frontend.pages import settings

        assert callable(settings.settings_page)


class TestCliBridgeFunctions:
    """Tests for cli_bridge public surface with CLI injected."""

    def setup_method(self):
        if CLI_PATH not in sys.path:
            sys.path.insert(0, CLI_PATH)

    def test_available_langs_constant(self):
        """cli_bridge.AVAILABLE_LANGS contains the 11 CLI languages."""
        from bosch_camera_frontend.adapters.cli_bridge import AVAILABLE_LANGS

        assert "en" in AVAILABLE_LANGS
        assert "de" in AVAILABLE_LANGS
        assert "zh-Hans" in AVAILABLE_LANGS
        assert len(AVAILABLE_LANGS) == 11

    def test_t_function_works(self):
        """cli_bridge.t() delegates to bosch_i18n.t()."""
        from bosch_camera_frontend.adapters.cli_bridge import t, set_lang

        set_lang("en")
        # A key that definitely exists in translations
        result = t("cmd.status.online", cam_name="Test")
        # Should return a string (not the key itself) if translation loaded
        assert isinstance(result, str)

    def test_detect_lang_returns_string(self):
        """cli_bridge.detect_lang returns a valid lang code."""
        from bosch_camera_frontend.adapters.cli_bridge import (
            detect_lang,
            AVAILABLE_LANGS,
        )

        cfg = {"language": "de"}
        lang = detect_lang(cfg)
        assert lang in AVAILABLE_LANGS

    def test_get_token_raises_on_empty_config(self):
        """get_token raises ValueError when no token is in config."""
        from bosch_camera_frontend.adapters.cli_bridge import get_token

        with pytest.raises(ValueError, match="No bearer token"):
            get_token({"account": {"bearer_token": ""}})

    def test_get_token_returns_token_string(self):
        """get_token returns the token string from config."""
        from bosch_camera_frontend.adapters.cli_bridge import get_token

        cfg = {"account": {"bearer_token": "abc.def.ghi"}}
        assert get_token(cfg) == "abc.def.ghi"


class TestHlsPlayerComponent:
    """Tests for the HLS player component (no browser required)."""

    def test_hls_player_importable(self):
        """HlsPlayer imports without error."""
        _mock_nicegui()
        if CLI_PATH not in sys.path:
            sys.path.insert(0, CLI_PATH)
        try:
            from bosch_camera_frontend.components.hls_player import HlsPlayer  # noqa: F401
        except Exception as exc:
            pytest.fail(f"HlsPlayer import raised: {exc}")

    def test_hls_player_cdn_url_pinned(self):
        """_HLS_JS_CDN constant contains a pinned version."""
        _mock_nicegui()
        if CLI_PATH not in sys.path:
            sys.path.insert(0, CLI_PATH)
        from bosch_camera_frontend.components.hls_player import _HLS_JS_CDN

        # Must contain a version number (not just "latest")
        assert "hls.js@" in _HLS_JS_CDN
        assert "latest" not in _HLS_JS_CDN
