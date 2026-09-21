import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import type { UsageResponse } from "@/types/api";

export function UsageStrip() {
  const [usage, setUsage] = useState<UsageResponse | null>(null);

  const refresh = useCallback(async () => {
    try {
      setUsage(await api.usage());
    } catch {
      setUsage(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 12000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const totals = useMemo(() => {
    const items = usage?.items ?? [];
    return {
      requests: items.reduce((sum, item) => sum + item.request_count, 0),
      prompt: items.reduce((sum, item) => sum + item.prompt_tokens, 0),
      completion: items.reduce((sum, item) => sum + item.completion_tokens, 0),
      models: items.length,
    };
  }, [usage]);

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border bg-surface-muted/40 px-4 py-1.5 text-[11px] text-ink-muted">
      <span className="uppercase tracking-[0.12em] text-ink-subtle">Usage</span>
      <span className="font-mono text-ink">
        {totals.requests} req | {totals.prompt}/{totals.completion} tok
      </span>
      <span className="text-ink-subtle" title="Prompt tokens in / completion tokens out">
        (in/out)
      </span>
      <span className="font-mono text-ink-subtle">{totals.models} model ids</span>
      <Link to="/models" className="ml-auto text-accent hover:underline">
        Details
      </Link>
    </div>
  );
}
