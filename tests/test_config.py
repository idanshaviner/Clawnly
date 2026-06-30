"""Tests for API-key resolution and the friendly no-key error (config.py)."""

import pytest

import config


def test_resolve_key_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
    assert config.resolve_api_key() == "sk-ant-test-123"


def test_get_client_raises_clear_error_when_no_key(monkeypatch):
    # no env var and (pretend) no .env file -> a helpful message, not the cryptic SDK one.
    monkeypatch.setattr(config, "resolve_api_key", lambda: None)
    with pytest.raises(ValueError) as info:
        config.get_client()
    msg = str(info.value)
    assert "Demo mode" in msg and ".env" in msg


def test_get_client_builds_with_key(monkeypatch):
    monkeypatch.setattr(config, "resolve_api_key", lambda: "sk-ant-test-123")
    client = config.get_client()           # constructs, no network call
    assert client is not None
