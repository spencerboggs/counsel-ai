import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "@/lib/api";
import type { PaperPosition } from "@/types/api";
import { cn } from "@/lib/cn";

function yahooUrl(ticker: string) {
  return `https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}`;
}

function tradingViewUrl(ticker: string) {
  return `https://www.tradingview.com/symbols/${encodeURIComponent(ticker)}/`;
}

function money(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "-";
  return `$${value.toFixed(digits)}`;
}

function formatWhen(value: string) {
  const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function StockDetailPage() {
  const { ticker: rawTicker = "" } = useParams();
  const ticker = rawTicker.toUpperCase();
  const [positions, setPositions] = useState<PaperPosition[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const rows = await api.listPositions("open");
        if (cancelled) return;
        setPositions(
          rows.filter((row) => row.ticker.toUpperCase() === ticker),
        );
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : "Could not load positions",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  const position = positions[0] ?? null;
  const tradeHref = useMemo(() => {
    const q = new URLSearchParams();
    q.set("ticker", ticker);
    return `/stocks/trade?${q.toString()}`;
  }, [ticker]);

  if (!ticker) {
    return (
      <p className="text-sm text-ink-muted">
        Pick a ticker from{" "}
        <Link to="/stocks/portfolio" className="text-accent hover:underline">
          Paper book
        </Link>{" "}
        or{" "}
        <Link to="/stocks/found" className="text-accent hover:underline">
          Found stocks
        </Link>
        .
      </p>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-[10px] uppercase tracking-[0.16em] text-ink-subtle">
            Stock
          </p>
          <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight text-ink">
            {ticker}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">
            Charts and live quotes live on Yahoo Finance or TradingView.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            to={tradeHref}
            className="border border-accent bg-accent px-3 py-2 text-sm text-accent-fg"
          >
            Trade
          </Link>
          <Link
            to="/stocks/portfolio"
            className="border border-border px-3 py-2 text-sm text-ink-muted hover:bg-surface-muted"
          >
            Paper book
          </Link>
        </div>
      </header>

      {error ? (
        <div className="border border-danger/40 bg-danger/10 px-4 py-3 text-sm">
          {error}
        </div>
      ) : null}

      <section className="border border-border bg-surface-raised/80 p-5">
        <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
          Market charts
        </h2>
        <p className="mt-2 text-sm text-ink-muted">
          Open a full chart in your browser - better data, ranges, and tools
          than we can host here.
        </p>
        <div className="mt-4 flex flex-wrap gap-3">
          <a
            href={yahooUrl(ticker)}
            target="_blank"
            rel="noopener noreferrer"
            className="border border-accent bg-accent px-4 py-2.5 text-sm text-accent-fg"
          >
            Yahoo Finance
          </a>
          <a
            href={tradingViewUrl(ticker)}
            target="_blank"
            rel="noopener noreferrer"
            className="border border-border px-4 py-2.5 text-sm text-ink hover:bg-surface-muted"
          >
            TradingView
          </a>
        </div>
        <p className="mt-3 font-mono text-[11px] text-ink-subtle">
          {yahooUrl(ticker)}
        </p>
      </section>

      {loading ? (
        <p className="text-sm text-ink-subtle">Loading paper position...</p>
      ) : position ? (
        <section className="border border-border bg-surface-raised/80 p-5">
          <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
            Your position
          </h2>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Stat label="Bought" value={formatWhen(position.opened_at)} />
            <Stat label="Shares" value={String(position.shares)} />
            <Stat label="Cost / share" value={money(position.cost_basis)} />
            <Stat
              label="Invested"
              value={money(position.cost_basis * position.shares)}
            />
          </div>
          {position.notes ? (
            <p className="mt-3 text-xs text-ink-muted">{position.notes}</p>
          ) : null}
          {positions.length > 1 ? (
            <p className="mt-2 text-[11px] text-ink-subtle">
              Showing earliest open lot. You have {positions.length} open lots
              in {ticker}.
            </p>
          ) : null}
        </section>
      ) : (
        <section className="border border-border bg-surface-raised/60 px-5 py-4 text-sm text-ink-muted">
          No open paper position in {ticker}.{" "}
          <Link to={tradeHref} className="text-accent hover:underline">
            Trade it
          </Link>{" "}
          to track buy-in date here.
        </section>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-[0.14em] text-ink-subtle">
        {label}
      </p>
      <p className={cn("mt-1 font-mono text-sm text-ink", tone)}>{value}</p>
    </div>
  );
}
