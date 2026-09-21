import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

type Venue = "paper_local" | "paper_alpaca" | "live_alpaca";

export function TradePage() {
  const [params] = useSearchParams();
  const ticker = (params.get("ticker") || "").toUpperCase();
  const hintedPrice = Number(params.get("price") || "");
  const sourceRunId = params.get("run");
  const [notional, setNotional] = useState(100);
  const [venue, setVenue] = useState<Venue>("paper_local");
  const [liveConfirmed, setLiveConfirmed] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [washBlock, setWashBlock] = useState<Record<string, unknown> | null>(
    null,
  );
  const [washOverride, setWashOverride] = useState("");
  const [capital, setCapital] = useState<Record<string, unknown> | null>(null);

  const price = Number.isFinite(hintedPrice) && hintedPrice > 0 ? hintedPrice : null;
  const sizing = useMemo(() => {
    if (!price || notional <= 0) return null;
    const shares = Math.floor(notional / price);
    const spend = Math.round(shares * price * 100) / 100;
    const leftover = Math.round((notional - spend) * 100) / 100;
    return { shares, spend, leftover };
  }, [notional, price]);

  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    void (async () => {
      try {
        const [wash, cap] = await Promise.all([
          api.washCheck(ticker),
          api.taxCapital(),
        ]);
        if (cancelled) return;
        setWashBlock(wash.allowed ? null : (wash.block ?? null));
        setCapital(cap);
      } catch {
        if (!cancelled) setWashBlock(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  async function submit() {
    if (!ticker) return;
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const position = await api.placeOrder({
        ticker,
        notional,
        venue,
        live_confirmed: liveConfirmed,
        price,
        source_run_id: sourceRunId,
        wash_override_phrase: washOverride.trim() || null,
      });
      const spent = position.shares * position.cost_basis;
      setMessage(
        `Bought ${position.shares} whole share${position.shares === 1 ? "" : "s"} of ${position.ticker} ` +
          `~ $${spent.toFixed(2)} @ $${position.cost_basis.toFixed(2)} each. ` +
          `${position.notes || venue}`,
      );
      setWashOverride("");
      const wash = await api.washCheck(ticker);
      setWashBlock(wash.allowed ? null : (wash.block ?? null));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Order failed");
    } finally {
      setSubmitting(false);
    }
  }

  const overrideOk =
    !washBlock ||
    washOverride.trim() === String(washBlock.override_phrase || "");

  const canSubmit =
    !submitting &&
    notional > 0 &&
    (sizing == null || sizing.shares >= 1) &&
    !(venue === "live_alpaca" && !liveConfirmed) &&
    overrideOk;

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <header>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">
          Trade {ticker || "a stock"}
        </h1>
        <p className="mt-2 text-sm text-ink-muted">
          Orders use settled buying power (not unsettled sale proceeds). Whole
          shares only. Tax is on realized profit - see{" "}
          <Link to="/tax" className="text-accent hover:underline">
            Tax ledger
          </Link>
          .
        </p>
      </header>

      {!ticker ? (
        <p className="text-sm text-ink-muted">
          Pick a stock from{" "}
          <Link to="/stocks/found" className="text-accent hover:underline">
            Found stocks
          </Link>
          .
        </p>
      ) : (
        <section className="space-y-4 border border-border bg-surface-raised/80 p-5">
          <p className="font-mono text-sm text-ink">
            {ticker}
            {price != null
              ? ` | last saved price $${price.toFixed(2)}`
              : " | price will be fetched at submit"}
          </p>

          {capital ? (
            <div className="border border-border bg-surface px-3 py-2 text-xs text-ink-muted">
              Buying power {String(capital.buying_power ?? "-")} | Settled cash{" "}
              {String(capital.settled_cash ?? "-")} | Unsettled proceeds{" "}
              {String(capital.unsettled_proceeds ?? "0")}
            </div>
          ) : null}

          {washBlock ? (
            <div className="space-y-2 border border-warning/40 bg-warning/10 px-3 py-3 text-sm">
              <p className="text-ink">{String(washBlock.message)}</p>
              <label className="block space-y-1 text-xs">
                <span className="uppercase tracking-[0.14em] text-ink-subtle">
                  Type override to proceed
                </span>
                <input
                  value={washOverride}
                  onChange={(e) => setWashOverride(e.target.value)}
                  placeholder={String(washBlock.override_phrase)}
                  className="w-full border border-border bg-surface px-3 py-2 font-mono text-sm text-ink"
                />
              </label>
            </div>
          ) : null}

          <label className="block space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Budget (USD)
            </span>
            <input
              type="number"
              min={1}
              step={1}
              value={notional}
              onChange={(e) => setNotional(Number(e.target.value) || 0)}
              className="w-full border border-border bg-surface px-3 py-2"
            />
          </label>

          {sizing ? (
            <div className="border border-border bg-surface px-3 py-3 text-sm text-ink">
              {sizing.shares >= 1 ? (
                <>
                  <p>
                    You will buy{" "}
                    <span className="font-mono font-medium">{sizing.shares}</span>{" "}
                    whole share{sizing.shares === 1 ? "" : "s"}
                  </p>
                  <p className="mt-1">
                    Estimated spend:{" "}
                    <span className="font-mono font-medium">
                      ${sizing.spend.toFixed(2)}
                    </span>
                    {sizing.leftover > 0 ? (
                      <span className="text-ink-muted">
                        {" "}
                        (${sizing.leftover.toFixed(2)} of budget unused)
                      </span>
                    ) : null}
                  </p>
                </>
              ) : (
                <p className="text-warning">
                  Budget ${notional.toFixed(2)} is below 1 share at $
                  {price?.toFixed(2)}. Increase the amount.
                </p>
              )}
            </div>
          ) : (
            <p className="text-xs text-ink-subtle">
              Spend preview appears once a price is available.
            </p>
          )}

          <fieldset className="space-y-2 text-sm">
            <legend className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Venue
            </legend>
            {(
              [
                ["paper_local", "Paper - local ledger (free, no broker)"],
                ["paper_alpaca", "Paper - Alpaca paper account"],
                ["live_alpaca", "Live - Alpaca real money"],
              ] as const
            ).map(([id, label]) => (
              <label key={id} className="flex items-center gap-2">
                <input
                  type="radio"
                  name="venue"
                  checked={venue === id}
                  onChange={() => {
                    setVenue(id);
                    if (id !== "live_alpaca") setLiveConfirmed(false);
                  }}
                />
                <span className={id === "live_alpaca" ? "text-danger" : "text-ink"}>
                  {label}
                </span>
              </label>
            ))}
          </fieldset>
          {venue === "live_alpaca" ? (
            <label className="flex items-start gap-2 text-sm text-danger">
              <input
                type="checkbox"
                checked={liveConfirmed}
                onChange={(e) => setLiveConfirmed(e.target.checked)}
              />
              I confirm this live order can spend real money.
            </label>
          ) : null}
          {error ? (
            <div className="border border-danger/40 bg-danger/10 px-3 py-2 text-sm">
              {error}
            </div>
          ) : null}
          {message ? (
            <div className="border border-success/40 bg-success/10 px-3 py-2 text-sm">
              {message}{" "}
              <Link
                to={`/stocks/view/${encodeURIComponent(ticker)}`}
                className="text-accent hover:underline"
              >
                View market
              </Link>{" "}
              <Link to="/stocks/portfolio" className="text-accent hover:underline">
                Open paper book
              </Link>{" "}
              <Link to="/tax" className="text-accent hover:underline">
                Tax ledger
              </Link>
            </div>
          ) : null}
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() => void submit()}
            className={cn(
              "border px-4 py-2 text-sm disabled:opacity-50",
              venue === "live_alpaca"
                ? "border-danger bg-danger text-white"
                : "border-accent bg-accent text-accent-fg",
            )}
          >
            {submitting
              ? "Submitting..."
              : venue === "live_alpaca"
                ? sizing && sizing.shares >= 1
                  ? `Buy ${sizing.shares} shares live (~$${sizing.spend.toFixed(2)})`
                  : "Place live order"
                : sizing && sizing.shares >= 1
                  ? `Buy ${sizing.shares} shares (~$${sizing.spend.toFixed(2)})`
                  : "Place paper order"}
          </button>
        </section>
      )}
    </div>
  );
}
