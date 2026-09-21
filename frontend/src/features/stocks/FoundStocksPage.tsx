import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { DataTable, ProgressStages } from "@/components";
import { useResearchLane } from "@/hooks/useResearchLane";
import { api, ApiError } from "@/lib/api";
import {
  SIGNAL_ORDER,
  compareSignals,
  orderedSignalOptions,
} from "@/lib/signals";
import type { CandidateSighting, ProgressStage } from "@/types/api";
import { normalizeLane, type ResearchLane } from "@/lib/lane";
import { cn } from "@/lib/cn";

type SortKey =
 | "seen_at"
 | "ticker"
 | "score"
 | "panel_score"
 | "price"
 | "signal"
 | "name";

type SortDir = "asc" | "desc";
type ListFilter = "all" | "ranked" | "scored";
type QueueStatus = "queued" | "running" | "done" | "error" | "cancelled";

type QueueItem = {
  ticker: string;
  status: QueueStatus;
  runId?: string;
  error?: string;
};

function formatWhen(value: string) {
  const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function seenAtMs(value: string) {
  const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const ms = Date.parse(normalized);
  return Number.isNaN(ms) ? 0 : ms;
}

function compareNullable(
  a: number | null | undefined,
  b: number | null | undefined,
  dir: SortDir,
) {
  const av = a == null || Number.isNaN(a) ? null : a;
  const bv = b == null || Number.isNaN(b) ? null : b;
  if (av == null && bv == null) return 0;
  if (av == null) return 1;
  if (bv == null) return -1;
  return dir === "asc" ? av - bv : bv - av;
}

const EMPTY_STAGES: ProgressStage[] = [
  { id: "load", label: "Load", status: "pending" },
  { id: "evidence", label: "Evidence", status: "pending" },
  { id: "research", label: "Research", status: "pending" },
  { id: "scoring", label: "Scoring", status: "pending" },
  { id: "counsel", label: "Counsel", status: "pending" },
];

export function FoundStocksPage() {
  const navigate = useNavigate();
  const { lane, setLane } = useResearchLane();
  const [rows, setRows] = useState<CandidateSighting[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [note, setNote] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);

  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [reexamineStages, setReexamineStages] =
    useState<ProgressStage[]>(EMPTY_STAGES);
  const [reexamineLog, setReexamineLog] = useState<string | null>(null);
  const processingRef = useRef(false);
  const stopQueueRef = useRef(false);

  const [query, setQuery] = useState("");
  const [signalFilter, setSignalFilter] = useState("all");
  const [listFilter, setListFilter] = useState<ListFilter>("all");
  const [sectorFilter, setSectorFilter] = useState("all");
  const [minScore, setMinScore] = useState(0);
  const [minPanel, setMinPanel] = useState(0);
  const [sortKey, setSortKey] = useState<SortKey>("seen_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const [batchSignals, setBatchSignals] = useState<string[]>([]);
  const [batchMinScore, setBatchMinScore] = useState(0);
  const [batchMaxScore, setBatchMaxScore] = useState(100);
  const [batchBeforeDate, setBatchBeforeDate] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.candidateHistory(lane);
      setRows(data.items);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load found stocks");
    } finally {
      setLoading(false);
    }
  }, [lane]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Mirror a live discovery run's lane even if we open Found first.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const latest = await api.latestDiscovery();
        if (cancelled || latest?.status !== "running") return;
        const runLane = normalizeLane(
          (latest.input as { lane?: unknown } | undefined)?.lane,
        );
        if (runLane) setLane(runLane);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [setLane]);

  const signalOptions = useMemo(() => {
    const present: string[] = [];
    for (const row of rows) {
      if (row.signal) present.push(row.signal);
    }
    return orderedSignalOptions(present);
  }, [rows]);

  const batchSignalChoices = useMemo(() => {
    const present = new Set(
      rows.map((r) => r.signal).filter((s): s is string => Boolean(s)),
    );
    const ordered = SIGNAL_ORDER.filter((s) => present.has(s));
    const extras = Array.from(present)
      .filter((s) => !(SIGNAL_ORDER as readonly string[]).includes(s))
      .sort((a, b) => a.localeCompare(b));
    return [...ordered, ...extras];
  }, [rows]);

  const sectorOptions = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows) {
      if (row.sector) set.add(row.sector);
    }
    return ["all", ...Array.from(set).sort((a, b) => a.localeCompare(b))];
  }, [rows]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = rows.filter((row) => {
      if (q) {
        const hay = `${row.ticker} ${row.name ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (signalFilter !== "all" && (row.signal || "") !== signalFilter) {
        return false;
      }
      if (listFilter === "ranked" && !row.in_output) return false;
      if (listFilter === "scored" && row.in_output) return false;
      if (sectorFilter !== "all" && (row.sector || "") !== sectorFilter) {
        return false;
      }
      if (minScore > 0 && (row.score ?? -1) < minScore) return false;
      if (minPanel > 0 && (row.panel_score ?? -1) < minPanel) return false;
      return true;
    });

    const sorted = [...filtered].sort((a, b) => {
      if (sortKey === "seen_at") {
        const diff = seenAtMs(a.seen_at) - seenAtMs(b.seen_at);
        return sortDir === "asc" ? diff : -diff;
      }
      if (sortKey === "signal") {
        return compareSignals(a.signal, b.signal, sortDir);
      }
      if (sortKey === "ticker" || sortKey === "name") {
        const av = String(a[sortKey] ?? "").toLowerCase();
        const bv = String(b[sortKey] ?? "").toLowerCase();
        const cmp = av.localeCompare(bv);
        return sortDir === "asc" ? cmp : -cmp;
      }
      return compareNullable(a[sortKey], b[sortKey], sortDir);
    });
    return sorted;
  }, [
    rows,
    query,
    signalFilter,
    listFilter,
    sectorFilter,
    minScore,
    minPanel,
    sortKey,
    sortDir,
  ]);

  const filtersActive =
    query.trim() !== "" ||
    signalFilter !== "all" ||
    listFilter !== "all" ||
    sectorFilter !== "all" ||
    minScore > 0 ||
    minPanel > 0 ||
    sortKey !== "seen_at" ||
    sortDir !== "desc";

  const queueCounts = useMemo(() => {
    const counts = { queued: 0, running: 0, done: 0, error: 0, cancelled: 0 };
    for (const item of queue) counts[item.status] += 1;
    return counts;
  }, [queue]);

  const activeItem = queue.find((item) => item.status === "running") ?? null;
  const queueBusy = queueCounts.queued > 0 || queueCounts.running > 0;

  function resetControls() {
    setQuery("");
    setSignalFilter("all");
    setListFilter("all");
    setSectorFilter("all");
    setMinScore(0);
    setMinPanel(0);
    setSortKey("seen_at");
    setSortDir("desc");
  }

  function switchLane(next: ResearchLane) {
    if (queueBusy) {
      setError("Finish or clear the reexamine queue before switching lanes.");
      return;
    }
    setLane(next);
    resetControls();
    setBatchSignals([]);
    setBatchMinScore(0);
    setBatchMaxScore(100);
    setBatchBeforeDate("");
    setNote(null);
    setError(null);
  }

  function enqueueTickers(tickers: string[]) {
    const cleaned = [
      ...new Set(tickers.map((t) => t.toUpperCase().trim()).filter(Boolean)),
    ];
    if (!cleaned.length) return;
    stopQueueRef.current = false;
    setQueue((prev) => {
      const blocked = new Set(
        prev
          .filter((item) => item.status === "queued" || item.status === "running")
          .map((item) => item.ticker),
      );
      const add = cleaned
        .filter((ticker) => !blocked.has(ticker))
        .map((ticker) => ({ ticker, status: "queued" as const }));
      if (!add.length) return prev;
      setNote(`Queued ${add.length} ticker${add.length === 1 ? "" : "s"} for reexamine.`);
      return [...prev, ...add];
    });
    setError(null);
  }

  function enqueueOne(row: CandidateSighting) {
    enqueueTickers([row.ticker]);
  }

  function queueMatchingBatch() {
    const beforeMs = batchBeforeDate
      ? Date.parse(`${batchBeforeDate}T23:59:59`)
      : null;
    const matched = rows.filter((row) => {
      if (batchSignals.length && !batchSignals.includes(row.signal || "")) {
        return false;
      }
      const score = row.score ?? -1;
      if (score < batchMinScore || score > batchMaxScore) return false;
      if (beforeMs != null && !Number.isNaN(beforeMs)) {
        if (seenAtMs(row.seen_at) > beforeMs) return false;
      }
      return true;
    });
    if (!matched.length) {
      setError("No saved stocks match that batch selection.");
      return;
    }
    const ok = window.confirm(
      `Queue ${matched.length} ticker${matched.length === 1 ? "" : "s"} for reexamine in the ${lane} lane?`,
    );
    if (!ok) return;
    enqueueTickers(matched.map((row) => row.ticker));
  }

  function queueVisible() {
    if (!visible.length) {
      setError("Nothing in the current table view to queue.");
      return;
    }
    const ok = window.confirm(
      `Queue all ${visible.length} visible ticker${visible.length === 1 ? "" : "s"}?`,
    );
    if (!ok) return;
    enqueueTickers(visible.map((row) => row.ticker));
  }

  function clearFinishedQueue() {
    setQueue((prev) =>
      prev.filter(
        (item) => item.status === "queued" || item.status === "running",
      ),
    );
  }

  function clearEntireQueue() {
    stopQueueRef.current = true;
    setQueue([]);
    setReexamineLog(null);
    setReexamineStages(EMPTY_STAGES);
    setNote("Reexamine queue cleared.");
  }

  function cancelRemaining() {
    stopQueueRef.current = true;
    setQueue((prev) =>
      prev.map((item) =>
        item.status === "queued"
          ? { ...item, status: "cancelled" as const }
          : item,
      ),
    );
    setNote("Cancelled remaining queued reexamines. Current run finishes.");
  }

  useEffect(() => {
    if (processingRef.current) return;
    const next = queue.find((item) => item.status === "queued");
    if (!next) return;
    if (stopQueueRef.current) {
      stopQueueRef.current = false;
      return;
    }

    processingRef.current = true;
    const ticker = next.ticker;

    void (async () => {
      setQueue((prev) =>
        prev.map((item) =>
          item.ticker === ticker && item.status === "queued"
            ? { ...item, status: "running" }
            : item,
        ),
      );
      setReexamineStages(EMPTY_STAGES);
      setReexamineLog(`Starting reexamine for ${ticker}...`);
      setNote(`Reexamining ${ticker} (fresh research + panel)...`);
      try {
        const created = await api.reexamine(ticker, lane);
        setQueue((prev) =>
          prev.map((item) =>
            item.ticker === ticker && item.status === "running"
              ? { ...item, runId: created.run_id }
              : item,
          ),
        );
        let failed = false;
        let failMsg = "";
        for (let attempt = 0; attempt < 180; attempt += 1) {
          const run = await api.getDiscoveryRun(created.run_id);
          if (run.stages?.length) setReexamineStages(run.stages);
          const events = run.events ?? [];
          if (events.length) {
            const latest = events[events.length - 1];
            setReexamineLog(
              `[${latest.stage ?? "-"}] ${latest.message ?? ""}`.trim(),
            );
          }
          if (run.status === "complete" || run.status === "error") {
            if (run.status === "error") {
              failed = true;
              failMsg = run.error || `Reexamine failed for ${ticker}`;
            } else {
              const panel = run.candidates?.[0]?.panel_score;
              setNote(
                `${ticker} reexamined` +
                  (panel != null ? ` | panel ${panel.toFixed(1)}/100` : "") +
                  ".",
              );
              setReexamineLog(`Done | ${ticker} saved.`);
            }
            break;
          }
          await new Promise((resolve) => window.setTimeout(resolve, 800));
        }
        setQueue((prev) =>
          prev.map((item) =>
            item.ticker === ticker && item.status === "running"
              ? failed
                ? { ...item, status: "error", error: failMsg }
                : { ...item, status: "done" }
              : item,
          ),
        );
        if (failed) setError(failMsg);
        await refresh();
      } catch (err) {
        const message =
          err instanceof ApiError ? err.message : "Reexamine failed";
        setError(message);
        setReexamineLog(null);
        setQueue((prev) =>
          prev.map((item) =>
            item.ticker === ticker && item.status === "running"
              ? { ...item, status: "error", error: message }
              : item,
          ),
        );
      } finally {
        processingRef.current = false;
        // Kick the effect again for the next queued item.
        setQueue((prev) => [...prev]);
      }
    })();
  }, [queue, lane, refresh]);

  async function clearSaved() {
    if (clearing || queueBusy) return;
    const laneLabel =
      lane === "daytrade" ? "day trade" : lane === "swing" ? "swing" : "invest";
    const ok = window.confirm(
      `Clear saved ${laneLabel} stocks and local LLM research cache?\n\nOnly this lane is wiped. The other lane stays intact.`,
    );
    if (!ok) return;
    setClearing(true);
    setNote(null);
    setError(null);
    try {
      const result = await api.clearCandidateHistory(lane);
      setNote(
        `Cleared ${result.stocks_cleared ?? 0} ${laneLabel} stocks` +
          (result.llm_cache_cleared
            ? ` and ${result.llm_cache_cleared} cached model responses.`
            : ".") +
          ` Skip list now has ${result.stocks_remaining ?? 0} tickers in this lane.`,
      );
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not clear saved stocks");
    } finally {
      setClearing(false);
    }
  }

  function toggleBatchSignal(signal: string) {
    setBatchSignals((prev) =>
      prev.includes(signal)
        ? prev.filter((s) => s !== signal)
        : [...prev, signal],
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">
            Found stocks
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-muted">
            One row per ticker per lane. Reexamine updates that row instead of
            duplicating it. Queue multiple reexamines or batch by signal / score /
            date.
          </p>
        </div>
        <button
          type="button"
          disabled={clearing || loading || queueBusy}
          onClick={() => void clearSaved()}
          className="border border-border px-3 py-2 text-sm text-ink-muted hover:bg-surface-muted disabled:opacity-50"
        >
          {clearing
            ? "Clearing..."
            : lane === "daytrade"
              ? "Clear daytrade saves"
              : lane === "swing"
                ? "Clear swing saves"
                : "Clear invest saves"}
        </button>
      </header>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => switchLane("invest")}
          className={cn(
            "border px-4 py-2 text-sm",
            lane === "invest"
              ? "border-accent bg-accent text-accent-fg"
              : "border-border text-ink-muted hover:bg-surface-muted",
          )}
        >
          Invest / hold
        </button>
        <button
          type="button"
          onClick={() => switchLane("swing")}
          className={cn(
            "border px-4 py-2 text-sm",
            lane === "swing"
              ? "border-accent bg-accent text-accent-fg"
              : "border-border text-ink-muted hover:bg-surface-muted",
          )}
        >
          Swing 1-7d
        </button>
        <button
          type="button"
          onClick={() => switchLane("daytrade")}
          className={cn(
            "border px-4 py-2 text-sm",
            lane === "daytrade"
              ? "border-accent bg-accent text-accent-fg"
              : "border-border text-ink-muted hover:bg-surface-muted",
          )}
        >
          Day trade
        </button>
      </div>

      {error ? (
        <div className="border border-danger/40 bg-danger/10 px-4 py-3 text-sm">{error}</div>
      ) : null}
      {note ? (
        <div className="border border-border bg-surface-muted px-4 py-3 text-sm text-ink">
          {note}
        </div>
      ) : null}

      <section className="space-y-3 border border-border bg-surface-raised/80 p-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
            Batch reexamine
          </h2>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={queueVisible}
              className="border border-border px-3 py-1.5 text-xs text-ink-muted hover:bg-surface-muted"
            >
              Queue visible ({visible.length})
            </button>
            <button
              type="button"
              onClick={queueMatchingBatch}
              className="border border-accent bg-accent px-3 py-1.5 text-xs text-accent-fg"
            >
              Queue matching
            </button>
          </div>
        </div>
        <p className="text-[11px] text-ink-muted">
          Pick any combination of signals, score range, and found-before date.
          Matching tickers in this lane are queued one after another.
        </p>
        <div className="flex flex-wrap gap-2">
          {batchSignalChoices.length === 0 ? (
            <span className="text-[11px] text-ink-subtle">No signals saved yet.</span>
          ) : (
            batchSignalChoices.map((signal) => {
              const on = batchSignals.includes(signal);
              return (
                <button
                  key={signal}
                  type="button"
                  onClick={() => toggleBatchSignal(signal)}
                  className={cn(
                    "border px-2.5 py-1 text-xs",
                    on
                      ? "border-accent bg-accent text-accent-fg"
                      : "border-border text-ink-muted hover:bg-surface-muted",
                  )}
                >
                  {signal}
                </button>
              );
            })
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Min score
            </span>
            <input
              type="number"
              min={0}
              max={100}
              value={batchMinScore}
              onChange={(e) =>
                setBatchMinScore(
                  Math.max(0, Math.min(100, Number(e.target.value) || 0)),
                )
              }
              className="w-full border border-border bg-surface px-3 py-2 text-ink"
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Max score
            </span>
            <input
              type="number"
              min={0}
              max={100}
              value={batchMaxScore}
              onChange={(e) =>
                setBatchMaxScore(
                  Math.max(0, Math.min(100, Number(e.target.value) || 0)),
                )
              }
              className="w-full border border-border bg-surface px-3 py-2 text-ink"
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Found before
            </span>
            <input
              type="date"
              value={batchBeforeDate}
              onChange={(e) => setBatchBeforeDate(e.target.value)}
              className="w-full border border-border bg-surface px-3 py-2 text-ink"
            />
          </label>
        </div>
      </section>

      {queue.length > 0 ? (
        <section className="space-y-3 border border-border bg-surface-raised/80 p-4">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
              Reexamine queue
            </h2>
            <p className="text-[11px] text-ink-subtle">
              {queueCounts.running} running | {queueCounts.queued} queued | {" "}
              {queueCounts.done} done | {queueCounts.error} error
            </p>
          </div>
          {activeItem ? (
            <>
              <p className="text-sm text-ink">
                Now: <span className="font-mono">{activeItem.ticker}</span>
                {activeItem.runId ? (
                  <span className="ml-2 font-mono text-[11px] text-ink-subtle">
                    {activeItem.runId}
                  </span>
                ) : null}
              </p>
              <ProgressStages horizontal stages={reexamineStages} />
              {reexamineLog ? (
                <p className="border border-border bg-surface px-3 py-2 font-mono text-[11px] text-ink-muted">
                  {reexamineLog}
                </p>
              ) : null}
            </>
          ) : null}
          <ol className="max-h-40 space-y-1 overflow-auto font-mono text-[11px]">
            {queue.map((item) => (
              <li
                key={`${item.ticker}-${item.status}-${item.runId ?? "x"}`}
                className={cn(
                  "flex flex-wrap items-center gap-2",
                  item.status === "error" && "text-danger",
                  item.status === "done" && "text-ink-subtle",
                  item.status === "running" && "text-ink",
                  item.status === "queued" && "text-ink-muted",
                )}
              >
                <span className="w-16 uppercase tracking-wide">{item.status}</span>
                <span>{item.ticker}</span>
                {item.error ? <span> | {item.error}</span> : null}
              </li>
            ))}
          </ol>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={cancelRemaining}
              disabled={queueCounts.queued === 0}
              className="border border-border px-3 py-1.5 text-xs text-ink-muted hover:bg-surface-muted disabled:opacity-50"
            >
              Cancel remaining
            </button>
            <button
              type="button"
              onClick={clearFinishedQueue}
              className="border border-border px-3 py-1.5 text-xs text-ink-muted hover:bg-surface-muted"
            >
              Clear finished
            </button>
            <button
              type="button"
              onClick={clearEntireQueue}
              className="border border-border px-3 py-1.5 text-xs text-ink-muted hover:bg-surface-muted"
            >
              Clear queue
            </button>
          </div>
        </section>
      ) : null}

      <section className="space-y-3 border border-border bg-surface-raised/80 p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <p className="text-[10px] uppercase tracking-[0.16em] text-ink-subtle">
            Filter & sort | {" "}
            {lane === "daytrade"
              ? "Day trade"
              : lane === "swing"
                ? "Swing 1-7d"
                : "Invest"}
          </p>
          <p className="text-xs text-ink-subtle">
            Showing {visible.length} of {rows.length}
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Search
            </span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ticker or name"
              className="w-full border border-border bg-surface px-3 py-2 text-ink"
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Signal
            </span>
            <select
              value={signalFilter}
              onChange={(e) => setSignalFilter(e.target.value)}
              className="w-full border border-border bg-surface px-3 py-2 text-ink"
            >
              {signalOptions.map((signal) => (
                <option key={signal} value={signal}>
                  {signal === "all" ? "All signals" : signal}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              List
            </span>
            <select
              value={listFilter}
              onChange={(e) => setListFilter(e.target.value as ListFilter)}
              className="w-full border border-border bg-surface px-3 py-2 text-ink"
            >
              <option value="all">All saved</option>
              <option value="ranked">Ranked only</option>
              <option value="scored">Scored only (not ranked)</option>
            </select>
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Sector
            </span>
            <select
              value={sectorFilter}
              onChange={(e) => setSectorFilter(e.target.value)}
              className="w-full border border-border bg-surface px-3 py-2 text-ink"
              disabled={sectorOptions.length <= 1}
            >
              {sectorOptions.map((sector) => (
                <option key={sector} value={sector}>
                  {sector === "all" ? "All sectors" : sector}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Min score
            </span>
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={minScore}
              onChange={(e) =>
                setMinScore(Math.max(0, Math.min(100, Number(e.target.value) || 0)))
              }
              className="w-full border border-border bg-surface px-3 py-2 text-ink"
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Min panel
            </span>
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={minPanel}
              onChange={(e) =>
                setMinPanel(Math.max(0, Math.min(100, Number(e.target.value) || 0)))
              }
              className="w-full border border-border bg-surface px-3 py-2 text-ink"
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Sort by
            </span>
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className="w-full border border-border bg-surface px-3 py-2 text-ink"
            >
              <option value="seen_at">Found date</option>
              <option value="score">Score</option>
              <option value="panel_score">Panel</option>
              <option value="price">Price</option>
              <option value="ticker">Ticker</option>
              <option value="name">Name</option>
              <option value="signal">Signal (strength)</option>
            </select>
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Direction
            </span>
            <select
              value={sortDir}
              onChange={(e) => setSortDir(e.target.value as SortDir)}
              className="w-full border border-border bg-surface px-3 py-2 text-ink"
            >
              <option value="desc">Descending</option>
              <option value="asc">Ascending</option>
            </select>
          </label>
        </div>
        {filtersActive ? (
          <button
            type="button"
            onClick={resetControls}
            className="text-xs text-accent hover:underline"
          >
            Reset filters & sort
          </button>
        ) : null}
      </section>

      <DataTable<CandidateSighting>
        columns={[
          {
            key: "when",
            header: "Found",
            className: "font-mono text-xs",
            render: (row) => formatWhen(row.seen_at),
          },
          {
            key: "ticker",
            header: "Ticker",
            className: "font-mono font-medium",
            render: (row) => row.ticker,
          },
          {
            key: "name",
            header: "Name",
            className: "max-w-[10rem] truncate text-xs text-ink-muted",
            render: (row) => row.name || "-",
          },
          {
            key: "score",
            header: "Score",
            className: "font-mono",
            render: (row) => (row.score != null ? `${row.score.toFixed(1)}/100` : "-"),
          },
          {
            key: "signal",
            header: "Signal",
            render: (row) => row.signal || "-",
          },
          {
            key: "price",
            header: "Price",
            className: "font-mono",
            render: (row) => (row.price != null ? `$${row.price.toFixed(2)}` : "-"),
          },
          {
            key: "panel",
            header: "Panel",
            className: "font-mono",
            render: (row) =>
              row.panel_score != null ? `${row.panel_score.toFixed(1)}/100` : "-",
          },
          {
            key: "kept",
            header: "List",
            render: (row) => (row.in_output ? "Ranked" : "Scored"),
          },
          {
            key: "actions",
            header: "",
            render: (row) => {
              const queued =
                queue.find(
                  (item) =>
                    item.ticker === row.ticker &&
                    (item.status === "queued" || item.status === "running"),
                ) ?? null;
              return (
                <div className="flex gap-2">
                  <Link
                    to={`/stocks/view/${encodeURIComponent(row.ticker)}`}
                    className="text-xs text-accent hover:underline"
                    onClick={(event) => event.stopPropagation()}
                  >
                    Chart
                  </Link>
                  <Link
                    to={`/stocks/trade?ticker=${encodeURIComponent(row.ticker)}&price=${row.price ?? ""}&run=${encodeURIComponent(row.research_run_id)}`}
                    className="text-xs text-accent hover:underline"
                    onClick={(event) => event.stopPropagation()}
                  >
                    Trade
                  </Link>
                  <button
                    type="button"
                    className="text-xs text-ink-muted underline disabled:opacity-50"
                    disabled={Boolean(queued)}
                    onClick={(event) => {
                      event.stopPropagation();
                      enqueueOne(row);
                    }}
                  >
                    {queued
                      ? queued.status === "running"
                        ? "Running..."
                        : "Queued"
                      : "Reexamine"}
                  </button>
                  <Link
                    to={`/stocks/discover?run=${encodeURIComponent(row.research_run_id)}`}
                    className="text-xs text-ink-muted hover:underline"
                    onClick={(event) => event.stopPropagation()}
                  >
                    Open run
                  </Link>
                </div>
              );
            },
          },
        ]}
        rows={visible}
        getRowId={(row) => `${row.lane ?? lane}-${row.ticker}`}
        onRowClick={(row) =>
          navigate(`/stocks/view/${encodeURIComponent(row.ticker)}`)
        }
        emptyMessage={
          loading
            ? "Loading saved stocks..."
            : rows.length === 0
              ? "No stocks saved yet. Run discovery - results stay here after you leave the page."
              : "No stocks match these filters."
        }
      />

      <section className="grid gap-3 border border-border bg-surface-raised/60 p-4 sm:grid-cols-2 lg:grid-cols-4 text-[11px] text-ink-muted">
        <p>
          <span className="text-ink">Score</span> - deterministic 0/100 to 100/100 that
          ranks discovery.
        </p>
        <p>
          <span className="text-ink">Panel</span> - average of three LLM roles on the
          same 0/100 to 100/100 scale; opinion only, never overrides Score.
        </p>
        <p>
          <span className="text-ink">Signal</span> - plain-language band from
          Score alone.
        </p>
        <p>
          <span className="text-ink">List</span> - Ranked made the top table;
          Scored was saved but not shown there.
        </p>
      </section>
    </div>
  );
}
