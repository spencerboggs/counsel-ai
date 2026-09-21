import { cn } from "@/lib/cn";

interface ScoreCardProps {
  ticker?: string;
  score?: number | null;
  confidence?: number | null;
  signal?: string | null;
  panelScore?: number | null;
  panelSpread?: number | null;
  emptyMessage?: string;
  className?: string;
}

function outOf100(value: number) {
  return `${value.toFixed(1)}/100`;
}

export function ScoreCard({
  ticker,
  score,
  confidence,
  signal,
  panelScore,
  panelSpread,
  emptyMessage = "No score yet - select a candidate.",
  className,
}: ScoreCardProps) {
  const hasScore = typeof score === "number";
  const panelDiverges =
    hasScore &&
    typeof panelScore === "number" &&
    Math.abs(score - panelScore) >= 15;

  return (
    <article
      className={cn(
        "border border-border bg-surface-raised/80 p-5",
        className,
      )}
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
          Deterministic score
        </h3>
        {ticker ? (
          <span className="font-mono text-sm text-ink">{ticker}</span>
        ) : null}
      </div>

      {hasScore ? (
        <>
          <p className="font-mono text-4xl font-semibold tabular-nums text-score">
            {outOf100(score)}
          </p>
          <p className="mt-2 text-[11px] leading-snug text-ink-subtle">
            0/100 to 100/100 from evidence and market metrics. This is the value
            that ranks the list and drives Signal.
          </p>
          <div className="mt-3 space-y-2 text-xs text-ink-muted">
            {typeof confidence === "number" ? (
              <p>
                <span className="text-ink">Confidence</span>{" "}
                {Math.round(confidence * 100)}/100 - how complete the inputs
                were for that math.
              </p>
            ) : null}
            {signal ? (
              <p>
                <span className="text-ink">Signal</span> {signal} - final band
                from the deterministic score
                {" "}
                (Strong Interest {">="}80, Interesting {">="}65, Watch {">="}50,
                Cautious {">="}35, else Avoid / Defer).
              </p>
            ) : null}
            {typeof panelScore === "number" ? (
              <div className="space-y-1.5 border-t border-border/70 pt-2">
                <p>
                  <span className="text-ink">Panel</span> {outOf100(panelScore)}
                  {typeof panelSpread === "number"
                    ? ` | spread ${panelSpread.toFixed(1)} pts`
                    : ""}
                </p>
                <p className="text-[11px] leading-snug text-ink-subtle">
                  Also on a 0/100 to 100/100 scale, but it is only the average of
                  the three local LLM roles (fundamental, skeptic, counsel). It
                  never overrides Score or Signal. A low panel next to a high
                  score usually means the models disagree or are cautious - treat
                  it as a second opinion, not a veto.
                </p>
                {panelDiverges ? (
                  <p className="text-[11px] leading-snug text-warning">
                    Panel is meaningfully below Score here. Prefer the
                    deterministic {outOf100(score)} and Signal for ranking; read
                    the role notes below for why the models are cooler.
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        </>
      ) : (
        <p className="text-sm text-ink-muted">{emptyMessage}</p>
      )}
    </article>
  );
}
