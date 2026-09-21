import { cn } from "@/lib/cn";

interface UsageBarProps {
  value: number;
  max?: number;
  label?: string;
  detail?: string;
  className?: string;
}

export function UsageBar({
  value,
  max = 100,
  label,
  detail,
  className,
}: UsageBarProps) {
  const pct = max <= 0 ? 0 : Math.max(0, Math.min(100, (value / max) * 100));

  return (
    <div className={cn("space-y-1.5", className)}>
      {(label || detail) && (
        <div className="flex items-baseline justify-between gap-3 text-xs">
          {label ? <span className="text-ink-muted">{label}</span> : <span />}
          {detail ? (
            <span className="font-mono text-ink-subtle">{detail}</span>
          ) : null}
        </div>
      )}
      <div className="h-2 overflow-hidden rounded-sm bg-surface-muted">
        <div
          className="h-full rounded-sm bg-accent transition-[width] duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
