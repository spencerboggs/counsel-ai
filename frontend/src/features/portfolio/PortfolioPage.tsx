import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LayoutGrid, List, ExternalLink } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { DataTable } from "@/components";
import { api, ApiError } from "@/lib/api";
import type {
  ChartSnapshot,
  PaperPosition,
  PortfolioMode,
  PortfolioStats,
} from "@/types/api";
import { cn } from "@/lib/cn";
import { Sparkline } from "@/features/portfolio/Sparkline";

const POLL_MS = 60_000;
const VIEW_KEY = "ai-counsel.paper-book.view";
const CHART_CACHE_PREFIX = "ai-counsel.chart.1mo.";

type ViewMode = "list" | "grid";

function formatWhen(value: string) {
  const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function money(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "-";
  return `$${value.toFixed(digits)}`;
}

function pct(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

function signedMoney(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}$${value.toFixed(2)}`;
}

function compact(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "-";
  if (Math.abs(value) >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  return money(value, 0);
}

function yahooUrl(ticker: string) {
  return `https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}`;
}

function tradingViewUrl(ticker: string) {
  return `https://www.tradingview.com/symbols/${encodeURIComponent(ticker)}/`;
}

function readStoredView(): ViewMode {
  try {
    const raw = localStorage.getItem(VIEW_KEY);
    return raw === "grid" ? "grid" : "list";
  } catch {
    return "list";
  }
}

function readCachedChart(ticker: string): ChartSnapshot | null {
  try {
    const raw = sessionStorage.getItem(CHART_CACHE_PREFIX + ticker.toUpperCase());
    if (!raw) return null;
    return JSON.parse(raw) as ChartSnapshot;
  } catch {
    return null;
  }
}

function writeCachedChart(ticker: string, snap: ChartSnapshot) {
  try {
    sessionStorage.setItem(
      CHART_CACHE_PREFIX + ticker.toUpperCase(),
      JSON.stringify(snap),
    );
  } catch {
    /* quota */
  }
}

function syntheticChart(position: PaperPosition): ChartSnapshot {
  const entry = position.cost_basis;
  const last = position.last_price ?? entry;
  return {
    ticker: position.ticker,
    range: "1mo",
    last,
    bars: [
      { t: position.opened_at, c: entry },
      { t: new Date().toISOString(), c: last },
    ],
    source: "synthetic",
    stale: true,
  };
}

export function PortfolioPage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<PaperPosition[]>([]);
  const [stats, setStats] = useState<PortfolioStats | null>(null);
  const [mode, setMode] = useState<PortfolioMode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastQuoteAt, setLastQuoteAt] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [view, setView] = useState<ViewMode>(() => readStoredView());
  const [charts, setCharts] = useState<Record<string, ChartSnapshot>>({});
  const [chartNotes, setChartNotes] = useState<Record<string, string>>({});
  const mounted = useRef(true);

  const setViewMode = useCallback((next: ViewMode) => {
    setView(next);
    try {
      localStorage.setItem(VIEW_KEY, next);
    } catch {
      /* ignore */
    }
  }, []);

  const refresh = useCallback(async (opts?: { quiet?: boolean }) => {
    const quiet = opts?.quiet === true;
    if (quiet) setRefreshing(true);
    else setLoading(true);
    try {
      const [positions, portfolioStats, portfolioMode] = await Promise.all([
        api.listPositions("open"),
        api.portfolioStats(),
        api.portfolioMode(),
      ]);
      if (!mounted.current) return;
      setRows(positions);
      setStats(portfolioStats);
      setMode(portfolioMode);
      setLastQuoteAt(new Date());
      setError(null);
    } catch (err) {
      if (!mounted.current) return;
      setError(err instanceof ApiError ? err.message : "Could not load portfolio");
    } finally {
      if (mounted.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const id = window.setInterval(() => {
      void refresh({ quiet: true });
    }, POLL_MS);
    return () => {
      mounted.current = false;
      window.clearInterval(id);
    };
  }, [refresh]);

  // Stagger chart loads in grid mode; use session + server cache; fall back to synthetic.
  useEffect(() => {
    if (view !== "grid" || rows.length === 0) return;
    let cancelled = false;

    void (async () => {
      for (const row of rows) {
        if (cancelled) return;
        const key = row.ticker.toUpperCase();
        if (charts[key]?.source === "yahoo" && !charts[key]?.stale) continue;

        const cached = readCachedChart(key);
        if (cached?.bars?.length) {
          setCharts((prev) => (prev[key] ? prev : { ...prev, [key]: cached }));
        }

        try {
          const snap = await api.chartSnapshot(key, "1mo");
          if (cancelled) return;
          if (snap.bars?.length) writeCachedChart(key, snap);
          setCharts((prev) => ({ ...prev, [key]: snap }));
          setChartNotes((prev) => {
            const next = { ...prev };
            delete next[key];
            return next;
          });
        } catch (err) {
          if (cancelled) return;
          const fallback = cached ?? syntheticChart(row);
          setCharts((prev) => ({ ...prev, [key]: fallback }));
          setChartNotes((prev) => ({
            ...prev,
            [key]:
              err instanceof ApiError
                ? err.message
                : "Chart unavailable - showing entry->mark fallback",
          }));
        }
        // Soft throttle so Yahoo is less likely to 429 the whole book.
        await new Promise((r) => window.setTimeout(r, 400));
      }
    })();

    return () => {
      cancelled = true;
    };
    // Intentionally omit charts - we only re-run when positions/view change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, rows]);

  const empty = !loading && rows.length === 0;

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">
            Paper book
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-muted">
            Positions you opened. Mark-to-market uses Yahoo last trade (prior
            close when the session is shut). Charts cache for ~15 minutes and
            fall back to a cached or entry-to-mark line when Yahoo rate-limits.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex border border-border">
            <button
              type="button"
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 text-sm",
                view === "list"
                  ? "bg-surface-muted text-ink"
                  : "text-ink-muted hover:bg-surface-raised",
              )}
              onClick={() => setViewMode("list")}
            >
              <List className="size-3.5" />
              List
            </button>
            <button
              type="button"
              className={cn(
                "flex items-center gap-1.5 border-l border-border px-3 py-1.5 text-sm",
                view === "grid"
                  ? "bg-surface-muted text-ink"
                  : "text-ink-muted hover:bg-surface-raised",
              )}
              onClick={() => setViewMode("grid")}
            >
              <LayoutGrid className="size-3.5" />
              Grid
            </button>
          </div>
          <button
            type="button"
            className="border border-border px-3 py-1.5 text-sm text-ink hover:bg-surface-raised disabled:opacity-50"
            disabled={loading || refreshing}
            onClick={() => void refresh({ quiet: true })}
          >
            {refreshing ? "Refreshing..." : "Refresh quotes"}
          </button>
          <Link to="/settings" className="px-1 text-sm text-accent hover:underline">
            Manage keys / mode
          </Link>
        </div>
      </header>

      <div
        className={cn(
          "border px-4 py-3 text-sm",
          mode?.is_live
            ? "border-danger/40 bg-danger/10 text-danger"
            : "border-success/40 bg-success/10 text-ink",
        )}
      >
        Mode: {mode?.label ?? "PAPER (local free ledger)"}
        {lastQuoteAt ? (
          <span className="ml-3 text-ink-muted">
            Quotes as of {lastQuoteAt.toLocaleTimeString()}
          </span>
        ) : null}
      </div>

      {stats ? (
        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Open" value={String(stats.open_positions)} />
          <Stat label="Invested" value={money(stats.invested_cost)} />
          <Stat label="Mark" value={money(stats.market_value)} />
          <Stat label="Unrealized" value={signedMoney(stats.unrealized_pnl)} />
        </section>
      ) : null}

      {error ? (
        <div className="border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-ink">
          {error}
        </div>
      ) : null}

      {empty ? (
        <p className="border border-border bg-surface-raised/60 px-4 py-8 text-center text-sm text-ink-muted">
          No open positions yet. Open a trade from Found stocks.
        </p>
      ) : view === "list" ? (
        <DataTable<PaperPosition>
          columns={[
            {
              key: "ticker",
              header: "Ticker",
              className: "font-mono",
              render: (r) => (
                <span>
                  {r.ticker}
                  {r.name ? (
                    <span className="ml-2 text-xs text-ink-subtle">{r.name}</span>
                  ) : null}
                </span>
              ),
            },
            {
              key: "opened",
              header: "Entered",
              className: "text-xs text-ink-muted",
              render: (r) => formatWhen(r.opened_at),
            },
            {
              key: "shares",
              header: "Shares",
              className: "font-mono",
              render: (r) => String(r.shares),
            },
            {
              key: "basis",
              header: "Entry $/sh",
              className: "font-mono",
              render: (r) => money(r.cost_basis),
            },
            {
              key: "cost",
              header: "Cost",
              className: "font-mono",
              render: (r) => money(r.cost_total ?? r.cost_basis * r.shares),
            },
            {
              key: "last",
              header: "Last",
              className: "font-mono",
              render: (r) => money(r.last_price),
            },
            {
              key: "chg",
              header: "Day",
              className: "font-mono text-xs",
              render: (r) => (
                <span
                  className={cn(
                    r.change_pct != null && r.change_pct > 0 && "text-success",
                    r.change_pct != null && r.change_pct < 0 && "text-danger",
                  )}
                >
                  {pct(r.change_pct)}
                </span>
              ),
            },
            {
              key: "value",
              header: "Value",
              className: "font-mono",
              render: (r) => money(r.market_value),
            },
            {
              key: "pnl",
              header: "Unrealized",
              className: "font-mono",
              render: (r) => (
                <span
                  className={cn(
                    r.unrealized_pnl != null &&
                      r.unrealized_pnl > 0 &&
                      "text-success",
                    r.unrealized_pnl != null &&
                      r.unrealized_pnl < 0 &&
                      "text-danger",
                  )}
                >
                  {signedMoney(r.unrealized_pnl)}
                  {r.unrealized_pnl_pct != null
                    ? ` (${pct(r.unrealized_pnl_pct)})`
                    : ""}
                </span>
              ),
            },
            {
              key: "close",
              header: "",
              render: (r) => (
                <button
                  type="button"
                  className="text-xs text-ink-muted underline"
                  onClick={(event) => {
                    event.stopPropagation();
                    void api.closePaperPosition(r.id).then(() => refresh());
                  }}
                >
                  Exit
                </button>
              ),
            },
          ]}
          rows={rows}
          getRowId={(r) => r.id}
          onRowClick={(r) =>
            navigate(`/stocks/view/${encodeURIComponent(r.ticker)}`)
          }
          emptyMessage={loading ? "Loading paper book..." : "No open positions."}
        />
      ) : (
        <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {rows.map((row) => (
            <PositionTile
              key={row.id}
              position={row}
              chart={charts[row.ticker.toUpperCase()]}
              chartNote={chartNotes[row.ticker.toUpperCase()]}
              onOpen={() =>
                navigate(`/stocks/view/${encodeURIComponent(row.ticker)}`)
              }
              onClose={() =>
                void api.closePaperPosition(row.id).then(() => refresh())
              }
            />
          ))}
        </section>
      )}
    </div>
  );
}

function PositionTile({
  position,
  chart,
  chartNote,
  onOpen,
  onClose,
}: {
  position: PaperPosition;
  chart?: ChartSnapshot;
  chartNote?: string;
  onOpen: () => void;
  onClose: () => void;
}) {
  const closes = useMemo(
    () =>
      (chart?.bars ?? [])
        .map((b) => b.c)
        .filter((v): v is number => v != null && !Number.isNaN(v)),
    [chart],
  );
  const up =
    position.unrealized_pnl == null
      ? null
      : position.unrealized_pnl >= 0;

  return (
    <article className="flex flex-col border border-border bg-surface-raised/80">
      <button
        type="button"
        className="flex w-full flex-col gap-3 p-4 text-left hover:bg-surface-muted/40"
        onClick={onOpen}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-mono text-lg font-semibold tracking-tight text-ink">
              {position.ticker}
            </p>
            <p className="mt-0.5 line-clamp-1 text-xs text-ink-muted">
              {position.name ?? position.sector ?? " - "}
            </p>
          </div>
          <div className="text-right">
            <p className="font-mono text-lg text-ink">
              {money(position.last_price)}
            </p>
            <p
              className={cn(
                "font-mono text-xs",
                position.change_pct != null &&
                  position.change_pct > 0 &&
                  "text-success",
                position.change_pct != null &&
                  position.change_pct < 0 &&
                  "text-danger",
              )}
            >
              {signedMoney(position.change)} | {pct(position.change_pct)}
            </p>
          </div>
        </div>

        <div className="border border-border/70 bg-surface/50 px-1 pt-1">
          <Sparkline values={closes} positive={up} />
          <div className="flex items-center justify-between px-2 pb-1 text-[10px] text-ink-subtle">
            <span>
              {chart?.stale || chart?.source === "synthetic"
                ? chart?.source === "synthetic"
                  ? "Fallback: entry -> mark"
                  : "Cached chart"
                : "1M Yahoo"}
            </span>
            {chart?.range_change_pct != null ? (
              <span
                className={cn(
                  chart.range_change_pct > 0 && "text-success",
                  chart.range_change_pct < 0 && "text-danger",
                )}
              >
                Range {pct(chart.range_change_pct)}
              </span>
            ) : null}
          </div>
        </div>
        {chartNote ? (
          <p className="text-[10px] leading-snug text-warning">{chartNote}</p>
        ) : null}

        <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
          <TileStat label="Shares owned" value={String(position.shares)} />
          <TileStat
            label="Value owned"
            value={money(position.market_value)}
          />
          <TileStat label="Entry $/sh" value={money(position.cost_basis)} />
          <TileStat
            label="Cost basis"
            value={money(position.cost_total ?? position.cost_basis * position.shares)}
          />
          <TileStat
            label="Unrealized $"
            value={signedMoney(position.unrealized_pnl)}
            tone={
              position.unrealized_pnl == null
                ? undefined
                : position.unrealized_pnl >= 0
                  ? "up"
                  : "down"
            }
          />
          <TileStat
            label="Unrealized %"
            value={pct(position.unrealized_pnl_pct)}
            tone={
              position.unrealized_pnl_pct == null
                ? undefined
                : position.unrealized_pnl_pct >= 0
                  ? "up"
                  : "down"
            }
          />
          <TileStat label="Market enter" value={formatWhen(position.opened_at)} />
          <TileStat
            label="Exit mark"
            value={
              position.last_price != null
                ? `${money(position.last_price)} /sh`
                : "-"
            }
          />
          <TileStat label="Prev close" value={money(position.previous_close)} />
          <TileStat label="Day open" value={money(position.day_open)} />
          <TileStat label="Day high" value={money(position.day_high)} />
          <TileStat label="Day low" value={money(position.day_low)} />
          <TileStat label="Market cap" value={compact(position.market_cap)} />
          <TileStat
            label="P/E"
            value={
              position.pe != null ? position.pe.toFixed(1) : "-"
            }
          />
          <TileStat
            label="Beta"
            value={position.beta != null ? position.beta.toFixed(2) : "-"}
          />
          <TileStat
            label="Avg volume"
            value={
              position.avg_volume != null
                ? Math.round(position.avg_volume).toLocaleString()
                : "-"
            }
          />
          <TileStat
            label="52w high"
            value={money(position.fifty_two_week_high)}
          />
          <TileStat
            label="52w low"
            value={money(position.fifty_two_week_low)}
          />
          <TileStat label="Sector" value={position.sector ?? "-"} />
          <TileStat label="Industry" value={position.industry ?? "-"} />
          <TileStat
            label="Counsel score"
            value={
              position.score != null
                ? `${position.score.toFixed(1)}${position.signal ? ` | ${position.signal}` : ""}`
                : "-"
            }
          />
          <TileStat label="Lane" value={position.lane ?? "-"} />
        </dl>
      </button>

      <footer className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-2.5">
        <a
          href={yahooUrl(position.ticker)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          Yahoo <ExternalLink className="size-3" />
        </a>
        <a
          href={tradingViewUrl(position.ticker)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          TradingView <ExternalLink className="size-3" />
        </a>
        <button
          type="button"
          className="ml-auto text-xs text-ink-muted underline"
          onClick={(e) => {
            e.stopPropagation();
            onClose();
          }}
        >
          Exit position
        </button>
      </footer>
    </article>
  );
}

function TileStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "up" | "down";
}) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-[0.12em] text-ink-subtle">
        {label}
      </dt>
      <dd
        className={cn(
          "mt-0.5 font-mono text-[12px] text-ink",
          tone === "up" && "text-success",
          tone === "down" && "text-danger",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-border bg-surface-raised/80 p-4">
      <p className="text-[10px] uppercase tracking-[0.14em] text-ink-subtle">
        {label}
      </p>
      <p className="mt-2 font-mono text-lg text-ink">{value}</p>
    </div>
  );
}
