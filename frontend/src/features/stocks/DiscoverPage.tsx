import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  DataTable,
  EvidenceCard,
  ProgressStages,
  ScoreCard,
} from "@/components";
import { useDiscoveryRun } from "@/hooks/useDiscoveryRun";
import { useResearchLane } from "@/hooks/useResearchLane";
import { api, ApiError } from "@/lib/api";
import type { CandidateSummary } from "@/types/api";

const SCORE_MAX = 100;

const STAT_COPY: Record<string, { label: string; hint: string }> = {
  universe_loaded: {
    label: "Universe loaded",
    hint: "How many tickers were loaded for this run before skipping saved names.",
  },
  universe_size: {
    label: "Available this run",
    hint: "Tickers left after Skip previously found. This is a snapshot from that run, not live.",
  },
  excluded_seen: {
    label: "Skipped (this run)",
    hint: "Saved names skipped on that run for this lane. Clear that lane zeros its live skip list; this number stays as history until you run again.",
  },
  lane: {
    label: "Lane",
    hint: "invest = hold/swing archive; daytrade = same-session scalp archive.",
  },
  screened: {
    label: "Passed screen",
    hint: "Names that fit your budget, share minimum, and market-cap rules.",
  },
  scored: {
    label: "Scored",
    hint: "Names that got a full deterministic score this run (saved even if not ranked).",
  },
  output_count: {
    label: "Ranked results",
    hint: "How many top names are shown in the table below.",
  },
  investable_amount: {
    label: "Budget used",
    hint: "Dollar amount used to decide what is affordable.",
  },
  min_whole_shares: {
    label: "Min shares",
    hint: "A name must allow at least this many whole shares on the budget.",
  },
  reexamine: {
    label: "Reexamined",
    hint: "This run refreshed one saved ticker instead of scanning the universe.",
  },
  score: {
    label: "Score",
    hint: `Deterministic score for the reexamined ticker (0/${SCORE_MAX} to ${SCORE_MAX}/${SCORE_MAX}).`,
  },
  target_count: {
    label: "Target matches",
    hint: "How many names discovery was asked to find at the score/panel floors.",
  },
  min_score: {
    label: "Min score",
    hint: "Deterministic score floor used while searching.",
  },
  min_panel_score: {
    label: "Min panel",
    hint: "Panel score floor used while searching (0 means panel was not required).",
  },
  matched: {
    label: "Matched",
    hint: "How many names cleared the floors before the run stopped.",
  },
  batches: {
    label: "Batches",
    hint: "How many screening batches this run completed.",
  },
  tickers_tried: {
    label: "Tickers tried",
    hint: "How far into the available list this run got.",
  },
  cancelled: {
    label: "Stopped early",
    hint: "1 if you stopped the search before it finished.",
  },
};

const COLUMN_HINTS = [
  {
    title: "Score",
    body: `Deterministic 0/${SCORE_MAX} to ${SCORE_MAX}/${SCORE_MAX} from market metrics and evidence. This is what ranks the list and drives Signal.`,
  },
  {
    title: "Panel",
    body: `Median of three local LLM role scores (fundamental, skeptic, counsel), each 0/${SCORE_MAX} to ${SCORE_MAX}/${SCORE_MAX}. One harsh role cannot collapse the panel. Panel does not change rank - Signal still comes from Score.`,
  },
  {
    title: "Signal",
    body: "Final suggestion band from Score alone (Strong Interest >=80, Interesting >=65, Watch >=50, Cautious >=35, else Avoid / Defer).",
  },
  {
    title: "Shares @ budget",
    body: "Whole shares you can buy with the budget at the last observed price.",
  },
];

const DEFAULT_STAGES = [
  { id: "universe", label: "Universe", status: "pending" as const },
  { id: "screening", label: "Screening", status: "pending" as const },
  { id: "evidence", label: "Evidence", status: "pending" as const },
  { id: "research", label: "Research", status: "pending" as const },
  { id: "scoring", label: "Scoring", status: "pending" as const },
  { id: "counsel", label: "Counsel", status: "pending" as const },
];

function outOf100(value: number) {
  return `${value.toFixed(1)}/${SCORE_MAX}`;
}

function roleTitle(role?: string | null) {
  switch (role) {
    case "fundamental":
      return "Fundamental";
    case "skeptic":
      return "Skeptic";
    case "counsel":
      return "Counsel";
    default:
      return role || "Role";
  }
}

const COMPONENT_HELP: Record<string, string> = {
  fundamental_quality:
    "How strong earnings power looks versus peers (ROE and profit margin).",
  growth_quality:
    "How fast revenue is growing versus the screened peer set.",
  financial_health:
    "Balance-sheet safety: leverage (lower debt better) and liquidity (current ratio).",
  valuation:
    "How expensive the stock looks on PE versus peers (cheaper ranks higher).",
  momentum:
    "Recent price trend / strength versus peers over the lookback window.",
  catalysts:
    "Near-term news or event density that could move the name.",
  risk:
    "Penalty for volatility, beta, and other instability signals.",
  evidence_quality:
    "How solid and complete the evidence ledger is for this ticker.",
  affordability:
    "How well the name fits your budget (whole shares you can actually buy).",
};

function ComponentLabel({ name }: { name: string }) {
  const help = COMPONENT_HELP[name] ?? "Weighted piece of the deterministic score.";
  return (
    <span className="inline-flex items-center gap-1.5 text-ink-muted">
      {name.replaceAll("_", " ")}
      <span
        title={help}
        className="inline-flex size-3.5 cursor-help items-center justify-center rounded-full border border-border text-[9px] leading-none text-ink-subtle"
        aria-label={help}
      >
        i
      </span>
    </span>
  );
}

function roleHint(role?: string | null) {
  switch (role) {
    case "fundamental":
      return "Bullish or constructive read of the evidence.";
    case "skeptic":
      return "Risk-first challenge to the thesis.";
    case "counsel":
      return "Balanced synthesis across the other roles.";
    default:
      return "Local model opinion for this role.";
  }
}

export function DiscoverPage() {
  const [params] = useSearchParams();
  const { lane, setLane, syncFromRun } = useResearchLane();
  const [holdDays, setHoldDays] = useState(3);
  const [outputCount, setOutputCount] = useState(10);
  const [investableAmount, setInvestableAmount] = useState(100);
  const [minShares, setMinShares] = useState(5);
  const [risk, setRisk] = useState("Moderate");
  const [horizon, setHorizon] = useState("1-3 years");
  const [excludeSeen, setExcludeSeen] = useState(true);
  const [minScore, setMinScore] = useState(0);
  const [minPanelScore, setMinPanelScore] = useState(0);
  const [clearNote, setClearNote] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const [savedForSkip, setSavedForSkip] = useState<number | null>(null);
  const [universeCount, setUniverseCount] = useState<number | null>(null);
  const [refreshingUniverse, setRefreshingUniverse] = useState(false);
  const {
    run,
    detail,
    selectedTicker,
    error,
    starting,
    running,
    restored,
    start,
    selectTicker,
    cancel,
  } = useDiscoveryRun(600, params.get("run"));

  const refreshSkipAndUniverse = useCallback(async () => {
    try {
      const [history, universe] = await Promise.all([
        api.candidateHistory(lane),
        api.discoveryUniverse(),
      ]);
      setSavedForSkip(history.known_tickers?.length ?? history.count ?? 0);
      setUniverseCount(universe.ticker_count);
    } catch {
      // Keep prior values if status fetch fails.
    }
  }, [lane]);

  useEffect(() => {
    void refreshSkipAndUniverse();
  }, [refreshSkipAndUniverse, run?.status]);

  // While a discovery run is live, keep both pages on that run's lane.
  useEffect(() => {
    if (run?.status !== "running") return;
    const runLane = (run.input as { lane?: unknown } | undefined)?.lane;
    syncFromRun(runLane);
  }, [run?.id, run?.status, run?.input, syncFromRun]);

  async function clearSavedStocks() {
    if (running || clearing) return;
    const laneLabel =
      lane === "daytrade" ? "day trade" : lane === "swing" ? "swing" : "invest";
    const ok = window.confirm(
      `Clear saved ${laneLabel} stocks and local LLM research cache?\n\nThis only clears the ${laneLabel} archive. The other lane stays intact.`,
    );
    if (!ok) return;
    setClearing(true);
    setClearNote(null);
    try {
      const result = await api.clearCandidateHistory(lane);
      setSavedForSkip(result.stocks_remaining ?? 0);
      setClearNote(
        `Cleared ${result.stocks_cleared ?? 0} ${laneLabel} stocks` +
          (result.llm_cache_cleared
            ? ` and ${result.llm_cache_cleared} cached model responses. `
            : ". ") +
          "Next run in this lane will skip 0 previously saved.",
      );
      await refreshSkipAndUniverse();
    } catch (err) {
      setClearNote(
        err instanceof ApiError ? err.message : "Could not clear saved stocks",
      );
    } finally {
      setClearing(false);
    }
  }

  async function refreshStockUniverse() {
    if (running || refreshingUniverse) return;
    setRefreshingUniverse(true);
    setClearNote(null);
    try {
      const result = await api.refreshDiscoveryUniverse();
      setUniverseCount(result.ticker_count);
      setClearNote(
        `Stock universe refreshed: ${result.ticker_count.toLocaleString()} active US symbols from free Nasdaq lists (plus curated).`,
      );
    } catch (err) {
      setClearNote(
        err instanceof ApiError
          ? err.message
          : "Could not refresh stock universe",
      );
    } finally {
      setRefreshingUniverse(false);
    }
  }

  const maxPrice =
    investableAmount > 0 && minShares > 0
      ? investableAmount / minShares
      : null;

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">
          Stock Discovery
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-muted">
          Two lanes stay separate: Invest (hold/swing) and Day trade
          (same-session scalps). Scores are deterministic from evidence and
          market metrics. Every scored name is saved under Found stocks in its
          own lane.
        </p>
        {restored && run ? (
          <p className="mt-2 text-xs text-ink-subtle">
            Showing saved run {run.id}
            {run.created_at
              ? ` from ${new Date(
                  run.created_at.includes("T")
                    ? run.created_at
                    : `${run.created_at.replace(" ", "T")}Z`,
                ).toLocaleString()}`
              : ""}
            . Leaving this page does not delete it. Stats below are from that
            run; live skip/universe counts are above the form.
          </p>
        ) : null}
      </header>

      <section className="flex flex-wrap items-center gap-3 border border-border bg-surface-raised/70 px-4 py-3 text-sm">
        <p className="text-ink-muted">
          Live skip list:{" "}
          <span className="font-mono text-ink">
            {savedForSkip == null ? "..." : savedForSkip}
          </span>{" "}
          saved{" "}
          {lane === "daytrade"
            ? "daytrade"
            : lane === "swing"
              ? "swing"
              : "invest"}{" "}
          stock
          {savedForSkip === 1 ? "" : "s"}
        </p>
        <span className="text-ink-subtle"> | </span>
        <p className="text-ink-muted">
          Stock universe:{" "}
          <span className="font-mono text-ink">
            {universeCount == null ? "..." : universeCount.toLocaleString()}
          </span>{" "}
          tickers
        </p>
        <button
          type="button"
          disabled={running || refreshingUniverse}
          onClick={() => void refreshStockUniverse()}
          className="border border-border px-3 py-1.5 text-xs text-ink-muted hover:bg-surface-muted disabled:opacity-50"
          title="Download free Nasdaq/NYSE active symbol lists (no API key)"
        >
          {refreshingUniverse ? "Refreshing..." : "Refresh stock universe"}
        </button>
      </section>

      <section className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={running}
          onClick={() => setLane("invest")}
          className={
            lane === "invest"
              ? "border border-accent bg-accent px-4 py-2 text-sm text-accent-fg"
              : "border border-border px-4 py-2 text-sm text-ink-muted hover:bg-surface-muted"
          }
        >
          Invest / hold
        </button>
        <button
          type="button"
          disabled={running}
          onClick={() => setLane("swing")}
          className={
            lane === "swing"
              ? "border border-accent bg-accent px-4 py-2 text-sm text-accent-fg"
              : "border border-border px-4 py-2 text-sm text-ink-muted hover:bg-surface-muted"
          }
        >
          Swing 1-7d
        </button>
        <button
          type="button"
          disabled={running}
          onClick={() => setLane("daytrade")}
          className={
            lane === "daytrade"
              ? "border border-accent bg-accent px-4 py-2 text-sm text-accent-fg"
              : "border border-border px-4 py-2 text-sm text-ink-muted hover:bg-surface-muted"
          }
        >
          Day trade
        </button>
        <p className="w-full text-xs text-ink-muted sm:w-auto sm:self-center">
          {lane === "daytrade"
            ? "Same-session candidates: momentum, liquidity, tradable volatility. Risk/horizon locked."
            : lane === "swing"
              ? "Event-first: scan catalysts/news, then map to tickers likely to move within your hold window. Uses settled buying power awareness and skips wash-blocked names."
              : "Multi-day / hold ideas with your risk and horizon settings."}
        </p>
      </section>

      <section className="grid gap-4 border border-border bg-surface-raised/80 p-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        <label className="space-y-1.5 text-sm">
          <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
            Budget USD
          </span>
          <input
            type="number"
            min={10}
            max={100000}
            step={10}
            value={investableAmount}
            onChange={(e) => setInvestableAmount(Number(e.target.value) || 100)}
            className="w-full border border-border bg-surface px-3 py-2 text-ink"
            disabled={running}
          />
        </label>
        <label className="space-y-1.5 text-sm">
          <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
            Min shares
          </span>
          <input
            type="number"
            min={1}
            max={100}
            value={minShares}
            onChange={(e) => setMinShares(Number(e.target.value) || 5)}
            className="w-full border border-border bg-surface px-3 py-2 text-ink"
            disabled={running}
          />
        </label>
        <label className="space-y-1.5 text-sm">
          <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
            Find this many
          </span>
          <input
            type="number"
            min={1}
            max={25}
            value={outputCount}
            onChange={(e) => setOutputCount(Number(e.target.value) || 10)}
            className="w-full border border-border bg-surface px-3 py-2 text-ink"
            disabled={running}
          />
          <span className="block text-[11px] text-ink-subtle">
            Target count. With floors below, discovery keeps searching until it
            finds this many matches (or the universe runs out).
          </span>
        </label>
        <label className="space-y-1.5 text-sm">
          <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
            Universe
          </span>
          <select
            className="w-full border border-border bg-surface px-3 py-2 text-ink"
            disabled
            value="US Discovery"
          >
            <option>US Discovery</option>
          </select>
          <span className="block text-[11px] text-ink-subtle">
            {universeCount != null
              ? `${universeCount.toLocaleString()} local tickers. Use Refresh stock universe for the full free Nasdaq list.`
              : "Local US ticker list."}
          </span>
        </label>
        {lane === "swing" ? (
          <label className="space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Hold days (1-7)
            </span>
            <input
              type="number"
              min={1}
              max={7}
              value={holdDays}
              onChange={(e) =>
                setHoldDays(Math.max(1, Math.min(7, Number(e.target.value) || 3)))
              }
              className="w-full border border-border bg-surface px-3 py-2 text-ink"
              disabled={running}
            />
            <span className="block text-[11px] text-ink-subtle">
              Target window to be ready to sell for profit after entry.
            </span>
          </label>
        ) : null}
        {lane === "invest" ? (
          <>
            <label className="space-y-1.5 text-sm">
              <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
                Risk
              </span>
              <select
                value={risk}
                onChange={(e) => setRisk(e.target.value)}
                className="w-full border border-border bg-surface px-3 py-2 text-ink"
                disabled={running}
              >
                <option>Conservative</option>
                <option>Moderate</option>
                <option>Aggressive</option>
              </select>
            </label>
            <label className="space-y-1.5 text-sm">
              <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
                Horizon
              </span>
              <select
                value={horizon}
                onChange={(e) => setHorizon(e.target.value)}
                className="w-full border border-border bg-surface px-3 py-2 text-ink"
                disabled={running}
              >
                <option>Under 1 year</option>
                <option>1-3 years</option>
                <option>3-5 years</option>
                <option>5+ years</option>
              </select>
            </label>
          </>
        ) : (
          <div className="sm:col-span-2 space-y-1.5 border border-border bg-surface-muted/30 px-3 py-2 text-xs text-ink-muted">
            <p className="text-[10px] uppercase tracking-[0.14em] text-ink-subtle">
              Daytrade locks
            </p>
            <p>
              Risk = Aggressive | Horizon = Intraday (not editable). Scoring
              weights shift toward momentum, catalysts, and tradable volatility;
              liquidity floor is higher so you can get in and out the same day.
            </p>
          </div>
        )}
        <label className="space-y-1.5 text-sm">
          <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
            Min score /100
          </span>
          <input
            type="number"
            min={0}
            max={100}
            step={1}
            value={minScore}
            onChange={(e) => setMinScore(Math.max(0, Number(e.target.value) || 0))}
            className="w-full border border-border bg-surface px-3 py-2 text-ink"
            disabled={running}
          />
          <span className="block text-[11px] text-ink-subtle">
            0 = off (rank by score). Raise only as a filter after ranking the
            best deterministic scores - discovery does not aim for the floor.
          </span>
        </label>
        <label className="space-y-1.5 text-sm">
          <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
            Min panel /100
          </span>
          <input
            type="number"
            min={0}
            max={100}
            step={1}
            value={minPanelScore}
            onChange={(e) =>
              setMinPanelScore(Math.max(0, Number(e.target.value) || 0))
            }
            className="w-full border border-border bg-surface px-3 py-2 text-ink"
            disabled={running}
          />
          <span className="block text-[11px] text-ink-subtle">
            0 = off. Raise to require panel agreement after ranking. Needs
            Ollama. Panel is a median of roles so one harsh skeptic cannot zero
            it out.
          </span>
        </label>
        {(minScore > 0 || minPanelScore > 0) ? (
          <div className="sm:col-span-2 lg:col-span-3 xl:col-span-4 border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-ink">
            Floors filter each batch: screen a small slice, analyze the affordable
            names, keep matches that clear your floors, and stop once{" "}
            {outputCount} matches land. No full-universe bake-off. Hit Stop anytime.
          </div>
        ) : (
          <div className="sm:col-span-2 lg:col-span-3 xl:col-span-4 border border-border bg-surface-muted/40 px-3 py-2 text-xs text-ink-muted">
            No floors set. Discovery still works in small batches and stops after{" "}
            {outputCount} analyzed names - hit Stop earlier if you already have
            enough to work with.
          </div>
        )}
        <div className="sm:col-span-2 lg:col-span-3 xl:col-span-4 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-ink-muted">
            <input
              type="checkbox"
              checked={excludeSeen}
              onChange={(e) => setExcludeSeen(e.target.checked)}
              disabled={running}
            />
            Skip previously found tickers
            {savedForSkip != null ? (
              <span className="text-xs text-ink-subtle">
                ({savedForSkip} in {lane === "daytrade" ? "daytrade" : "invest"}{" "}
                lane)
              </span>
            ) : null}
          </label>
          <button
            type="button"
            disabled={running || clearing}
            onClick={() => void clearSavedStocks()}
            className="border border-border px-3 py-2 text-xs text-ink-muted hover:bg-surface-muted disabled:opacity-50"
            title="Wipe found-stock history and LLM cache so discovery can see every ticker again"
          >
            {clearing
              ? "Clearing..."
              : lane === "daytrade"
                ? "Clear daytrade saves"
                : lane === "swing"
                  ? "Clear swing saves"
                  : "Clear invest saves"}
          </button>
          {clearNote ? (
            <span className="text-xs text-ink-subtle">{clearNote}</span>
          ) : null}
          <button
            type="button"
            disabled={running}
            onClick={() =>
              void start({
                output_count: outputCount,
                universe: "US Discovery",
                market_cap: "Mid/Small",
                sector: "Any",
                risk_tolerance:
                  lane === "daytrade" || lane === "swing" ? "Aggressive" : risk,
                time_horizon:
                  lane === "daytrade"
                    ? "Intraday"
                    : lane === "swing"
                      ? `${holdDays}-day swing`
                      : horizon,
                investable_amount: investableAmount,
                min_whole_shares: minShares,
                exclude_seen: excludeSeen,
                min_score: minScore,
                min_panel_score: minPanelScore,
                lane,
                hold_days: holdDays,
              })
            }
            className="border border-accent bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-50"
          >
            {starting || running ? "Running discovery..." : "Run discovery"}
          </button>
          {running ? (
            <button
              type="button"
              onClick={() => void cancel()}
              className="border border-danger/50 px-4 py-2 text-sm text-danger hover:bg-danger/10"
            >
              Stop search
            </button>
          ) : null}
          <a
            href={api.exportCandidatesUrl("csv")}
            className="text-xs text-accent hover:underline"
          >
            Export CSV
          </a>
          <a
            href={api.exportCandidatesUrl("json")}
            className="text-xs text-accent hover:underline"
          >
            Export JSON
          </a>
          {maxPrice != null ? (
            <p className="text-xs text-ink-subtle">
              Max price ~ ${maxPrice.toFixed(2)} for {minShares}+ shares on $
              {investableAmount}. Caps &gt; $40B excluded.
            </p>
          ) : null}
        </div>
      </section>

      {error ? (
        <div className="border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-ink">
          {error}
        </div>
      ) : null}

      {run?.stats && Object.keys(run.stats).length > 0 ? (
        <section className="space-y-2">
          {restored && !running ? (
            <p className="text-[11px] text-ink-subtle">
              Run snapshot only. Live skip list is{" "}
              <span className="font-mono">{savedForSkip ?? 0}</span> right now
              {savedForSkip === 0
                ? " (clear worked; next discovery skips nothing)."
                : "."}
            </p>
          ) : null}
          <div className="grid gap-3 border border-border bg-surface-raised/70 p-4 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(run.stats).map(([key, value]) => {
              const copy = STAT_COPY[key] ?? {
                label: key.replaceAll("_", " "),
                hint: "Run statistic from this discovery pass.",
              };
              return (
                <div key={key}>
                  <p className="text-[10px] uppercase tracking-[0.14em] text-ink-subtle">
                    {copy.label}
                  </p>
                  <p className="mt-1 font-mono text-sm text-ink">
                    {String(value)}
                  </p>
                  <p className="mt-1 text-[11px] leading-snug text-ink-subtle">
                    {copy.hint}
                  </p>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      <section className="grid gap-3 border border-border bg-surface-raised/60 p-4 sm:grid-cols-2 lg:grid-cols-4">
        {COLUMN_HINTS.map((item) => (
          <div key={item.title}>
            <p className="text-[10px] uppercase tracking-[0.14em] text-ink-subtle">
              {item.title}
            </p>
            <p className="mt-1 text-[11px] leading-snug text-ink-muted">
              {item.body}
            </p>
          </div>
        ))}
      </section>

      <section className="border border-border bg-surface-raised/80 p-3">
        <h2 className="mb-2 text-[10px] uppercase tracking-[0.16em] text-ink-subtle">
          Progress
        </h2>
        <ProgressStages
          horizontal
          stages={run?.stages?.length ? run.stages : DEFAULT_STAGES}
        />
      </section>

      {run?.events?.length ? (
        <section className="border border-border bg-surface-raised/70 p-4">
          <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
            <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
              Run log
            </h2>
            <p className="text-[11px] text-ink-subtle">
              Showing latest {Math.min(run.events.length, 100)}
              {running
                ? " | live while discovery works (refreshes ~every 0.6s)"
                : ""}
            </p>
          </div>
          {running ? (
            <p className="mb-2 text-[11px] text-ink-muted">
              Screening logs every few tickers; research and panel log each name
              with timing so you can gauge wait. Newest at the top.
            </p>
          ) : null}
          <ol className="max-h-[28rem] space-y-1 overflow-auto font-mono text-[11px] text-ink-muted">
            {[...run.events].slice(-100).reverse().map((event) => (
              <li
                key={event.id}
                className={
                  event.level === "warning" ? "text-warning" : undefined
                }
              >
                <span className="text-ink-subtle">
                  [{event.stage ?? "-"}]
                </span>{" "}
                {event.message}
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.9fr)]">
        <section className="min-w-0 space-y-3">
          <div>
            <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
              Candidates
            </h2>
            <p className="mt-1 text-[11px] text-ink-subtle">
              Matches appear first. Names below your floors stay listed and are
              marked so you can stop early if nothing is clearing the bar.
            </p>
          </div>
          <DataTable<CandidateSummary>
            columns={[
              {
                key: "ticker",
                header: "Ticker",
                className: "font-mono font-medium",
                render: (row) => (
                  <Link
                    to={`/stocks/view/${encodeURIComponent(row.ticker)}`}
                    className="text-accent hover:underline"
                    onClick={(event) => event.stopPropagation()}
                  >
                    {row.ticker}
                  </Link>
                ),
              },
              {
                key: "price",
                header: "Price",
                className: "font-mono",
                render: (row) =>
                  row.price != null ? `$${row.price.toFixed(2)}` : "-",
              },
              {
                key: "shares",
                header: "Shares",
                className: "font-mono",
                render: (row) =>
                  row.shares_buyable != null ? String(row.shares_buyable) : "-",
              },
              {
                key: "score",
                header: "Score",
                className: "font-mono",
                render: (row) => outOf100(row.score),
              },
              {
                key: "panel",
                header: "Panel",
                className: "font-mono",
                render: (row) =>
                  row.panel_score != null ? outOf100(row.panel_score) : "-",
              },
              {
                key: "signal",
                header: "Signal",
                render: (row) => row.signal,
              },
              {
                key: "criteria",
                header: "Criteria",
                render: (row) =>
                  row.meets_criteria === false ? (
                    <span
                      className="text-xs text-warning"
                      title={row.miss_reason ?? "Below floors"}
                    >
                      Below
                    </span>
                  ) : row.meets_criteria === true &&
                    (minScore > 0 || minPanelScore > 0) ? (
                    <span className="text-xs text-success">Match</span>
                  ) : (
                    "-"
                  ),
              },
            ]}
            rows={run?.candidates ?? []}
            getRowId={(row) => row.ticker}
            onRowClick={(row) => void selectTicker(row.ticker)}
            emptyMessage={
              running
                ? "Discovery in progress - matches and below-criteria names will appear here..."
                : "No results yet. Start a discovery run."
            }
          />
          {run?.candidates?.some((row) => row.meets_criteria === false) ? (
            <p className="text-[11px] text-ink-subtle">
              Hover <span className="text-warning">Below</span> for why a name
              missed your floors. You can still open it for components and
              evidence.
            </p>
          ) : null}
        </section>

        <aside className="space-y-4 self-start lg:sticky lg:top-4">
          <ScoreCard
            ticker={detail?.ticker ?? selectedTicker ?? undefined}
            score={detail?.score}
            confidence={detail?.confidence}
            signal={detail?.signal}
            panelScore={detail?.panel_score}
            panelSpread={detail?.panel_spread}
            emptyMessage="Select a candidate to inspect score components."
          />
          {detail ? (
            <div className="border border-border bg-surface-raised/80 p-4">
                <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
                <div>
                  <h3 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
                    Score components
                  </h3>
                  <p className="mt-1 text-[11px] text-ink-subtle">
                    Each piece is also 0/{SCORE_MAX} to {SCORE_MAX}/{SCORE_MAX},
                    then weighted into Score.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Link
                    to={`/stocks/view/${encodeURIComponent(detail.ticker)}`}
                    className="border border-border px-3 py-1.5 text-xs text-ink hover:bg-surface-muted"
                  >
                    Chart
                  </Link>
                  <Link
                    to={`/stocks/trade?ticker=${encodeURIComponent(detail.ticker)}&price=${
                      run?.candidates.find((c) => c.ticker === detail.ticker)?.price ??
                      ""
                    }&run=${encodeURIComponent(run?.id ?? "")}`}
                    className="border border-border px-3 py-1.5 text-xs text-ink hover:bg-surface-muted"
                  >
                    Trade this stock
                  </Link>
                </div>
              </div>
              <ul className="space-y-2">
                {detail.components.map((c) => (
                  <li
                    key={c.name}
                    className="flex items-baseline justify-between gap-3 border-b border-border/70 pb-1.5 text-sm"
                  >
                    <span className="text-ink-muted">
                      <ComponentLabel name={c.name} />
                    </span>
                    <span className="shrink-0 font-mono text-ink">
                      {outOf100(c.score)}
                      <span className="text-ink-subtle">
                        {" "}
                        x {c.weight.toFixed(2)}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </aside>
      </div>

      {detail ? (
        <section className="space-y-3">
          <div>
            <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
              Counsel panel for {detail.ticker}
            </h2>
            <p className="mt-1 max-w-3xl text-[11px] text-ink-subtle">
              Role scores are also 0/{SCORE_MAX} to {SCORE_MAX}/{SCORE_MAX}.
              Their median is Panel (so one extreme role cannot dominate). They
              are second opinions; Signal still comes only from the
              deterministic Score.
            </p>
          </div>
          {detail.researcher_summary ? (
            <div className="border border-border bg-surface-raised/70 p-4">
              <p className="text-[10px] uppercase tracking-[0.14em] text-ink-subtle">
                Researcher summary
              </p>
              <p className="mt-2 text-sm leading-relaxed text-ink-muted">
                {detail.researcher_summary}
              </p>
            </div>
          ) : null}
          {detail.agents?.length ? (
            <div className="grid gap-3 md:grid-cols-3">
              {detail.agents.map((agent) => (
                <article
                  key={`${agent.role}-${agent.model}`}
                  className="border border-border bg-surface-raised/80 p-4"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <h3 className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
                      {roleTitle(agent.role)}
                    </h3>
                    <span className="font-mono text-sm text-ink">
                      {agent.score != null ? outOf100(agent.score) : "-"}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-ink-subtle">
                    {roleHint(agent.role)}
                  </p>
                  {agent.summary ? (
                    <p className="mt-3 text-sm leading-relaxed text-ink-muted">
                      {agent.summary}
                    </p>
                  ) : (
                    <p className="mt-3 text-sm text-ink-subtle">No summary.</p>
                  )}
                  {agent.risks?.length ? (
                    <ul className="mt-3 space-y-1 text-[11px] text-ink-subtle">
                      {agent.risks.slice(0, 4).map((riskItem) => (
                        <li key={riskItem}>- {riskItem}</li>
                      ))}
                    </ul>
                  ) : null}
                </article>
              ))}
            </div>
          ) : (
            <p className="text-sm text-ink-subtle">
              No panel opinions yet for this name (Ollama may have been offline).
            </p>
          )}
        </section>
      ) : null}

      {detail?.evidence?.length ? (
        <section className="space-y-3">
          <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
            Evidence for {detail.ticker}
          </h2>
          <div className="grid gap-3 md:grid-cols-2">
            {detail.evidence.map((item) => (
              <EvidenceCard
                key={item.id}
                id={item.id}
                claim={item.claim}
                sourceName={item.source_name}
                sourceType={item.source_type}
                sourceUrl={item.source_url}
                publishedAt={item.published_at}
                reliability={item.reliability}
                supportingData={
                  item.data_points
                    ? Object.fromEntries(
                        Object.entries(item.data_points).map(([k, v]) => [
                          k,
                          typeof v === "number" || typeof v === "string"
                            ? v
                            : JSON.stringify(v),
                        ]),
                      )
                    : undefined
                }
              />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
