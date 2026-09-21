/** Shared Invest / Day trade / Swing lane for Discover + Found stocks. */

export type ResearchLane = "invest" | "daytrade" | "swing";

const STORAGE_KEY = "ai-counsel.research-lane";
const CHANGE_EVENT = "ai-counsel:research-lane";

export function getStoredLane(): ResearchLane {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === "daytrade" || value === "swing") return value;
    return "invest";
  } catch {
    return "invest";
  }
}

export function setStoredLane(lane: ResearchLane): void {
  try {
    localStorage.setItem(STORAGE_KEY, lane);
  } catch {
    /* private mode / quota */
  }
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: lane }));
}

export function normalizeLane(value: unknown): ResearchLane | null {
  if (value === "daytrade" || value === "invest" || value === "swing") {
    return value;
  }
  return null;
}

export function laneLabel(lane: ResearchLane): string {
  if (lane === "daytrade") return "Day trade";
  if (lane === "swing") return "Swing 1-7d";
  return "Invest";
}

export function subscribeLane(listener: (lane: ResearchLane) => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) listener(getStoredLane());
  };
  const onCustom = (event: Event) => {
    const detail = (event as CustomEvent<ResearchLane>).detail;
    listener(normalizeLane(detail) ?? getStoredLane());
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(CHANGE_EVENT, onCustom);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(CHANGE_EVENT, onCustom);
  };
}
