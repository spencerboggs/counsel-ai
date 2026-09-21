"""Secrets status reports per-field presence."""

from __future__ import annotations

from backend.config.secrets import SecretsFile, save_secrets, secrets_status


def test_secrets_status_per_field(tmp_path, monkeypatch):
    secrets_path = tmp_path / "secrets.local.json"
    monkeypatch.setattr("backend.config.secrets.SECRETS_PATH", secrets_path)

    save_secrets(
        SecretsFile(
            alpaca_paper_key="PKTEST",
            openrouter_api_key="or-key",
            ollama_base_url="http://127.0.0.1:11434",
        )
    )

    status = secrets_status()
    assert status["keys"]["alpaca_paper_key"] is True
    assert status["keys"]["alpaca_paper_secret"] is False
    assert status["keys"]["alpaca_paper"] is False
    assert status["keys"]["openrouter_api_key"] is True
    assert status["ollama_base_url"] == "http://127.0.0.1:11434"
    assert status["keys"]["ollama_base_url"] is True
