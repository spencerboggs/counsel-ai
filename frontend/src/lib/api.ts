import type {
  CandidateDetailResponse,
  CandidateSighting,
  ChartSnapshot,
  ConfigResponse,
  DiscoveryRunCreated,
  DiscoveryRunRequest,
  DiscoveryRunResponse,
  HealthResponse,
  ModelsResponse,
  PaperPosition,
  PortfolioMode,
  PortfolioStats,
  SecretsStatus,
  UsageResponse,
} from "@/types/api";

const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ||
  "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      ...init,
    });
  } catch {
    throw new ApiError("Backend unreachable", 0);
  }

  if (!response.ok) {
    let detail = `Request failed: ${path}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  baseUrl: API_BASE,
  health: () => request<HealthResponse>("/health"),
  models: () => request<ModelsResponse>("/models"),
  usage: () => request<UsageResponse>("/models/usage"),
  config: () => request<ConfigResponse>("/config"),
  startDiscovery: (body: DiscoveryRunRequest) =>
    request<DiscoveryRunCreated>("/discovery/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getDiscoveryRun: (runId: string) =>
    request<DiscoveryRunResponse>(`/discovery/runs/${runId}`),
  cancelDiscovery: (runId: string) =>
    request<{
      run_id: string;
      status: string;
      cancel_requested: boolean;
      task_known?: boolean;
    }>(`/discovery/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
    }),
  getCandidateDetail: (runId: string, ticker: string) =>
    request<CandidateDetailResponse>(
      `/discovery/runs/${runId}/candidates/${encodeURIComponent(ticker)}`,
    ),
  listPositions: (status = "open") =>
    request<PaperPosition[]>(
      `/portfolio/positions?status=${encodeURIComponent(status)}`,
    ),
  openPaperPosition: (body: {
    ticker: string;
    shares: number;
    cost_basis: number;
    source_run_id?: string | null;
    notes?: string | null;
  }) =>
    request<PaperPosition>("/portfolio/positions", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  closePaperPosition: (id: string) =>
    request<PaperPosition>(`/portfolio/positions/${id}/close`, {
      method: "POST",
    }),
  portfolioMode: () => request<PortfolioMode>("/portfolio/mode"),
  portfolioStats: () => request<PortfolioStats>("/portfolio/stats"),
  chartSnapshot: (ticker: string, range = "1mo") =>
    request<ChartSnapshot>(
      `/market/chart/${encodeURIComponent(ticker)}?range=${encodeURIComponent(range)}`,
    ),
  secretsStatus: () => request<SecretsStatus>("/settings/secrets/status"),
  updateSecrets: (body: Record<string, unknown>) =>
    request<SecretsStatus>("/settings/secrets", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  candidateHistory: (lane?: "invest" | "daytrade" | "swing") =>
    request<{
      count: number;
      items: CandidateSighting[];
      known_tickers: string[];
      lane?: string | null;
    }>(
      lane
        ? `/history/candidates?lane=${encodeURIComponent(lane)}`
        : "/history/candidates",
    ),
  clearCandidateHistory: (lane?: "invest" | "daytrade" | "swing") =>
    request<{
      cleared: boolean;
      lane?: string | null;
      stocks_cleared?: number;
      llm_cache_cleared?: number;
      stocks_remaining?: number;
      note?: string;
    }>(
      lane
        ? `/history/candidates?lane=${encodeURIComponent(lane)}`
        : "/history/candidates",
      { method: "DELETE" },
    ),
  exportCandidatesUrl: (
    format: "json" | "csv",
    lane?: "invest" | "daytrade" | "swing",
  ) =>
    `${API_BASE}/history/candidates.${format}${
      lane ? `?lane=${encodeURIComponent(lane)}` : ""
    }`,
  taxSummary: () => request<Record<string, unknown>>("/tax/summary"),
  taxDispositions: () =>
    request<{ count: number; items: Record<string, unknown>[] }>(
      "/tax/dispositions",
    ),
  taxLots: () =>
    request<{ count: number; items: Record<string, unknown>[] }>("/tax/lots"),
  taxFills: () =>
    request<{ count: number; items: Record<string, unknown>[] }>("/tax/fills"),
  taxWashBlocks: () =>
    request<{ count: number; items: Record<string, unknown>[]; note?: string }>(
      "/tax/wash-blocks",
    ),
  taxCapital: () => request<Record<string, unknown>>("/tax/capital"),
  taxCompliance: () =>
    request<{
      items: Array<{
        section: number;
        title: string;
        status: string;
        notes: string;
      }>;
      counts: Record<string, number>;
      disclaimer: string;
      market_session?: Record<string, unknown>;
      trading_config?: Record<string, unknown>;
      readiness?: {
        paper_ready?: boolean;
        live_requires?: string[];
        deferred_ok_for_paper?: string[];
      };
    }>("/tax/compliance"),
  taxPurgeRequest: (body: {
    entity_type: string;
    entity_id: string;
    reason: string;
    confirmation_phrase: string;
  }) =>
    request<Record<string, unknown>>("/tax/purge-request", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  washCheck: (ticker: string, wash_override_phrase?: string | null) =>
    request<{
      allowed: boolean;
      override?: boolean;
      block?: Record<string, unknown>;
    }>("/tax/wash-check", {
      method: "POST",
      body: JSON.stringify({ ticker, wash_override_phrase }),
    }),
  discoveryUniverse: () =>
    request<{
      ticker_count: number;
      has_dynamic_file: boolean;
      curated_count: number;
      dynamic_count: number;
    }>("/discovery/universe"),
  refreshDiscoveryUniverse: () =>
    request<{
      remote_symbols: number;
      curated_symbols: number;
      merged_symbols: number;
      path: string;
      ticker_count: number;
      has_dynamic_file: boolean;
      curated_count: number;
      dynamic_count: number;
    }>("/discovery/universe/refresh", { method: "POST" }),
  latestDiscovery: () =>
    request<DiscoveryRunResponse | null>("/discovery/latest"),
  placeOrder: (body: {
    ticker: string;
    notional: number;
    venue: "paper_local" | "paper_alpaca" | "live_alpaca";
    live_confirmed: boolean;
    price?: number | null;
    source_run_id?: string | null;
    wash_override_phrase?: string | null;
  }) =>
    request<PaperPosition>("/portfolio/orders", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  reexamine: (ticker: string, lane: "invest" | "daytrade" | "swing" = "invest") =>
    request<DiscoveryRunCreated>("/discovery/reexamine", {
      method: "POST",
      body: JSON.stringify({ ticker, lane }),
    }),
  autopilotStatus: () =>
    request<{
      running: boolean;
      loop_alive?: boolean;
      mode: string;
      is_live: boolean;
      run_id?: string | null;
      started_at?: string | null;
      stopped_at?: string | null;
      asleep_since?: string | null;
      last_cycle_at?: string | null;
      cycle_count?: number;
      last_error?: string | null;
      config?: Record<string, unknown>;
      last_wake?: Record<string, unknown>;
      capital?: Record<string, unknown>;
      cycle_seconds?: number;
      recent_events?: Array<{
        message?: string;
        stage?: string;
        level?: string;
        created_at?: string;
      }>;
      note?: string;
    }>("/autopilot/status"),
  autopilotStart: (body: {
    arm_live_confirmed?: boolean;
    cycle_seconds?: number;
    max_positions?: number;
    max_notional_pct?: number;
    max_new_candidates?: number;
  }) =>
    request<Record<string, unknown>>("/autopilot/start", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  autopilotStop: () =>
    request<Record<string, unknown>>("/autopilot/stop", { method: "POST" }),
  autopilotDecisions: (limit = 40) =>
    request<{ count: number; items: Record<string, unknown>[] }>(
      `/autopilot/decisions?limit=${limit}`,
    ),
  autopilotLatestRun: () =>
    request<Record<string, unknown> | null>("/autopilot/runs/latest"),
  autopilotLearning: (limit = 40) =>
    request<{
      count: number;
      executed?: number;
      rejected_or_blocked?: number;
      wins?: number;
      losses?: number;
      win_rate?: number | null;
      lessons?: string[];
      recent?: Record<string, unknown>[];
      note?: string;
    }>(`/autopilot/learning?limit=${limit}`),
  brokerMonitor: () =>
    request<{
      venue: string;
      broker?: Record<string, unknown> | null;
      local_capital?: Record<string, unknown>;
      learning_journal?: Record<string, unknown>;
      note?: string;
    }>("/portfolio/broker/monitor"),
  killSwitchStatus: () =>
    request<{
      trading_disabled: boolean;
      updated_at?: string | null;
      notes?: string | null;
      effect?: string;
    }>("/settings/trading/kill-switch"),
  setKillSwitch: (trading_disabled: boolean, notes?: string) =>
    request<Record<string, unknown>>("/settings/trading/kill-switch", {
      method: "POST",
      body: JSON.stringify({ trading_disabled, notes }),
    }),
  tradingSession: () =>
    request<{
      session: Record<string, unknown>;
      trading_config: Record<string, unknown>;
      note?: string;
    }>("/settings/trading/session"),
  tradingRiskSnapshot: () =>
    request<Record<string, unknown>>("/settings/trading/risk-snapshot"),
};

