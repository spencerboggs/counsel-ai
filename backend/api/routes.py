"""HTTP routes for the AI Counsel backend."""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.api.discovery_routes import discovery_router
from backend.api.history_routes import history_router
from backend.api.market_routes import market_router
from backend.api.portfolio_routes import portfolio_router
from backend.api.settings_routes import settings_router
from backend.api.tax_routes import tax_router
from backend.api.autopilot_routes import autopilot_router
from backend.api.schemas import (
    ConfigResponse,
    DiscoveredModel,
    HealthResponse,
    ModelRegistryItem,
    ModelsResponse,
    ModelUsageItem,
    UsageResponse,
)
from backend.config.secrets import load_secrets
from backend.config.settings import get_app_config, get_settings
from backend.providers.ollama import OllamaProvider
from backend.storage.usage import UsageStore

api_router = APIRouter()
api_router.include_router(discovery_router)
api_router.include_router(portfolio_router)
api_router.include_router(tax_router)
api_router.include_router(autopilot_router)
api_router.include_router(market_router)
api_router.include_router(history_router)
api_router.include_router(settings_router)


def _ollama_from_request(request: Request) -> OllamaProvider:
    settings = get_settings()
    config = get_app_config()
    secrets = load_secrets()
    base_url = (
        secrets.ollama_base_url
        or config.providers.ollama.base_url
        or settings.ollama_base_url
    )
    return OllamaProvider(base_url=base_url)


@api_router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    config = get_app_config()
    ollama_enabled = config.providers.ollama.enabled
    ollama = _ollama_from_request(request)
    reachable = await ollama.health() if ollama_enabled else False
    models: list[str] = []
    if reachable:
        models = await ollama.list_models()

    return HealthResponse(
        status="ok",
        version="0.1.0",
        ollama={
            "enabled": ollama_enabled,
            "reachable": reachable,
            "base_url": ollama.base_url,
            "model_count": len(models),
        },
    )


@api_router.get("/models", response_model=ModelsResponse)
async def list_models(request: Request) -> ModelsResponse:
    config = get_app_config()
    ollama = _ollama_from_request(request)
    ollama_available = False
    discovered_names: list[str] = []

    if config.providers.ollama.enabled:
        ollama_available = await ollama.health()
        if ollama_available:
            discovered_names = await ollama.list_models()

    discovered = [
        DiscoveredModel(name=name, provider="ollama") for name in discovered_names
    ]

    registry: list[ModelRegistryItem] = []
    for entry in config.models:
        resolved = None
        available = False
        if entry.provider == "ollama":
            if entry.model != "auto" and entry.model in discovered_names:
                resolved = entry.model
                available = True
            elif entry.model == "auto" and discovered_names:
                resolved = discovered_names[0]
                available = True
        registry.append(
            ModelRegistryItem(
                id=entry.id,
                provider=entry.provider,
                model=entry.model,
                roles=entry.roles,
                enabled=entry.enabled,
                priority=entry.priority,
                resolved_model=resolved,
                available=available and entry.enabled,
            )
        )

    return ModelsResponse(
        registry=registry,
        discovered=discovered,
        ollama_available=ollama_available,
    )


@api_router.get("/models/usage", response_model=UsageResponse)
async def models_usage(request: Request) -> UsageResponse:
    store = UsageStore(request.app.state.db)
    rows = await store.list_usage()
    items = [
        ModelUsageItem(
            model_id=row["model_id"],
            provider=row["provider"],
            model_name=row["model_name"],
            request_count=row["request_count"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            last_used_at=row["last_used_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]
    return UsageResponse(items=items)


@api_router.get("/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    config = get_app_config()
    providers = {
        "ollama": {
            "enabled": config.providers.ollama.enabled,
            "base_url": config.providers.ollama.base_url,
        },
        "openrouter": {"enabled": config.providers.openrouter.enabled},
        "groq": {"enabled": config.providers.groq.enabled},
        "gemini": {"enabled": config.providers.gemini.enabled},
    }
    models = [
        ModelRegistryItem(
            id=m.id,
            provider=m.provider,
            model=m.model,
            roles=m.roles,
            enabled=m.enabled,
            priority=m.priority,
        )
        for m in config.models
    ]
    return ConfigResponse(
        application=config.application,
        research=config.research,
        discovery=config.discovery,
        discovery_score=dict(config.discovery_score),
        scoring=config.scoring,
        providers=providers,
        models=models,
    )
