export interface HealthResponse {
  status: string;
  version: string;
  ollama: {
    enabled: boolean;
    reachable: boolean;
    base_url: string;
    model_count: number;
  };
}

export interface ModelRegistryItem {
  id: string;
  provider: string;
  model: string;
  roles: string[];
  enabled: boolean;
  priority: number;
  resolved_model?: string | null;
  available?: boolean;
}

export interface DiscoveredModel {
  name: string;
  provider: string;
}

export interface ModelsResponse {
  registry: ModelRegistryItem[];
  discovered: DiscoveredModel[];
  ollama_available: boolean;
}

export interface ModelUsageItem {
  model_id: string;
  provider: string;
  model_name: string;
  request_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  last_used_at?: string | null;
  updated_at?: string | null;
}

export interface UsageResponse {
  items: ModelUsageItem[];
}

export interface ConfigResponse {
  application: Record<string, unknown>;
  research: Record<string, unknown>;
  discovery: Record<string, unknown>;
  discovery_score?: Record<string, number>;
  scoring: Record<string, unknown>;
  providers: Record<string, unknown>;
  models: ModelRegistryItem[];
}

export type ProgressStageStatus =
 | "complete"
 | "active"
 | "pending"
 | "error"
 | "skipped";

export interface ProgressStage {
  id: string;
  label: string;
  status: ProgressStageStatus;
  detail?: string;
}

export interface DiscoveryRunRequest {
  output_count: number;
  universe: string;
  market_cap: string;
  sector: string;
  risk_tolerance: string;
  time_horizon: string;
  investable_amount?: number;
  min_whole_shares?: number;
  exclude_seen?: boolean;
  candidate_pool_size?: number | null;
  screen_from_universe?: number | null;
  /** Keep searching until this many names clear both floors. */
  min_score?: number;
  min_panel_score?: number;
  /** invest = hold; daytrade = same-session; swing = 1-7d event-first. */
  lane?: "invest" | "daytrade" | "swing";
  hold_days?: number;
}

export interface DiscoveryRunCreated {
  run_id: string;
  status: string;
}

export interface CandidateSummary {
  ticker: string;
  score: number;
  confidence: number;
  signal: string;
  name?: string | null;
  sector?: string | null;
  price?: number | null;
  shares_buyable?: number | null;
  panel_score?: number | null;
  panel_spread?: number | null;
  meets_criteria?: boolean | null;
  miss_reason?: string | null;
}

export interface DiscoveryRunResponse {
  id: string;
  status: string;
  input: Record<string, unknown>;
  stages: ProgressStage[];
  candidates: CandidateSummary[];
  error?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
  researcher_available?: boolean | null;
  stats?: Record<string, unknown>;
  events?: RunEvent[];
}

export interface RunEvent {
  id: number;
  research_run_id: string;
  level: string;
  stage?: string | null;
  message: string;
  created_at: string;
}

export interface ScoreComponent {
  name: string;
  score: number;
  weight: number;
  raw_metrics?: Record<string, unknown>;
  method?: string;
  notes?: string[];
  weighted_contribution?: number;
}

export interface EvidenceItem {
  id: string;
  ticker: string;
  claim: string;
  source_name: string;
  source_url?: string | null;
  source_type: string;
  published_at?: string | null;
  retrieved_at: string;
  supporting_text?: string | null;
  data_points?: Record<string, unknown>;
  reliability?: number;
  freshness?: number;
  directness?: number;
  corroboration?: number;
}

export interface CandidateDetailResponse {
  ticker: string;
  score: number;
  confidence: number;
  signal: string;
  calculation: string;
  components: ScoreComponent[];
  evidence: EvidenceItem[];
  researcher_summary?: string | null;
  researcher?: Record<string, unknown> | null;
  name?: string | null;
  sector?: string | null;
  evidence_ids: string[];
  panel_score?: number | null;
  panel_spread?: number | null;
  agents?: AgentFinding[];
}

export interface AgentFinding {
  role?: string | null;
  model?: string | null;
  score?: number | null;
  confidence?: number | null;
  summary?: string | null;
  risks?: string[];
  evidence_ids?: string[];
  dimension_scores?: Record<string, number>;
}

export interface CandidateSighting {
  ticker: string;
  research_run_id: string;
  score?: number | null;
  signal?: string | null;
  price?: number | null;
  shares_buyable?: number | null;
  panel_score?: number | null;
  seen_at: string;
  name?: string | null;
  sector?: string | null;
  confidence?: number | null;
  rank?: number | null;
  in_output?: number | null;
  lane?: "invest" | "daytrade" | string | null;
}

export interface PaperPosition {
  id: string;
  ticker: string;
  shares: number;
  cost_basis: number;
  opened_at: string;
  closed_at?: string | null;
  status: string;
  source_run_id?: string | null;
  notes?: string | null;
  last_price?: number | null;
  market_value?: number | null;
  unrealized_pnl?: number | null;
  cost_total?: number | null;
  unrealized_pnl_pct?: number | null;
  name?: string | null;
  currency?: string | null;
  change?: number | null;
  change_pct?: number | null;
  previous_close?: number | null;
  day_open?: number | null;
  day_high?: number | null;
  day_low?: number | null;
  market_cap?: number | null;
  pe?: number | null;
  sector?: string | null;
  industry?: string | null;
  beta?: number | null;
  avg_volume?: number | null;
  fifty_two_week_high?: number | null;
  fifty_two_week_low?: number | null;
  score?: number | null;
  signal?: string | null;
  lane?: string | null;
  quote_as_of?: string | null;
}

export interface ChartBar {
  t: string;
  o?: number | null;
  h?: number | null;
  l?: number | null;
  c?: number | null;
  v?: number | null;
}

export interface ChartSnapshot {
  ticker: string;
  name?: string | null;
  currency?: string | null;
  range: string;
  period?: string;
  interval?: string;
  last?: number | null;
  previous_close?: number | null;
  day_open?: number | null;
  day_high?: number | null;
  day_low?: number | null;
  change?: number | null;
  change_pct?: number | null;
  range_open?: number | null;
  range_close?: number | null;
  range_change?: number | null;
  range_change_pct?: number | null;
  market_cap?: number | null;
  bars: ChartBar[];
  as_of?: string;
  stale?: boolean;
  source?: string;
}

export interface PortfolioStats {
  trading_mode: string;
  open_positions: number;
  closed_positions: number;
  invested_cost: number;
  market_value: number;
  unrealized_pnl: number;
  realized_closed: number;
  win_count?: number | null;
  avg_position_size?: number | null;
}

export interface SecretsStatus {
  trading_mode: string;
  live_trading_enabled: boolean;
  live_trading_confirmed?: boolean;
  paper_is_default: boolean;
  active_backend?: string;
  /** Echoed because it is not a secret. */
  ollama_base_url?: string | null;
  keys: Record<string, boolean>;
  notes: Record<string, string>;
  kill_switch?: {
    trading_disabled?: boolean;
    updated_at?: string | null;
    notes?: string | null;
    effect?: string;
  };
  market_session?: Record<string, unknown>;
  trading_config?: Record<string, unknown>;
}

export interface PortfolioMode {
  backend: string;
  is_paper: boolean;
  is_live: boolean;
  label: string;
}
