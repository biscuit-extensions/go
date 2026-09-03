from __future__ import annotations

from unittest.mock import MagicMock
import pytest


class MockCommands:
    def __init__(self):
        self._commands = {}

    def register_command(self, name, callback):
        self._commands[name] = callback

    @property
    def commands(self):
        return self._commands.copy()


class MockSettings:
    def __init__(self):
        self._settings = {}
        self._data = {}

    def register_setting(self, name, type="string", default=None, description=""):
        self._settings[name] = {
            "name": name,
            "type": type,
            "default": default,
            "description": description,
        }
        if name not in self._data and default is not None:
            self._data[name] = default

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def get_registered_settings(self):
        return self._settings.copy()


class MockStatusbarButton:
    def __init__(self, **kwargs):
        self.text = kwargs.get("text", "")
        self.icon = kwargs.get("icon", "")
        self.callback = kwargs.get("callback")
        self.description = kwargs.get("description", "")
        self.side = kwargs.get("side", None)
        self.visible = False

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def change_text(self, text):
        self.text = text

    def change_icon(self, icon):
        self.icon = icon

    def change_description(self, desc):
        self.description = desc


class MockStatusbar:
    def __init__(self):
        self.buttons = []

    def add_button(self, **kwargs):
        btn = MockStatusbarButton(**kwargs)
        self.buttons.append(btn)
        return btn


class MockTerminalManager:
    def __init__(self):
        self.opened_terminals = []

    def open_terminal(self, command=None):
        self.opened_terminals.append(command)
        return MagicMock()


class MockExtensionsAPI:
    def __init__(self):
        self.base = MagicMock()
        self.logger = MagicMock()
        self.notifications = MagicMock()
        self.commands = MockCommands()
        self.settings = MockSettings()
        self.statusbar = MockStatusbar()
        self.views = MagicMock()
        self.editors = MagicMock()
        self.terminalmanager = MockTerminalManager()
        self.registered_extensions = {}

        self.register_comment_prefix = MagicMock()
        self.register_langserver = MagicMock()
        self.register_run_command = MagicMock()
        self.register_debugger = MagicMock()
        self.register_dap_adapter = MagicMock()

    def register(self, name, extension):
        self.registered_extensions[name] = extension

    def register_extension(self, name, extension):
        self.register(name, extension)


@pytest.fixture
def mock_api():
    """Provides a fast, headless mock of ExtensionsAPI."""
    return MockExtensionsAPI()


@pytest.fixture(scope="session")
def app_instance():
    """Fast headless app fixture for test compatibility."""
    mock_app = MagicMock()
    mock_app.api = MockExtensionsAPI()
    return mock_app
