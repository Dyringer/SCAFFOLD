"""Shared pytest fixtures.

`isolate_settings` is autouse: it redirects the global settings_store singleton
at a throwaway temp file and restores its state after each test. Without it,
any test that constructs a TerminalSession (or otherwise calls
settings_store.set) writes into the developer's real .local/settings.json —
which has repeatedly polluted the live plot config and caused "blank plot"
surprises. Tests must never touch real settings.
"""
from __future__ import annotations

import pytest

from app.core.settings_store import settings_store


@pytest.fixture(autouse=True)
def isolate_settings(tmp_path, monkeypatch):
    # Point the singleton at a temp file and give it a clean slate, so writes
    # during the test never reach the real settings file.
    monkeypatch.setattr(settings_store, "_path", tmp_path / "settings.json")
    saved = dict(settings_store._data)
    settings_store._data = {}
    yield
    # Restore the in-memory state other tests/sessions may rely on.
    settings_store._data = saved
