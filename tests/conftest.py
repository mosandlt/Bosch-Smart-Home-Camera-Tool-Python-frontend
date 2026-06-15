"""Shared test fixtures — a comprehensive fake NiceGUI that lets page and
component code run end-to-end without a browser, so we can exercise (and
cover) the real handler logic with cli_bridge mocked.

The fake is intentionally permissive: every UI element supports fluent
chaining (`.classes().style().props()...`), works as a context manager
(`with ui.card(): ...`), and accepts any method call (`set_text`,
`set_value`, `set_source`, `enable`, ...) as a recorded no-op. `ui.card`
and `ui.element` are real classes so `class CameraCard(ui.card)` and
`class HlsPlayer(ui.element)` subclassing works.

Use the `fake_nicegui` fixture in a test to install the fake before importing
any page/component module. All fixtures are FAKE-DATA only (never real device
IDs / MACs / tokens).
"""

from __future__ import annotations

import os
import sys
import types
from typing import Any

import pytest

# Real sibling CLI repo path (some tests inject it; most mock cli_bridge._bc).
CLI_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",  # frontend repo root
        "..",  # bosch kamera/
        "Bosch-Smart-Home-Camera-Tool-Python",
    )
)


class FakeElement:
    """A permissive stand-in for any NiceGUI element.

    Records the calls made on it so tests can assert on UI side effects, while
    returning ``self`` from every method so fluent chains keep working.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.init_args = args
        self.init_kwargs = kwargs
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        # Frequently-read back values for assertions.
        self.text: Any = None
        self.value: Any = kwargs.get("value")
        self.source: Any = None
        self.content: Any = None
        self.enabled: bool = True
        self.handlers: dict[str, Any] = {}

    # Context-manager support: `with ui.card(): ...`
    def __enter__(self) -> "FakeElement":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    # Common concrete setters (so tests can read back state).
    def set_text(self, text: Any) -> "FakeElement":
        self.text = text
        return self._record("set_text", text)

    def set_value(self, value: Any) -> "FakeElement":
        self.value = value
        return self._record("set_value", value)

    def set_source(self, source: Any) -> "FakeElement":
        self.source = source
        return self._record("set_source", source)

    def set_content(self, content: Any) -> "FakeElement":
        self.content = content
        return self._record("set_content", content)

    def enable(self) -> "FakeElement":
        self.enabled = True
        return self._record("enable")

    def disable(self) -> "FakeElement":
        self.enabled = False
        return self._record("disable")

    def on(self, event: str, handler: Any = None, *a: Any, **kw: Any) -> "FakeElement":
        self.handlers[event] = handler
        return self._record("on", event)

    def _record(self, name: str, *args: Any, **kwargs: Any) -> "FakeElement":
        self.calls.append((name, args, kwargs))
        return self

    # Any other method (classes/style/props/tooltip/clear/...) chains.
    def __getattr__(self, name: str) -> Any:
        def _method(*args: Any, **kwargs: Any) -> "FakeElement":
            # __getattr__ only fires for missing attrs, so self.calls exists.
            self.calls.append((name, args, kwargs))
            return self

        return _method


def _factory(*args: Any, **kwargs: Any) -> FakeElement:
    return FakeElement(*args, **kwargs)


def _passthrough_decorator(*d_args: Any, **d_kwargs: Any) -> Any:
    """Stand-in for `@ui.page(...)` / `@ui.middleware(...)` — returns the
    function unchanged so the decorated handler stays directly callable."""

    def wrap(func: Any) -> Any:
        return func

    return wrap


def build_fake_nicegui() -> types.ModuleType:
    """Construct (but do not install) a fake `nicegui` module tree."""
    ng = types.ModuleType("nicegui")
    ui = types.SimpleNamespace()

    # Decorators / app lifecycle.
    ui.page = _passthrough_decorator
    ui.middleware = _passthrough_decorator
    ui.run = _factory

    # Layout + widgets — all produce a FakeElement.
    for name in (
        "label",
        "button",
        "switch",
        "select",
        "slider",
        "image",
        "html",
        "icon",
        "badge",
        "table",
        "separator",
        "tooltip",
        "row",
        "column",
        "grid",
        "card",
        "header",
        "footer",
        "expansion",
        "timer",
        "on",
        "notify",
        "page_title",
        "add_head_html",
        "add_css",
        "add_scss",
        "add_sass",
        "input",
        "number",
        "chip",
        "spinner",
        "link",
        "markdown",
    ):
        setattr(ui, name, _factory)

    # Subclassable element bases — must be real classes.
    ui.card = FakeElement
    ui.element = FakeElement

    # Navigation.
    ui.navigate = types.SimpleNamespace(to=_factory, back=_factory, reload=_factory)

    ng.ui = ui

    # app + storage (real dict so pages can read/write general state).
    app = types.SimpleNamespace()
    app.storage = types.SimpleNamespace(general={}, client={}, user={}, tab={})
    app.on_startup = _passthrough_decorator
    app.on_shutdown = _passthrough_decorator
    app.on_connect = _passthrough_decorator
    app.on_disconnect = _passthrough_decorator
    ng.app = app

    return ng


@pytest.fixture
def fake_nicegui() -> Any:
    """Install the fake `nicegui` into sys.modules for the duration of a test.

    Yields the fake module. On teardown it removes the fake and any imported
    `bosch_camera_frontend` submodules so the next test re-imports cleanly
    against whatever nicegui it expects.
    """
    saved = {k: sys.modules.get(k) for k in ("nicegui", "nicegui.ui")}
    saved_frontend = {
        k: v for k, v in sys.modules.items() if k.startswith("bosch_camera_frontend")
    }
    # Fresh import of frontend modules against the fake.
    for k in list(saved_frontend):
        del sys.modules[k]

    ng = build_fake_nicegui()
    sys.modules["nicegui"] = ng
    sys.modules["nicegui.ui"] = ng.ui  # type: ignore[assignment]

    try:
        yield ng
    finally:
        # Drop frontend modules imported during the test.
        for k in [m for m in sys.modules if m.startswith("bosch_camera_frontend")]:
            del sys.modules[k]
        # Restore nicegui state.
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        for k, v in saved_frontend.items():
            sys.modules[k] = v


@pytest.fixture
def fake_camera() -> dict[str, Any]:
    """A single fake camera dict — FAKE IDs only, never real device values."""
    return {
        "id": "11111111-2222-3333-4444-555555555555",
        "name": "Test Cam",
        "model": "CAMERA_EYES",
        "firmware": "9.0.0",
        "mac": "aa:bb:cc:dd:ee:ff",
        "download_folder": "Test Cam",
        "local_ip": "",
        "has_light": False,
        "pan_limit": 0,
    }


@pytest.fixture
def fake_cfg(fake_camera: dict[str, Any]) -> dict[str, Any]:
    """A minimal fake bosch_config dict with a fake bearer token."""
    return {
        "account": {"bearer_token": "header.payload.signature"},
        "language": "en",
        "cameras": {"Test Cam": fake_camera},
    }
