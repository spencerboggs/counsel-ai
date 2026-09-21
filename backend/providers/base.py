"""Provider protocol definitions."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMResponse(BaseModel):
    content: str
    model: str
    provider: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class UsageInfo(BaseModel):
    request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    last_used_at: str | None = None


class QuotaInfo(BaseModel):
    known: bool = False
    limit: int | None = None
    remaining: int | None = None
    reset_at: str | None = None
    note: str | None = "quota unknown"


class Quote(BaseModel):
    ticker: str
    price: float | None = None
    currency: str | None = None
    as_of: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class HistoryBar(BaseModel):
    date: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None


class NewsItem(BaseModel):
    title: str
    url: str | None = None
    published_at: str | None = None
    source: str | None = None
    summary: str | None = None


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str | None = None
    published_at: str | None = None


class FetchedDocument(BaseModel):
    url: str
    title: str | None = None
    text: str
    retrieved_at: str


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def generate(
        self,
        model: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse: ...

    async def get_usage(self) -> UsageInfo: ...

    async def get_quota(self) -> QuotaInfo: ...

    async def list_models(self) -> list[str]: ...

    async def health(self) -> bool: ...


@runtime_checkable
class MarketDataProvider(Protocol):
    name: str

    async def get_quote(self, ticker: str) -> Quote: ...

    async def get_history(self, ticker: str, period: str) -> list[HistoryBar]: ...

    async def get_financials(self, ticker: str) -> dict[str, Any]: ...

    async def get_news(self, ticker: str) -> list[NewsItem]: ...


@runtime_checkable
class WebResearchProvider(Protocol):
    name: str

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]: ...

    async def fetch(self, url: str) -> FetchedDocument: ...
