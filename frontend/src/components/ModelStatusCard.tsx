import type { ReactNode } from "react";
import { UsageBar } from "@/components/UsageBar";
import { cn } from "@/lib/cn";

interface ModelStatusCardProps {
  title: string;
  provider: string;
  modelName?: string | null;
  status: "available" | "unavailable" | "busy" | "waiting" | "offline";
  usagePercent?: number;
  usageDetail?: string;
  requests?: number;
  footer?: ReactNode;
}

const statusLabel: Record<ModelStatusCardProps["status"], string> = {
  available: "Available",
  unavailable: "Unavailable",
  busy: "Busy",
  waiting: "Waiting",
  offline: "Offline",
};

const statusDot: Record<ModelStatusCardProps["status"], string> = {
  available: "bg-success",
  unavailable: "bg-danger",
  busy: "bg-warning",
  waiting: "bg-ink-subtle",
  offline: "bg-ink-subtle",
};

export function ModelStatusCard({
  title,
  provider,
  modelName,
  status,
  usagePercent,
  usageDetail,
  requests,
  footer,
}: ModelStatusCardProps) {
  return (
    <article className="border border-border bg-surface-raised/80 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span
              className={cn("inline-block size-2 rounded-full", statusDot[status])}
              aria-hidden
            />
            <h3 className="text-sm font-semibold tracking-wide text-ink">
              {title}
            </h3>
          </div>
          <p className="mt-1 font-mono text-xs text-ink-subtle">
            {provider}
            {modelName ? ` / ${modelName}` : ""}
          </p>
        </div>
        <span className="text-[11px] uppercase tracking-[0.14em] text-ink-muted">
          {statusLabel[status]}
        </span>
      </div>

      {typeof usagePercent === "number" ? (
        <UsageBar
          value={usagePercent}
          label="Usage"
          detail={usageDetail ?? `${Math.round(usagePercent)}%`}
        />
      ) : (
        <p className="text-xs text-ink-subtle">Quota unknown (local / untracked)</p>
      )}

      {typeof requests === "number" ? (
        <p className="mt-3 font-mono text-xs text-ink-muted">
          Requests: {requests}
        </p>
      ) : null}

      {footer ? <div className="mt-3 border-t border-border pt-3">{footer}</div> : null}
    </article>
  );
}
