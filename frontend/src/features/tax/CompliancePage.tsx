import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

export function CompliancePage() {
  const [data, setData] = useState<{
    items: Array<{
      section: number;
      title: string;
      status: string;
      notes: string;
    }>;
    counts: Record<string, number>;
    disclaimer: string;
    market_session?: {
      open_for_market_orders?: boolean;
      phase?: string;
      local_et?: string;
      next_hint?: string | null;
    };
    readiness?: {
      paper_ready?: boolean;
      live_requires?: string[];
      deferred_ok_for_paper?: string[];
    };
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        setData(await api.taxCompliance());
        setError(null);
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : "Could not load checklist",
        );
      }
    })();
  }, []);

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <header>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">
          Compliance checklist
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-muted">
          Engineering status against the Alpaca live-trading readiness list.
          Core path stays free unless you add paid API keys. Not legal advice.
        </p>
        <div className="mt-2 flex flex-wrap gap-3 text-sm">
          <Link to="/tax" className="text-accent hover:underline">
            Tax ledger
          </Link>
          <Link to="/autopilot" className="text-accent hover:underline">
            Autopilot
          </Link>
          <Link to="/settings" className="text-accent hover:underline">
            Settings
          </Link>
        </div>
      </header>

      {error ? (
        <div className="border border-danger/40 bg-danger/10 px-4 py-3 text-sm">
          {error}
        </div>
      ) : null}

      {data ? (
        <>
          <div className="border border-border bg-surface-raised/80 px-4 py-3 text-sm">
            <p className="text-ink">
              Paper ready:{" "}
              <span
                className={
                  data.readiness?.paper_ready ? "text-success" : "text-warning"
                }
              >
                {data.readiness?.paper_ready ? "Yes" : "Not yet"}
              </span>
              {" | "}
              Session: {data.market_session?.phase ?? " - "}
              {data.market_session?.open_for_market_orders
                ? " (open for orders)"
                : " (fills blocked until RTH)"}
            </p>
            {data.market_session?.next_hint ? (
              <p className="mt-1 text-xs text-ink-muted">
                {data.market_session.next_hint}
              </p>
            ) : null}
            {data.readiness?.deferred_ok_for_paper?.length ? (
              <p className="mt-2 text-xs text-ink-subtle">
                Deferred OK for paper:{" "}
                {data.readiness.deferred_ok_for_paper.join("; ")}
              </p>
            ) : null}
          </div>
          <p className="text-sm text-ink-muted">
            Done {data.counts.done} | Partial {data.counts.partial} | Todo{" "}
            {data.counts.todo} / {data.counts.total}
          </p>
          <p className="text-xs text-ink-subtle">{data.disclaimer}</p>
          <ul className="space-y-2">
            {data.items.map((item) => (
              <li
                key={item.section}
                className="border border-border bg-surface-raised/80 px-4 py-3"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-sm text-ink">
                    <span className="font-mono text-ink-subtle">
                      {item.section}.
                    </span>{" "}
                    {item.title}
                  </p>
                  <span
                    className={cn(
                      "text-[10px] uppercase tracking-[0.14em]",
                      item.status === "done" && "text-success",
                      item.status === "partial" && "text-warning",
                      item.status === "todo" && "text-ink-subtle",
                    )}
                  >
                    {item.status}
                  </span>
                </div>
                <p className="mt-1 text-xs text-ink-muted">{item.notes}</p>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}
