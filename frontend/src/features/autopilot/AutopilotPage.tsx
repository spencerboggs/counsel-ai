import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

type AutopilotStatus = {
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
  kill_switch?: {
    trading_disabled?: boolean;
    notes?: string | null;
    effect?: string;
  };
  market_session?: {
    open_for_market_orders?: boolean;
    phase?: string;
    local_et?: string;
    next_hint?: string | null;
    reasons?: string[];
  };
};

type Decision = {
  id: string;
  cycle_id: string;
  created_at: string;
  symbol?: string | null;
  action: string;
  status: string;
  notes?: string | null;
  votes?: Array<{
    role?: string;
    stance?: string;
    confidence?: number;
    rationale?: string;
  }> | null;
  consensus?: Record<string, unknown> | null;
  execution?: Record<string, unknown> | null;
  proposal?: Record<string, unknown> | null;
};

const LIVE_PHRASE = "ARM LIVE AUTOPILOT";

function money(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return " - ";
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

export function AutopilotPage() {
  const [status, setStatus] = useState<AutopilotStatus | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [positions, setPositions] = useState<
    Array<{ id: string; ticker: string; shares: number; cost_basis: number }>
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [armChecked, setArmChecked] = useState(false);
  const [armPhrase, setArmPhrase] = useState("");
  const [cycleSeconds, setCycleSeconds] = useState(120);
  const [maxPositions, setMaxPositions] = useState(8);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [wakeDismissed, setWakeDismissed] = useState(false);
  const [learning, setLearning] = useState<{
    win_rate?: number | null;
    wins?: number;
    losses?: number;
    lessons?: string[];
    note?: string;
  } | null>(null);
  const [broker, setBroker] = useState<{
    venue?: string;
    note?: string;
    broker?: {
      configured?: boolean;
      counts?: { positions?: number; open_orders?: number };
      account?: Record<string, unknown>;
      positions?: Array<Record<string, unknown>>;
    } | null;
  } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [st, dec, pos, learn, mon] = await Promise.all([
        api.autopilotStatus(),
        api.autopilotDecisions(30),
        api.listPositions("open"),
        api.autopilotLearning(40),
        api.brokerMonitor(),
      ]);
      setStatus(st);
      setDecisions(dec.items as Decision[]);
      setPositions(
        pos.map((p) => ({
          id: p.id,
          ticker: p.ticker,
          shares: p.shares,
          cost_basis: p.cost_basis,
        })),
      );
      setLearning(learn);
      setBroker(mon);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Status unavailable");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    if (status?.last_wake && status.running) {
      setWakeDismissed(false);
    }
  }, [status?.started_at, status?.running, status?.last_wake]);

  const isLive = Boolean(status?.is_live);
  const running = Boolean(status?.running);
  const liveArmedOk =
    !isLive || (armChecked && armPhrase.trim() === LIVE_PHRASE);

  async function onStart() {
    if (!liveArmedOk) return;
    setBusy(true);
    setError(null);
    try {
      await api.autopilotStart({
        arm_live_confirmed: isLive ? true : false,
        cycle_seconds: cycleSeconds,
        max_positions: maxPositions,
        max_notional_pct: 0.08,
      });
      setArmPhrase("");
      setArmChecked(false);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Start failed");
    } finally {
      setBusy(false);
    }
  }

  async function onStop() {
    setBusy(true);
    setError(null);
    try {
      await api.autopilotStop();
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Stop failed");
    } finally {
      setBusy(false);
    }
  }

  async function onKill(disabled: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api.setKillSwitch(
        disabled,
        disabled ? "Emergency disable from Autopilot" : "Re-enabled from Autopilot",
      );
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kill switch failed");
    } finally {
      setBusy(false);
    }
  }

  const capital = status?.capital || {};
  const wake = status?.last_wake || {};
  const session = status?.market_session;
  const killOn = Boolean(status?.kill_switch?.trading_disabled);
  const showWake =
    !wakeDismissed &&
    Boolean(wake.asleep_note || (wake.mismatches as string[] | undefined)?.length);

  const holdByTicker = new Map<string, Decision>();
  for (const d of decisions) {
    if (!d.symbol) continue;
    const key = d.symbol.toUpperCase();
    if (!holdByTicker.has(key)) holdByTicker.set(key, d);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">
            Autopilot
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-muted">
            Multi-role crew: quantitative signals, character votes, lawyer/broker
            veto. Paper by default; live only after Settings mode + arm confirm.
          </p>
          <div className="mt-2 flex flex-wrap gap-3 text-sm">
            <Link to="/tax" className="text-accent hover:underline">
              Tax ledger
            </Link>
            <Link to="/compliance" className="text-accent hover:underline">
              Compliance
            </Link>
            <Link to="/settings" className="text-accent hover:underline">
              Settings
            </Link>
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <span
            className={cn(
              "rounded-sm border px-3 py-1 font-mono text-xs uppercase tracking-[0.16em]",
              running
                ? "border-success/50 bg-success/15 text-success"
                : "border-border bg-surface-muted text-ink-muted",
            )}
          >
            {running ? "Running" : "Stopped"}
          </span>
          <span
            className={cn(
              "rounded-sm border px-3 py-1 font-mono text-[10px] uppercase tracking-[0.14em]",
              isLive
                ? "border-danger/50 bg-danger/15 text-danger"
                : "border-success/40 bg-success/10 text-success",
            )}
          >
            {isLive ? "Live" : "Paper"} | {status?.mode || " - "}
          </span>
        </div>
      </header>

      {error ? (
        <div className="border border-danger/40 bg-danger/10 px-4 py-3 text-sm">
          {error}
        </div>
      ) : null}

      {killOn ? (
        <div className="border border-danger/50 bg-danger/15 px-4 py-3 text-sm text-danger">
          Kill switch ON - new orders blocked.{" "}
          <button
            type="button"
            className="underline"
            disabled={busy}
            onClick={() => void onKill(false)}
          >
            Re-enable trading
          </button>
        </div>
      ) : null}

      {session && !session.open_for_market_orders ? (
        <div className="border border-warning/40 bg-warning/10 px-4 py-3 text-sm">
          <p className="font-medium text-ink">
            Market closed ({session.phase}) - Autopilot can run, fills blocked until RTH
          </p>
          <p className="mt-1 text-ink-muted">
            {session.next_hint || (session.reasons || []).join(" ")} | ET{" "}
            {session.local_et}
          </p>
        </div>
      ) : null}

      {session?.open_for_market_orders ? (
        <div className="border border-success/30 bg-success/10 px-4 py-2 text-xs text-success">
          Regular session open | ET {session.local_et}
        </div>
      ) : null}

      {showWake ? (
        <div className="border border-warning/40 bg-warning/10 px-4 py-3 text-sm">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="font-medium text-ink">Waking up...</p>
              <p className="mt-1 text-ink-muted">
                {String(wake.asleep_note || "Reconciled after sleep.")}
              </p>
              {Array.isArray(wake.mismatches) && wake.mismatches.length > 0 ? (
                <p className="mt-2 text-danger">
                  Trading halted for mismatch:{" "}
                  {(wake.mismatches as string[]).join("; ")}
                </p>
              ) : null}
            </div>
            <button
              type="button"
              className="text-xs text-ink-subtle hover:text-ink"
              onClick={() => setWakeDismissed(true)}
            >
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(
          [
            ["Cash", capital.cash ?? capital.settled_cash],
            ["Settled", capital.settled_cash ?? capital.settled],
            ["Buying power", capital.buying_power],
            ["Equity", capital.equity ?? capital.portfolio_value],
          ] as Array<[string, unknown]>
        ).map(([label, value]) => (
          <div
            key={label}
            className="border border-border bg-surface-raised/80 px-4 py-3"
          >
            <p className="text-[10px] uppercase tracking-[0.14em] text-ink-subtle">
              {label}
            </p>
            <p className="mt-1 font-mono text-lg text-ink">{money(value)}</p>
          </div>
        ))}
      </section>
      {status?.note ? (
        <p className="text-xs text-ink-subtle">{status.note}</p>
      ) : null}

      <section className="space-y-4 border border-border bg-surface-raised/60 p-5">
        <div className="flex flex-wrap items-end gap-4">
          <label className="text-sm text-ink-muted">
            Cycle seconds
            <input
              type="number"
              min={30}
              max={3600}
              value={cycleSeconds}
              disabled={running}
              onChange={(e) => setCycleSeconds(Number(e.target.value) || 120)}
              className="mt-1 block w-28 border border-border bg-surface px-2 py-1.5 font-mono text-sm text-ink"
            />
          </label>
          <label className="text-sm text-ink-muted">
            Max positions
            <input
              type="number"
              min={1}
              max={50}
              value={maxPositions}
              disabled={running}
              onChange={(e) => setMaxPositions(Number(e.target.value) || 8)}
              className="mt-1 block w-28 border border-border bg-surface px-2 py-1.5 font-mono text-sm text-ink"
            />
          </label>
          <div className="ml-auto flex gap-2">
            {!killOn ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void onKill(true)}
                className="border border-danger/40 bg-danger/10 px-4 py-2 text-sm text-danger hover:bg-danger/20 disabled:opacity-50"
              >
                Kill switch
              </button>
            ) : null}
            {running ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void onStop()}
                className="border border-border bg-surface-muted px-4 py-2 text-sm text-ink hover:bg-surface-muted/80 disabled:opacity-50"
              >
                Stop
              </button>
            ) : (
              <button
                type="button"
                disabled={busy || !liveArmedOk || killOn}
                onClick={() => void onStart()}
                className="border border-accent/40 bg-accent/15 px-4 py-2 text-sm text-ink hover:bg-accent/25 disabled:opacity-50"
              >
                Start
              </button>
            )}
          </div>
        </div>

        {isLive && !running ? (
          <div className="space-y-2 border border-danger/40 bg-danger/10 p-4">
            <p className="text-sm text-danger">
              Live trading mode is active. Autopilot will use real Alpaca buying
              power - not the paper seed.
            </p>
            <label className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={armChecked}
                onChange={(e) => setArmChecked(e.target.checked)}
              />
              I understand Autopilot may place live orders
            </label>
            <label className="block text-sm text-ink-muted">
              Type {LIVE_PHRASE} to arm
              <input
                value={armPhrase}
                onChange={(e) => setArmPhrase(e.target.value)}
                className="mt-1 block w-full border border-border bg-surface px-2 py-1.5 font-mono text-sm text-ink"
                placeholder={LIVE_PHRASE}
                autoComplete="off"
              />
            </label>
            <p className="text-xs text-ink-subtle">
              Equity {money(capital.equity)} | Cash {money(capital.cash)} | BP{" "}
              {money(capital.buying_power)}
            </p>
          </div>
        ) : null}

        <p className="text-xs text-ink-subtle">
          Cycles: {status?.cycle_count ?? 0}
          {status?.last_cycle_at ? ` | last ${status.last_cycle_at}` : ""}
          {status?.last_error ? ` | error: ${status.last_error}` : ""}
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
          Open positions
        </h2>
        {positions.length === 0 ? (
          <p className="text-sm text-ink-muted">No open positions.</p>
        ) : (
          <ul className="divide-y divide-border border border-border">
            {positions.map((p) => {
              const last = holdByTicker.get(p.ticker.toUpperCase());
              return (
                <li
                  key={p.id}
                  className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-3 text-sm"
                >
                  <span className="font-mono text-ink">
                    {p.ticker} | {p.shares} @ {money(p.cost_basis)}
                  </span>
                  <span className="text-xs text-ink-muted">
                    {last
                      ? `Last crew: ${last.action} (${last.status})`
                      : "No crew vote yet"}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2 border border-border bg-surface-raised/60 p-4">
          <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
            Paper learning journal
          </h2>
          {learning ? (
            <>
              <p className="text-sm text-ink">
                Win rate{" "}
                {learning.win_rate != null
                  ? `${Math.round(learning.win_rate * 100)}%`
                  : " - "}{" "}
 | {learning.wins ?? 0}W / {learning.losses ?? 0}L
              </p>
              <ul className="max-h-36 space-y-1 overflow-y-auto text-xs text-ink-muted">
                {(learning.lessons || []).length === 0 ? (
                  <li>No scored outcomes yet - run paper cycles through sells.</li>
                ) : (
                  (learning.lessons || []).map((lesson, i) => (
                    <li key={i}>- {lesson}</li>
                  ))
                )}
              </ul>
              {learning.note ? (
                <p className="text-[11px] text-ink-subtle">{learning.note}</p>
              ) : null}
            </>
          ) : (
            <p className="text-sm text-ink-muted">Loading journal...</p>
          )}
        </div>
        <div className="space-y-2 border border-border bg-surface-raised/60 p-4">
          <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
            Broker monitor (Alpaca)
          </h2>
          {broker ? (
            <>
              <p className="text-sm text-ink">Venue: {broker.venue}</p>
              {broker.broker?.configured ? (
                <p className="text-xs text-ink-muted">
                  Positions {broker.broker.counts?.positions ?? 0} | Open orders{" "}
                  {broker.broker.counts?.open_orders ?? 0}
                  {broker.broker.account?.equity != null
                    ? ` | Equity ${money(broker.broker.account.equity)}`
                    : ""}
                  {broker.broker.account?.buying_power != null
                    ? ` | BP ${money(broker.broker.account.buying_power)}`
                    : ""}
                </p>
              ) : (
                <p className="text-xs text-ink-muted">
                  {broker.note ||
                    "Add free Alpaca paper keys in Settings to watch broker positions."}
                </p>
              )}
              {broker.broker?.positions && broker.broker.positions.length > 0 ? (
                <ul className="max-h-28 space-y-1 overflow-y-auto font-mono text-xs text-ink-muted">
                  {broker.broker.positions.slice(0, 8).map((p, i) => (
                    <li key={String(p.symbol || i)}>
                      {String(p.symbol)} | qty {String(p.qty)} | {" "}
                      {money(p.market_value)}
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : (
            <p className="text-sm text-ink-muted">Loading broker...</p>
          )}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
          Cycle log
        </h2>
        <ul className="max-h-48 space-y-1 overflow-y-auto border border-border bg-surface-raised/40 p-3 font-mono text-xs text-ink-muted">
          {(status?.recent_events || []).length === 0 ? (
            <li>No events yet.</li>
          ) : (
            (status?.recent_events || []).map((ev, i) => (
              <li key={`${ev.created_at}-${i}`}>
                <span className="text-ink-subtle">
                  [{ev.stage || " - "}]
                </span>{" "}
                {ev.message}
              </li>
            ))
          )}
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
          Decisions & character votes
        </h2>
        {decisions.length === 0 ? (
          <p className="text-sm text-ink-muted">No decisions recorded yet.</p>
        ) : (
          <ul className="space-y-2">
            {decisions.map((d) => {
              const open = expanded === d.id;
              return (
                <li
                  key={d.id}
                  className="border border-border bg-surface-raised/80"
                >
                  <button
                    type="button"
                    className="flex w-full flex-wrap items-baseline justify-between gap-2 px-4 py-3 text-left text-sm"
                    onClick={() => setExpanded(open ? null : d.id)}
                  >
                    <span className="font-mono text-ink">
                      {d.symbol || " - "} | {d.action} | {d.status}
                    </span>
                    <span className="text-xs text-ink-subtle">{d.created_at}</span>
                  </button>
                  {d.notes ? (
                    <p className="border-t border-border px-4 py-2 text-xs text-ink-muted">
                      {d.notes}
                    </p>
                  ) : null}
                  {open && Array.isArray(d.votes) ? (
                    <ul className="space-y-2 border-t border-border px-4 py-3">
                      {d.votes.map((v, i) => (
                        <li key={`${v.role}-${i}`} className="text-xs">
                          <span className="font-mono text-ink">
                            {v.role}: {v.stance}
                          </span>
                          {v.confidence != null ? (
                            <span className="text-ink-subtle">
                              {" "}
                              ({Math.round(Number(v.confidence) * 100)}%)
                            </span>
                          ) : null}
                          <p className="mt-0.5 text-ink-muted">{v.rationale}</p>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
