"""Tests for environment-based configuration loading."""

import pytest

from app.config import Settings


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure no stray environment values leak into the defaults test.
    for var in (
        "APP_NAME",
        "GROQ_API_KEY",
        "GROQ_MODEL",
        "GROQ_BASE_URL",
        "MAX_ITERATIONS",
        "TASK_TIMEOUT_SECONDS",
        "MAX_OUTPUT_BYTES",
        "SANDBOX_IMAGE",
        "SANDBOX_MEMORY",
        "SANDBOX_CPUS",
        "SANDBOX_PIDS_LIMIT",
        "SANDBOX_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings.from_env()
    assert settings.app_name == "autonomous-sandbox-agent"
    assert settings.groq_api_key == ""
    assert settings.groq_model == ""
    assert settings.max_iterations == 25
    assert settings.task_timeout_seconds == 600
    assert settings.sandbox_image == "autonomous-sandbox-agent:latest"
    assert settings.sandbox_memory == "256m"
    assert settings.sandbox_cpus == "0.5"
    assert settings.sandbox_pids_limit == 64
    assert settings.sandbox_timeout_seconds == 30


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    monkeypatch.setenv("MAX_ITERATIONS", "7")
    monkeypatch.setenv("SANDBOX_MEMORY", "512m")
    monkeypatch.setenv("SANDBOX_PIDS_LIMIT", "16")

    settings = Settings.from_env()
    assert settings.groq_api_key == "test-key-not-real"
    assert settings.groq_model == "test-model"
    assert settings.max_iterations == 7
    assert settings.sandbox_memory == "512m"
    assert settings.sandbox_pids_limit == 16
