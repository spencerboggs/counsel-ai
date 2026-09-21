import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

function money(value: unknown) {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "-";
  const sign = n > 0 ? "+" : "";
  return `${sign}$${n.toFixed(2)}`;
}

export function TaxLedgerPage() {
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [dispositions, setDispositions] = useState<Record<string, unknown>[]>(
    [],
  );
  const [lots, setLots] = useState<Record<string, unknown>[]>([]);
  const [blocks, setBlocks] = useState<Record<string, unknown>[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [purgeNote, setPurgeNote] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [sum, disp, openLots, wash] = await Promise.all([
        api.taxSummary(),
        api.taxDispositions(),
        api.taxLots(),
        api.taxWashBlocks(),
      ]);
      setSummary(sum);
      setDispositions(disp.items);
      setLots(openLots.items);
      setBlocks(wash.items);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load tax ledger");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const realized = (summary?.realized as Record<string, unknown>) || {};
  const capital = (summary?.capital as Record<string, unknown>) || {};

  async function requestPurge(entityType: string, entityId: string) {
    const phrase = `PURGE ${entityType.toUpperCase()} ${entityId}`;
    const reason = window.prompt(
      `Tax/trade history is permanent by default.\n\nSoft-flag only (never hard-delete).\nType a reason (>=20 chars), then you will confirm with:\n${phrase}`,
    );
    if (!reason || reason.trim().length < 20) {
      setPurgeNote("Purge cancelled - reason too short.");
      return;
    }
    const confirm = window.prompt(`Type exactly:\n${phrase}`);
    if (confirm !== phrase) {
      setPurgeNote("Purge cancelled - confirmation phrase mismatch.");
      return;
    }
    try {
      const result = await api.taxPurgeRequest({
        entity_type: entityType,
        entity_id: entityId,
        reason: reason.trim(),
        confirmation_phrase: phrase,
      });
      setPurgeNote(String(result.note || "Soft-flagged."));
      void refresh();
    } catch (err) {
      setPurgeNote(err instanceof ApiError ? err.message : "Purge failed");
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">
            Tax ledger
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-muted">
            Taxes are on <em>profit</em> (realized gain), not sale proceeds.
            Wash-sale windows hard-block repurchases. Fills and lots are
            append-only - purge only soft-flags with typed confirmation. Not tax
            advice; you remain responsible for IRS reporting.
          </p>
        </div>
        <div className="flex gap-3 text-sm">
          <Link to="/compliance" className="text-accent hover:underline">
            Compliance checklist
          </Link>
          <Link to="/stocks/portfolio" className="text-accent hover:underline">
            Paper book
          </Link>
        </div>
      </header>

      {error ? (
        <div className="border border-danger/40 bg-danger/10 px-4 py-3 text-sm">
          {error}
        </div>
      ) : null}
      {purgeNote ? (
        <div className="border border-border bg-surface-muted px-4 py-3 text-sm">
          {purgeNote}
        </div>
      ) : null}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="YTD realized (taxable profit)" value={money(realized.ytd_realized)} />
        <Stat label="Total realized" value={money(realized.total_realized)} />
        <Stat label="Gains / losses" value={`${money(realized.gains)} / ${money(realized.losses)}`} />
        <Stat label="Wash disallowed (tracked)" value={money(realized.wash_disallowed)} />
      </section>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Cash (ledger)" value={money(capital.cash)} />
        <Stat label="Settled cash" value={money(capital.settled_cash)} />
        <Stat label="Buying power" value={money(capital.buying_power)} />
        <Stat label="Unsettled proceeds" value={money(capital.unsettled_proceeds)} />
      </section>
      {capital.note ? (
        <p className="text-xs text-ink-subtle">{String(capital.note)}</p>
      ) : null}

      <section className="space-y-3">
        <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
          Wash-sale blocks (30-day window)
        </h2>
        {blocks.length === 0 ? (
          <p className="text-sm text-ink-muted">No active wash-sale blocks.</p>
        ) : (
          <div className="overflow-x-auto border border-border">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-muted text-xs uppercase tracking-[0.12em] text-ink-subtle">
                <tr>
                  <th className="px-3 py-2">Symbol</th>
                  <th className="px-3 py-2">Window</th>
                  <th className="px-3 py-2">Loss</th>
                  <th className="px-3 py-2">Override phrase</th>
                </tr>
              </thead>
              <tbody>
                {blocks.map((b) => (
                  <tr key={String(b.symbol)} className="border-t border-border">
                    <td className="px-3 py-2 font-mono">{String(b.symbol)}</td>
                    <td className="px-3 py-2 text-xs">
                      {String(b.window_start)} to {String(b.window_end)}
                    </td>
                    <td className="px-3 py-2 font-mono text-danger">
                      {money(b.loss_amount)}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {String(b.override_phrase)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
          Open tax lots
        </h2>
        {lots.length === 0 ? (
          <p className="text-sm text-ink-muted">No open lots.</p>
        ) : (
          <div className="overflow-x-auto border border-border">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-muted text-xs uppercase tracking-[0.12em] text-ink-subtle">
                <tr>
                  <th className="px-3 py-2">Symbol</th>
                  <th className="px-3 py-2">Qty</th>
                  <th className="px-3 py-2">Basis $/sh</th>
                  <th className="px-3 py-2">Acquired</th>
                  <th className="px-3 py-2">Wash adj</th>
                </tr>
              </thead>
              <tbody>
                {lots.map((lot) => (
                  <tr key={String(lot.id)} className="border-t border-border">
                    <td className="px-3 py-2 font-mono">{String(lot.symbol)}</td>
                    <td className="px-3 py-2 font-mono">{String(lot.qty_open)}</td>
                    <td className="px-3 py-2 font-mono">
                      $
                      {Number(
                        lot.adjusted_basis_per_share ?? lot.cost_basis_per_share,
                      ).toFixed(4)}
                    </td>
                    <td className="px-3 py-2 text-xs">{String(lot.acquired_at)}</td>
                    <td className="px-3 py-2">
                      {lot.wash_adjusted ? "yes" : " - "}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
          Dispositions (realized)
        </h2>
        {dispositions.length === 0 ? (
          <p className="text-sm text-ink-muted">No closed lots yet.</p>
        ) : (
          <div className="overflow-x-auto border border-border">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-muted text-xs uppercase tracking-[0.12em] text-ink-subtle">
                <tr>
                  <th className="px-3 py-2">Symbol</th>
                  <th className="px-3 py-2">Qty</th>
                  <th className="px-3 py-2">Proceeds</th>
                  <th className="px-3 py-2">Cost</th>
                  <th className="px-3 py-2">Realized</th>
                  <th className="px-3 py-2">Hold days</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {dispositions.map((d) => (
                  <tr key={String(d.id)} className="border-t border-border">
                    <td className="px-3 py-2 font-mono">{String(d.symbol)}</td>
                    <td className="px-3 py-2 font-mono">{String(d.qty)}</td>
                    <td className="px-3 py-2 font-mono">
                      ${Number(d.proceeds).toFixed(2)}
                    </td>
                    <td className="px-3 py-2 font-mono">
                      ${Number(d.cost).toFixed(2)}
                    </td>
                    <td
                      className={cn(
                        "px-3 py-2 font-mono",
                        Number(d.realized_gain) >= 0
                          ? "text-success"
                          : "text-danger",
                      )}
                    >
                      {money(d.realized_gain)}
                    </td>
                    <td className="px-3 py-2">{String(d.holding_days)}</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        className="text-xs text-ink-subtle underline"
                        onClick={() =>
                          void requestPurge("disposition", String(d.id))
                        }
                      >
                        Request soft-flag
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
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
