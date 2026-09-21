import { cn } from "@/lib/cn";

interface SparklineProps {
  values: number[];
  className?: string;
  positive?: boolean | null;
}

/** Compact SVG line chart without a chart library. */
export function Sparkline({ values, className, positive }: SparklineProps) {
  if (values.length < 2) {
    return (
      <div
        className={cn(
          "flex h-16 items-center justify-center text-[10px] uppercase tracking-[0.14em] text-ink-subtle",
          className,
        )}
      >
        No series
      </div>
    );
  }

  const width = 320;
  const height = 72;
  const pad = 4;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values
    .map((v, i) => {
      const x = pad + (i / (values.length - 1)) * (width - pad * 2);
      const y = height - pad - ((v - min) / span) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const stroke =
    positive == null
      ? "var(--ink-muted)"
      : positive
        ? "var(--success)"
        : "var(--danger)";

  const first = values[0];
  const last = values[values.length - 1];
  const areaPositive = last >= first;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={cn("h-16 w-full", className)}
      preserveAspectRatio="none"
      aria-hidden
    >
      <polyline
        fill="none"
        stroke={stroke}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        points={points}
        opacity={0.95}
      />
      <polyline
        fill={areaPositive ? "var(--success)" : "var(--danger)"}
        fillOpacity="0.08"
        stroke="none"
        points={`${pad},${height - pad} ${points} ${width - pad},${height - pad}`}
      />
    </svg>
  );
}
