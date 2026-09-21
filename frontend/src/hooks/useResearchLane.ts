import { useCallback, useEffect, useState } from "react";
import {
  getStoredLane,
  normalizeLane,
  setStoredLane,
  subscribeLane,
  type ResearchLane,
} from "@/lib/lane";

/** Shared lane toggle for Discover and Found stocks (persisted). */
export function useResearchLane() {
  const [lane, setLaneState] = useState<ResearchLane>(() => getStoredLane());

  useEffect(() => subscribeLane(setLaneState), []);

  const setLane = useCallback((next: ResearchLane) => {
    setStoredLane(next);
    setLaneState(next);
  }, []);

  /** Sync from a discovery run's lane without fighting user clicks mid-edit. */
  const syncFromRun = useCallback((raw: unknown) => {
    const next = normalizeLane(raw);
    if (!next) return;
    setStoredLane(next);
    setLaneState(next);
  }, []);

  return { lane, setLane, syncFromRun } as const;
}
