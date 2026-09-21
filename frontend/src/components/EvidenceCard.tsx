import { ExternalLink } from "lucide-react";
import { UsageBar } from "@/components/UsageBar";
import { cn } from "@/lib/cn";

interface EvidenceCardProps {
  id?: string;
  claim?: string;
  sourceName?: string;
  sourceType?: string;
  sourceUrl?: string | null;
  publishedAt?: string | null;
  reliability?: number | null;
  usedBy?: string[];
  supportingData?: Record<string, string | number>;
  emptyMessage?: string;
  className?: string;
}

export function EvidenceCard({
  id,
  claim,
  sourceName,
  sourceType,
  sourceUrl,
  publishedAt,
  reliability,
  usedBy,
  supportingData,
  emptyMessage = "No evidence items yet.",
  className,
}: EvidenceCardProps) {
  if (!id || !claim) {
    return (
      <article
        className={cn(
          "border border-dashed border-border bg-surface-raised/40 p-5 text-sm text-ink-muted",
          className,
        )}
      >
        {emptyMessage}
      </article>
    );
  }

  return (
    <article className={cn("border border-border bg-surface-raised/80 p-5", className)}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="font-mono text-xs text-accent">{id}</span>
        {sourceType ? (
          <span className="text-[11px] uppercase tracking-[0.14em] text-ink-subtle">
            {sourceType}
          </span>
        ) : null}
      </div>

      <h3 className="text-base leading-snug text-ink">{claim}</h3>

      <div className="mt-4 space-y-1 text-sm text-ink-muted">
        {sourceName ? <p>Source: {sourceName}</p> : null}
        {publishedAt ? <p>Published: {publishedAt}</p> : null}
      </div>

      {typeof reliability === "number" ? (
        <div className="mt-4">
          <UsageBar
            value={reliability * 100}
            label="Reliability"
            detail={`${Math.round(reliability * 100)}%`}
          />
        </div>
      ) : null}

      {usedBy && usedBy.length > 0 ? (
        <p className="mt-4 text-xs text-ink-subtle">Used by: {usedBy.join(", ")}</p>
      ) : null}

      {supportingData && Object.keys(supportingData).length > 0 ? (
        <dl className="mt-4 grid grid-cols-2 gap-2 border-t border-border pt-3 font-mono text-xs">
          {Object.entries(supportingData).map(([key, value]) => (
            <div key={key}>
              <dt className="text-ink-subtle">{key}</dt>
              <dd className="text-ink">{String(value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {sourceUrl ? (
        <a
          href={sourceUrl}
          target="_blank"
          rel="noreferrer"
          className="mt-4 inline-flex items-center gap-1.5 text-xs text-accent hover:underline"
        >
          Open source <ExternalLink className="size-3" />
        </a>
      ) : null}
    </article>
  );
}
