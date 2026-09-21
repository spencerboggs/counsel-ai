/** Discovery signal bands from strongest to weakest. */
export const SIGNAL_ORDER = [
  "Strong Interest",
  "Interesting",
  "Watch",
  "Cautious",
  "Avoid / Defer",
] as const;

export type DiscoverySignal = (typeof SIGNAL_ORDER)[number];

const SIGNAL_RANK: Record<string, number> = Object.fromEntries(
  SIGNAL_ORDER.map((label, index) => [label, SIGNAL_ORDER.length - index]),
);

/** Higher = stronger interest. Unknown labels sort last. */
export function signalRank(signal: string | null | undefined): number {
  if (!signal) return 0;
  return SIGNAL_RANK[signal] ?? 0;
}

export function compareSignals(
  a: string | null | undefined,
  b: string | null | undefined,
  dir: "asc" | "desc" = "desc",
): number {
  const diff = signalRank(a) - signalRank(b);
  if (diff !== 0) return dir === "asc" ? diff : -diff;
  return String(a ?? "").localeCompare(String(b ?? ""));
}

/** Filter dropdown: known hierarchy first, then any odd leftovers. */
export function orderedSignalOptions(present: Iterable<string>): string[] {
  const set = new Set(present);
  const ordered = SIGNAL_ORDER.filter((s) => set.has(s));
  const extras = Array.from(set)
    .filter((s) => !SIGNAL_RANK[s])
    .sort((a, b) => a.localeCompare(b));
  return ["all", ...ordered, ...extras];
}
