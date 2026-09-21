"""API response models shared with the frontend contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    version: str
    ollama: dict[str, Any]


class ModelRegistryItem(BaseModel):
    id: str
    provider: str
    model: str
    roles: list[str] = Field(default_factory=list)
    enabled: bool = True
    priority: int = 100
    resolved_model: str | None = None
    available: bool = False


class DiscoveredModel(BaseModel):
    name: str
    provider: str = "ollama"


class ModelsResponse(BaseModel):
    registry: list[ModelRegistryItem]
    discovered: list[DiscoveredModel]
    ollama_available: bool


class ModelUsageItem(BaseModel):
    model_id: str
    provider: str
    model_name: str
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    last_used_at: str | None = None
    updated_at: str | None = None


class UsageResponse(BaseModel):
    items: list[ModelUsageItem]


class ConfigResponse(BaseModel):
    application: dict[str, Any]
    research: dict[str, Any]
    discovery: dict[str, Any]
    discovery_score: dict[str, float] = Field(default_factory=dict)
    scoring: dict[str, Any]
    providers: dict[str, Any]
    models: list[ModelRegistryItem]


class DiscoveryRunRequest(BaseModel):
    output_count: int = Field(default=10, ge=1, le=25)
    universe: str = "US Equities"
    market_cap: str = "Any"
    sector: str = "Any"
    risk_tolerance: str = "Moderate"
    time_horizon: str = "1-3 years"
    investable_amount: float = Field(default=100, ge=10, le=100_000)
    min_whole_shares: int = Field(default=5, ge=1, le=100)
    exclude_seen: bool = True
    candidate_pool_size: int | None = Field(default=None, ge=10, le=20)
    screen_from_universe: int | None = Field(default=None, ge=10, le=20000)
    # Keep searching until this many names meet both floors (0 = off / take top by score).
    min_score: float = Field(default=0, ge=0, le=100)
    min_panel_score: float = Field(default=0, ge=0, le=100)
    # invest = multi-day/hold; daytrade = same-session; swing = 1-7d event-first.
    lane: str = Field(default="invest", pattern="^(invest|daytrade|swing)$")
    hold_days: int = Field(default=3, ge=1, le=7)


class ReexamineRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    investable_amount: float | None = Field(default=None, ge=10, le=100_000)
    min_whole_shares: int | None = Field(default=None, ge=1, le=100)
    lane: str = Field(default="invest", pattern="^(invest|daytrade|swing)$")


class TradeOrderRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    notional: float = Field(gt=0, le=1_000_000)
    venue: str = "paper_local"
    live_confirmed: bool = False
    price: float | None = Field(default=None, gt=0)
    source_run_id: str | None = None
    wash_override_phrase: str | None = None


class DiscoveryRunCreated(BaseModel):
    run_id: str
    status: str


class ProgressStageOut(BaseModel):
    id: str
    label: str
    status: str
    detail: str | None = None


class PaperPositionCreate(BaseModel):
    ticker: str
    shares: float = Field(gt=0)
    cost_basis: float = Field(gt=0)
    source_run_id: str | None = None
    notes: str | None = None
    wash_override_phrase: str | None = None


class CandidateSummary(BaseModel):
    ticker: str
    score: float
    confidence: float
    signal: str
    name: str | None = None
    sector: str | None = None
    price: float | None = None
    shares_buyable: int | None = None
    panel_score: float | None = None
    panel_spread: float | None = None
    meets_criteria: bool | None = None
    miss_reason: str | None = None


class AgentFindingOut(BaseModel):
    role: str | None = None
    model: str | None = None
    score: float | None = None
    confidence: float | None = None
    summary: str | None = None
    risks: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    dimension_scores: dict[str, float] = Field(default_factory=dict)


class PaperPositionOut(BaseModel):
    id: str
    ticker: str
    shares: float
    cost_basis: float
    opened_at: str
    closed_at: str | None = None
    status: str
    source_run_id: str | None = None
    notes: str | None = None
    last_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    # Enriched mark-to-market / quote fields (best-effort).
    cost_total: float | None = None
    unrealized_pnl_pct: float | None = None
    name: str | None = None
    currency: str | None = None
    change: float | None = None
    change_pct: float | None = None
    previous_close: float | None = None
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    market_cap: float | None = None
    pe: float | None = None
    sector: str | None = None
    industry: str | None = None
    beta: float | None = None
    avg_volume: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    score: float | None = None
    signal: str | None = None
    lane: str | None = None
    quote_as_of: str | None = None
    realized_gain: float | None = None


class DiscoveryRunResponse(BaseModel):
    id: str
    status: str
    input: dict[str, Any]
    stages: list[ProgressStageOut]
    candidates: list[CandidateSummary]
    error: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    researcher_available: bool | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)


class SecretsUpdateRequest(BaseModel):
    ollama_base_url: str | None = None
    openrouter_api_key: str | None = None
    groq_api_key: str | None = None
    gemini_api_key: str | None = None
    alpaca_paper_key: str | None = None
    alpaca_paper_secret: str | None = None
    alpaca_live_key: str | None = None
    alpaca_live_secret: str | None = None
    trading_mode: str | None = None
    live_trading_confirmed: bool | None = None
    fred_api_key: str | None = None
    # Empty string means "clear this key"
    clear_fields: list[str] = Field(default_factory=list)


class PortfolioStatsOut(BaseModel):
    trading_mode: str
    open_positions: int
    closed_positions: int
    invested_cost: float
    market_value: float
    unrealized_pnl: float
    realized_closed: int
    win_count: int | None = None
    avg_position_size: float | None = None


class CandidateDetailResponse(BaseModel):
    ticker: str
    score: float
    confidence: float
    signal: str
    calculation: str
    components: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    researcher_summary: str | None = None
    researcher: dict[str, Any] | None = None
    name: str | None = None
    sector: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    panel_score: float | None = None
    panel_spread: float | None = None
    agents: list[AgentFindingOut] = Field(default_factory=list)
