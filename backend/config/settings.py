"""Application settings and YAML config loading."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class OllamaProviderConfig(BaseModel):
    enabled: bool = True
    base_url: str = "http://127.0.0.1:11434"


class RemoteProviderConfig(BaseModel):
    enabled: bool = False


class ProvidersConfig(BaseModel):
    ollama: OllamaProviderConfig = Field(default_factory=OllamaProviderConfig)
    openrouter: RemoteProviderConfig = Field(default_factory=RemoteProviderConfig)
    groq: RemoteProviderConfig = Field(default_factory=RemoteProviderConfig)
    gemini: RemoteProviderConfig = Field(default_factory=RemoteProviderConfig)


class ModelRegistryEntry(BaseModel):
    id: str
    provider: str
    model: str = "auto"
    roles: list[str] = Field(default_factory=list)
    enabled: bool = True
    priority: int = 100


class AppYamlConfig(BaseModel):
    application: dict[str, Any] = Field(default_factory=dict)
    research: dict[str, Any] = Field(default_factory=dict)
    discovery: dict[str, Any] = Field(default_factory=dict)
    discovery_score: dict[str, float] = Field(default_factory=dict)
    scoring: dict[str, Any] = Field(default_factory=dict)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    models: list[ModelRegistryEntry] = Field(default_factory=list)
    autopilot: dict[str, Any] = Field(default_factory=dict)
    trading: dict[str, Any] = Field(default_factory=dict)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(default="127.0.0.1", alias="AI_COUNSEL_HOST")
    port: int = Field(default=8000, alias="AI_COUNSEL_PORT")
    config_path: str = Field(default="config.yaml", alias="AI_COUNSEL_CONFIG")
    db_path: str = Field(
        default="backend/data/ai_counsel.db",
        alias="AI_COUNSEL_DB_PATH",
    )
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        alias="OLLAMA_BASE_URL",
    )

    def resolve_config_path(self) -> Path:
        path = Path(self.config_path)
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path

    def resolve_db_path(self) -> Path:
        path = Path(self.db_path)
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path


def load_yaml_config(path: Path) -> AppYamlConfig:
    if not path.exists():
        return AppYamlConfig()
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return AppYamlConfig.model_validate(raw)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    object.__setattr__(settings, "db_path", str(settings.resolve_db_path()))
    return settings


@lru_cache
def get_app_config() -> AppYamlConfig:
    settings = get_settings()
    return load_yaml_config(settings.resolve_config_path())
