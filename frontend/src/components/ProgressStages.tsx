import type { ProgressStage } from "@/types/api";
import { cn } from "@/lib/cn";

interface ProgressStagesProps {
  stages: ProgressStage[];
  onSelect?: (stage: ProgressStage) => void;
  className?: string;
  /** denser layout for narrow sidebars */
  compact?: boolean;
  /** single row that wraps instead of a tall stack */
  horizontal?: boolean;
}

const glyph: Record<ProgressStage["status"], string> = {
  complete: "ok",
  active: "*",
  pending: "o",
  error: "!",
  skipped: "-",
};

export function ProgressStages({
  stages,
  onSelect,
  className,
  compact = false,
  horizontal = false,
}: ProgressStagesProps) {
  return (
    <ol
      className={cn(
        horizontal
          ? "grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6"
          : compact
            ? "space-y-0.5"
            : "space-y-2",
        className,
      )}
    >
      {stages.map((stage) => (
        <li key={stage.id}>
          <button
            type="button"
            onClick={() => onSelect?.(stage)}
            title={stage.detail || stage.label}
            className={cn(
              "flex w-full items-center gap-2 text-left transition-colors",
              horizontal
                ? cn(
                    "h-full border border-border bg-surface px-2.5 py-2",
                    stage.status === "active" && "border-accent bg-accent/10",
                    stage.status === "complete" && "border-success/40 bg-success/5",
                    stage.status === "error" && "border-danger/40 bg-danger/5",
                    stage.status === "skipped" && "border-warning/40 bg-warning/5",
                  )
                : cn(
                    "border border-transparent",
                    compact ? "px-1.5 py-1" : "items-start gap-3 px-2 py-1.5",
                    onSelect && "hover:border-border hover:bg-surface-muted/60",
                    stage.status === "active" && "border-border bg-surface-muted/40",
                  ),
            )}
          >
            <span
              className={cn(
                "w-3.5 shrink-0 font-mono text-xs",
                !compact && !horizontal && "mt-0.5 w-4 text-sm",
                stage.status === "complete" && "text-success",
                stage.status === "active" && "text-accent",
                stage.status === "pending" && "text-ink-subtle",
                stage.status === "error" && "text-danger",
                stage.status === "skipped" && "text-warning",
              )}
            >
              {glyph[stage.status]}
            </span>
            <span className="min-w-0 flex-1">
              <span
                className={cn(
                  "block text-ink",
                  compact || horizontal ? "truncate text-xs font-medium" : "text-sm",
                )}
              >
                {stage.label}
              </span>
              {horizontal && stage.detail ? (
                <span className="mt-0.5 block truncate text-[10px] text-ink-subtle">
                  {stage.detail}
                </span>
              ) : null}
              {!compact && !horizontal && stage.detail ? (
                <span className="mt-0.5 block text-xs text-ink-subtle">
                  {stage.detail}
                </span>
              ) : null}
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}
