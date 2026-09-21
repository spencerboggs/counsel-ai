import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type {
  CandidateDetailResponse,
  DiscoveryRunRequest,
  DiscoveryRunResponse,
} from "@/types/api";

export function useDiscoveryRun(pollMs = 1500, explicitRunId?: string | null) {
  const [run, setRun] = useState<DiscoveryRunResponse | null>(null);
  const [detail, setDetail] = useState<CandidateDetailResponse | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [restored, setRestored] = useState(false);
  const pollRef = useRef<number | null>(null);
  const userStarted = useRef(false);
  const stoppedLocally = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const refresh = useCallback(async (runId: string) => {
    try {
      const data = await api.getDiscoveryRun(runId);
      // If the user already hit Stop, never revive a "running" poll race.
      if (stoppedLocally.current && data.status === "running") {
        setRun({ ...data, status: "cancelled" });
        stopPolling();
        return { ...data, status: "cancelled" as const };
      }
      setRun(data);
      setError(data.error ?? null);
      if (
        data.status === "complete" ||
        data.status === "error" ||
        data.status === "cancelled"
      ) {
        stopPolling();
      }
      return data;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load run");
      stopPolling();
      return null;
    }
  }, [stopPolling]);

  const watch = useCallback(
    (runId: string, status: string) => {
      stopPolling();
      if (status === "running" && !stoppedLocally.current) {
        pollRef.current = window.setInterval(() => {
          void refresh(runId);
        }, pollMs);
      }
    },
    [pollMs, refresh, stopPolling],
  );

  useEffect(() => {
    let cancelled = false;
    userStarted.current = false;
    stoppedLocally.current = false;
    setRestored(false);
    void (async () => {
      try {
        const data = explicitRunId
          ? await api.getDiscoveryRun(explicitRunId)
          : await api.latestDiscovery();
        if (cancelled || userStarted.current || !data) return;
        setRun(data);
        setError(data.error ?? null);
        setRestored(true);
        // Only resume polling for a truly live run (server marks orphans cancelled).
        if (data.status === "running") {
          watch(data.id, data.status);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Failed to restore run");
        }
      }
    })();
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [explicitRunId, stopPolling, watch]);

  const start = useCallback(
    async (params: DiscoveryRunRequest) => {
      userStarted.current = true;
      stoppedLocally.current = false;
      setStarting(true);
      setRestored(false);
      setError(null);
      setDetail(null);
      setSelectedTicker(null);
      stopPolling();
      try {
        const created = await api.startDiscovery(params);
        const initial = await refresh(created.run_id);
        setStarting(false);
        watch(created.run_id, "running");
        return initial;
      } catch (err) {
        setStarting(false);
        setError(
          err instanceof ApiError ? err.message : "Failed to start discovery",
        );
        return null;
      }
    },
    [refresh, stopPolling, watch],
  );

  const selectTicker = useCallback(
    async (ticker: string) => {
      if (!run) return;
      setSelectedTicker(ticker);
      try {
        const data = await api.getCandidateDetail(run.id, ticker);
        setDetail(data);
      } catch (err) {
        setDetail(null);
        setError(
          err instanceof ApiError ? err.message : "Failed to load candidate",
        );
      }
    },
    [run],
  );

  const cancel = useCallback(async () => {
    if (!run?.id || run.status !== "running") return;
    const runId = run.id;
    // Stop UI immediately - do not wait for the backend to finish current I/O.
    stoppedLocally.current = true;
    stopPolling();
    setRun((prev) => (prev ? { ...prev, status: "cancelled" } : prev));
    setError(null);
    try {
      await api.cancelDiscovery(runId);
      await refresh(runId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to cancel run");
    }
  }, [refresh, run, stopPolling]);

  const running = starting || (run?.status === "running" && !stoppedLocally.current);

  return {
    run,
    detail,
    selectedTicker,
    error,
    starting,
    running,
    restored,
    start,
    selectTicker,
    cancel,
    refresh,
  };
}
