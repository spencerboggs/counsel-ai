import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { HealthResponse } from "@/types/api";

export function useHealth(pollMs = 15000) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await api.health();
      setHealth(data);
      setError(null);
    } catch (err) {
      setHealth(null);
      setError(err instanceof ApiError ? err.message : "Health check failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), pollMs);
    return () => window.clearInterval(id);
  }, [pollMs, refresh]);

  return { health, error, loading, refresh };
}
