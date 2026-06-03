"""Tests for bosch_camera_frontend.app — covers _parse_args, _resolve_storage_secret,
_setup_cli_path, _load_config_and_session, and main().

All data is FAKE only (cloud-ID 11111111-…, MAC aa:bb:cc:…, token header.payload.signature).
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_CFG: dict[str, Any] = {
    "account": {"bearer_token": "header.payload.signature"},
    "language": "en",
    "cameras": {
        "Test Cam": {
            "id": "11111111-2222-3333-4444-555555555555",
            "name": "Test Cam",
            "model": "CAMERA_EYES",
            "firmware": "9.0.0",
            "mac": "aa:bb:cc:dd:ee:ff",
        }
    },
}
FAKE_TOKEN = "header.payload.signature"


def _import_app() -> types.ModuleType:
    """Import app module fresh (works whether nicegui is real or faked)."""
    if "bosch_camera_frontend.app" in sys.modules:
        return sys.modules["bosch_camera_frontend.app"]
    import importlib
    return importlib.import_module("bosch_camera_frontend.app")


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------

class TestParseArgs:
    def test_defaults(self) -> None:
        app = _import_app()
        args = app._parse_args([])
        assert args.port == 8080
        assert args.host == "127.0.0.1"
        assert args.config is None
        assert args.cli_path is None
        assert args.reload is False

    def test_all_flags(self, tmp_path: Any) -> None:
        app = _import_app()
        cfg_file = str(tmp_path / "bosch_config.json")
        cli_dir = str(tmp_path / "cli")
        args = app._parse_args([
            "--config", cfg_file,
            "--port", "9090",
            "--host", "0.0.0.0",
            "--cli-path", cli_dir,
            "--reload",
        ])
        assert args.config == cfg_file
        assert args.port == 9090
        assert args.host == "0.0.0.0"
        assert args.cli_path == cli_dir
        assert args.reload is True

    def test_port_is_int(self) -> None:
        app = _import_app()
        args = app._parse_args(["--port", "3000"])
        assert isinstance(args.port, int)
        assert args.port == 3000


# ---------------------------------------------------------------------------
# _resolve_storage_secret
# ---------------------------------------------------------------------------

class TestResolveStorageSecret:
    def test_env_var_set_returns_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BOSCH_FRONTEND_STORAGE_SECRET", "mysecret123")
        app = _import_app()
        result = app._resolve_storage_secret()
        assert result == "mysecret123"

    def test_env_var_with_whitespace_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BOSCH_FRONTEND_STORAGE_SECRET", "  stripped  ")
        app = _import_app()
        result = app._resolve_storage_secret()
        assert result == "stripped"

    def test_env_var_absent_returns_random(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BOSCH_FRONTEND_STORAGE_SECRET", raising=False)
        app = _import_app()
        result = app._resolve_storage_secret()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_env_var_empty_returns_random(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BOSCH_FRONTEND_STORAGE_SECRET", "")
        app = _import_app()
        result = app._resolve_storage_secret()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_two_random_calls_differ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BOSCH_FRONTEND_STORAGE_SECRET", raising=False)
        app = _import_app()
        s1 = app._resolve_storage_secret()
        s2 = app._resolve_storage_secret()
        # Two calls generate two different secrets (probabilistically guaranteed with 32-byte entropy).
        assert s1 != s2


# ---------------------------------------------------------------------------
# _setup_cli_path
# ---------------------------------------------------------------------------

class TestSetupCliPath:
    def test_with_cli_path_sets_env_and_calls_inject(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _import_app()
        mock_inject = MagicMock()
        monkeypatch.setattr("bosch_camera_frontend._inject_cli_path", mock_inject, raising=False)
        # Also patch inside the app module's import scope
        import bosch_camera_frontend as bfe
        original_inject = bfe._inject_cli_path
        bfe._inject_cli_path = mock_inject  # type: ignore[attr-defined]
        try:
            import os
            app._setup_cli_path("/some/cli/path")
            assert os.environ.get("BOSCH_CAMERA_CLI_PATH") == "/some/cli/path"
            mock_inject.assert_called_once_with("/some/cli/path")
        finally:
            bfe._inject_cli_path = original_inject  # type: ignore[attr-defined]

    def test_without_cli_path_calls_inject_with_none(self) -> None:
        app = _import_app()
        import bosch_camera_frontend as bfe
        mock_inject = MagicMock()
        original_inject = bfe._inject_cli_path
        bfe._inject_cli_path = mock_inject  # type: ignore[attr-defined]
        try:
            app._setup_cli_path(None)
            mock_inject.assert_called_once_with(None)
        finally:
            bfe._inject_cli_path = original_inject  # type: ignore[attr-defined]

    def test_without_cli_path_does_not_overwrite_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BOSCH_CAMERA_CLI_PATH", "/existing/path")
        app = _import_app()
        import bosch_camera_frontend as bfe
        mock_inject = MagicMock()
        original_inject = bfe._inject_cli_path
        bfe._inject_cli_path = mock_inject  # type: ignore[attr-defined]
        try:
            import os
            app._setup_cli_path(None)
            # Env should remain unchanged (we only set it when cli_path is truthy).
            assert os.environ.get("BOSCH_CAMERA_CLI_PATH") == "/existing/path"
        finally:
            bfe._inject_cli_path = original_inject  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _load_config_and_session
# ---------------------------------------------------------------------------

class TestLoadConfigAndSession:
    """All cli_bridge functions are patched so no real network/file access."""

    def _patch_bridge(
        self,
        monkeypatch: pytest.MonkeyPatch,
        load_config_side_effect: Any = None,
        load_config_return: Any = None,
        get_token_side_effect: Any = None,
        get_token_return: str = FAKE_TOKEN,
        detect_lang_return: str = "en",
    ) -> None:
        """Helper to monkeypatch cli_bridge functions used inside _load_config_and_session."""
        import bosch_camera_frontend.adapters.cli_bridge as bridge

        if load_config_side_effect is not None:
            monkeypatch.setattr(bridge, "load_config", MagicMock(side_effect=load_config_side_effect))
        else:
            monkeypatch.setattr(bridge, "load_config", MagicMock(return_value=load_config_return or FAKE_CFG))

        if get_token_side_effect is not None:
            monkeypatch.setattr(bridge, "get_token", MagicMock(side_effect=get_token_side_effect))
        else:
            monkeypatch.setattr(bridge, "get_token", MagicMock(return_value=get_token_return))

        monkeypatch.setattr(bridge, "detect_lang", MagicMock(return_value=detect_lang_return))
        monkeypatch.setattr(bridge, "set_lang", MagicMock())

    def test_success_returns_cfg_and_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_bridge(monkeypatch)
        app = _import_app()
        cfg, token = app._load_config_and_session(None)
        assert cfg == FAKE_CFG
        assert token == FAKE_TOKEN

    def test_load_config_file_not_found_raises_systemexit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_bridge(monkeypatch, load_config_side_effect=FileNotFoundError("not found"))
        app = _import_app()
        with pytest.raises(SystemExit) as exc_info:
            app._load_config_and_session("/nonexistent/bosch_config.json")
        assert exc_info.value.code == 1

    def test_load_config_generic_exception_raises_systemexit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_bridge(monkeypatch, load_config_side_effect=RuntimeError("parse error"))
        app = _import_app()
        with pytest.raises(SystemExit) as exc_info:
            app._load_config_and_session(None)
        assert exc_info.value.code == 1

    def test_get_token_valueerror_returns_empty_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_bridge(
            monkeypatch,
            get_token_side_effect=ValueError("No bearer token in config"),
        )
        app = _import_app()
        cfg, token = app._load_config_and_session(None)
        assert cfg == FAKE_CFG
        assert token == ""

    def test_detect_lang_called(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as bridge
        mock_detect = MagicMock(return_value="de")
        mock_set = MagicMock()
        monkeypatch.setattr(bridge, "load_config", MagicMock(return_value=FAKE_CFG))
        monkeypatch.setattr(bridge, "get_token", MagicMock(return_value=FAKE_TOKEN))
        monkeypatch.setattr(bridge, "detect_lang", mock_detect)
        monkeypatch.setattr(bridge, "set_lang", mock_set)

        app = _import_app()
        app._load_config_and_session(None)
        mock_detect.assert_called_once_with(FAKE_CFG)
        mock_set.assert_called_once_with("de")

    def test_config_path_forwarded_to_load_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.adapters.cli_bridge as bridge
        mock_load = MagicMock(return_value=FAKE_CFG)
        monkeypatch.setattr(bridge, "load_config", mock_load)
        monkeypatch.setattr(bridge, "get_token", MagicMock(return_value=FAKE_TOKEN))
        monkeypatch.setattr(bridge, "detect_lang", MagicMock(return_value="en"))
        monkeypatch.setattr(bridge, "set_lang", MagicMock())

        app = _import_app()
        app._load_config_and_session("/custom/path/bosch_config.json")
        mock_load.assert_called_once_with("/custom/path/bosch_config.json")


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

class TestMain:
    """Tests for main() — requires fake_nicegui fixture."""

    def _patch_internals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Patch _setup_cli_path and _load_config_and_session inside app module."""
        import bosch_camera_frontend.app as app_mod
        monkeypatch.setattr(
            app_mod,
            "_setup_cli_path",
            MagicMock(),
        )
        monkeypatch.setattr(
            app_mod,
            "_load_config_and_session",
            MagicMock(return_value=(FAKE_CFG, FAKE_TOKEN)),
        )
        monkeypatch.setattr(
            app_mod,
            "_resolve_storage_secret",
            MagicMock(return_value="fake-storage-secret"),
        )

    def test_main_runs_to_completion(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() should call ui.run without raising."""
        import bosch_camera_frontend.app as app_mod
        self._patch_internals(monkeypatch)
        # Should not raise.
        app_mod.main([])

    def test_main_passes_host_and_port_to_ui_run(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ui.run is called with the parsed host/port."""
        import bosch_camera_frontend.app as app_mod
        self._patch_internals(monkeypatch)

        run_calls: list[dict[str, Any]] = []

        def capture_run(**kwargs: Any) -> None:
            run_calls.append(kwargs)

        fake_nicegui.ui.run = capture_run  # type: ignore[attr-defined]
        app_mod.main(["--host", "0.0.0.0", "--port", "9999"])
        assert len(run_calls) == 1
        assert run_calls[0]["host"] == "0.0.0.0"
        assert run_calls[0]["port"] == 9999
        assert run_calls[0]["show"] is False

    def test_main_reload_flag(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.app as app_mod
        self._patch_internals(monkeypatch)

        run_calls: list[dict[str, Any]] = []

        def capture_run(**kwargs: Any) -> None:
            run_calls.append(kwargs)

        fake_nicegui.ui.run = capture_run  # type: ignore[attr-defined]
        app_mod.main(["--reload"])
        assert run_calls[0]["reload"] is True

    def test_main_default_no_reload(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.app as app_mod
        self._patch_internals(monkeypatch)

        run_calls: list[dict[str, Any]] = []

        def capture_run(**kwargs: Any) -> None:
            run_calls.append(kwargs)

        fake_nicegui.ui.run = capture_run  # type: ignore[attr-defined]
        app_mod.main([])
        assert run_calls[0]["reload"] is False

    def test_main_calls_setup_cli_path(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.app as app_mod
        mock_setup = MagicMock()
        monkeypatch.setattr(app_mod, "_setup_cli_path", mock_setup)
        monkeypatch.setattr(
            app_mod, "_load_config_and_session", MagicMock(return_value=(FAKE_CFG, FAKE_TOKEN))
        )
        monkeypatch.setattr(app_mod, "_resolve_storage_secret", MagicMock(return_value="s"))
        app_mod.main(["--cli-path", "/tmp/cli"])
        mock_setup.assert_called_once_with("/tmp/cli")

    def test_main_calls_load_config_and_session(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bosch_camera_frontend.app as app_mod
        mock_load = MagicMock(return_value=(FAKE_CFG, FAKE_TOKEN))
        monkeypatch.setattr(app_mod, "_setup_cli_path", MagicMock())
        monkeypatch.setattr(app_mod, "_load_config_and_session", mock_load)
        monkeypatch.setattr(app_mod, "_resolve_storage_secret", MagicMock(return_value="s"))
        app_mod.main(["--config", "/tmp/bosch_config.json"])
        mock_load.assert_called_once_with("/tmp/bosch_config.json")

    def test_main_registers_on_startup(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """app.on_startup is called with a callable during main()."""
        import bosch_camera_frontend.app as app_mod
        self._patch_internals(monkeypatch)

        startup_callbacks: list[Any] = []

        def capture_startup(fn: Any) -> Any:
            startup_callbacks.append(fn)
            return fn

        fake_nicegui.app.on_startup = capture_startup  # type: ignore[attr-defined]
        app_mod.main([])
        assert len(startup_callbacks) == 1
        assert callable(startup_callbacks[0])

    async def test_on_startup_populates_storage(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calling the _on_startup closure fills app.storage.general."""
        import bosch_camera_frontend.app as app_mod
        self._patch_internals(monkeypatch)

        startup_callbacks: list[Any] = []

        def capture_startup(fn: Any) -> Any:
            startup_callbacks.append(fn)
            return fn

        fake_nicegui.app.on_startup = capture_startup  # type: ignore[attr-defined]
        app_mod.main([])

        # Execute the startup coroutine.
        await startup_callbacks[0]()

        storage = fake_nicegui.app.storage.general
        assert storage["cfg"] == FAKE_CFG
        assert storage["token"] == FAKE_TOKEN
        assert "config_path" in storage

    async def test_on_startup_config_path_empty_default(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no --config given, config_path in storage is '(CLI default)'."""
        import bosch_camera_frontend.app as app_mod
        self._patch_internals(monkeypatch)

        startup_callbacks: list[Any] = []

        def capture_startup(fn: Any) -> Any:
            startup_callbacks.append(fn)
            return fn

        fake_nicegui.app.on_startup = capture_startup  # type: ignore[attr-defined]
        app_mod.main([])  # no --config

        await startup_callbacks[0]()
        assert fake_nicegui.app.storage.general["config_path"] == "(CLI default)"

    async def test_on_startup_config_path_set(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When --config is given, config_path in storage matches."""
        import bosch_camera_frontend.app as app_mod
        self._patch_internals(monkeypatch)

        startup_callbacks: list[Any] = []

        def capture_startup(fn: Any) -> Any:
            startup_callbacks.append(fn)
            return fn

        fake_nicegui.app.on_startup = capture_startup  # type: ignore[attr-defined]
        app_mod.main(["--config", "/my/path.json"])

        await startup_callbacks[0]()
        assert fake_nicegui.app.storage.general["config_path"] == "/my/path.json"

    def test_reload_config_and_token_success(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_reload_config_and_token updates storage and returns (cfg, token)."""
        import bosch_camera_frontend.app as app_mod
        import bosch_camera_frontend.adapters.cli_bridge as bridge
        self._patch_internals(monkeypatch)
        app_mod.main([])

        # Patch _load_config_and_session again to simulate a new config.
        new_cfg = dict(FAKE_CFG, language="de")
        monkeypatch.setattr(
            app_mod,
            "_load_config_and_session",
            MagicMock(return_value=(new_cfg, "new.token.value")),
        )

        reloader = bridge.reload_config_and_token  # type: ignore[attr-defined]
        result = reloader()
        assert result is not None
        returned_cfg, returned_token = result
        assert returned_cfg == new_cfg
        assert returned_token == "new.token.value"
        assert fake_nicegui.app.storage.general["cfg"] == new_cfg
        assert fake_nicegui.app.storage.general["token"] == "new.token.value"

    def test_reload_config_and_token_systemexit_returns_none(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_reload_config_and_token returns None when _load_config_and_session exits."""
        import bosch_camera_frontend.app as app_mod
        import bosch_camera_frontend.adapters.cli_bridge as bridge
        self._patch_internals(monkeypatch)
        app_mod.main([])

        monkeypatch.setattr(
            app_mod,
            "_load_config_and_session",
            MagicMock(side_effect=SystemExit(1)),
        )

        reloader = bridge.reload_config_and_token  # type: ignore[attr-defined]
        result = reloader()
        assert result is None

    def test_reload_config_and_token_generic_exception_returns_none(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_reload_config_and_token returns None on unexpected errors."""
        import bosch_camera_frontend.app as app_mod
        import bosch_camera_frontend.adapters.cli_bridge as bridge
        self._patch_internals(monkeypatch)
        app_mod.main([])

        monkeypatch.setattr(
            app_mod,
            "_load_config_and_session",
            MagicMock(side_effect=RuntimeError("disk full")),
        )

        reloader = bridge.reload_config_and_token  # type: ignore[attr-defined]
        result = reloader()
        assert result is None

    def test_storage_secret_used_in_ui_run(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """storage_secret kwarg passed to ui.run comes from _resolve_storage_secret."""
        import bosch_camera_frontend.app as app_mod
        self._patch_internals(monkeypatch)
        monkeypatch.setattr(app_mod, "_resolve_storage_secret", MagicMock(return_value="test-secret-xyz"))

        run_calls: list[dict[str, Any]] = []

        def capture_run(**kwargs: Any) -> None:
            run_calls.append(kwargs)

        fake_nicegui.ui.run = capture_run  # type: ignore[attr-defined]
        app_mod.main([])
        assert run_calls[0]["storage_secret"] == "test-secret-xyz"

    def test_reload_fn_name_stored_in_general(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """app.storage.general['__reload_fn_name__'] is set to 'reload_config_and_token'."""
        import bosch_camera_frontend.app as app_mod
        self._patch_internals(monkeypatch)
        app_mod.main([])
        assert (
            fake_nicegui.app.storage.general["__reload_fn_name__"]
            == "reload_config_and_token"
        )

    def test_br_reload_callable_after_main(
        self, fake_nicegui: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cli_bridge.reload_config_and_token is callable after main() runs."""
        import bosch_camera_frontend.app as app_mod
        import bosch_camera_frontend.adapters.cli_bridge as bridge
        self._patch_internals(monkeypatch)
        app_mod.main([])
        assert callable(bridge.reload_config_and_token)  # type: ignore[attr-defined]
