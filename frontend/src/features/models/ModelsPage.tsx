import { useCallback, useEffect, useMemo, useState } from "react";
import { ModelStatusCard, DataTable } from "@/components";
import { api, ApiError } from "@/lib/api";
import type { ModelsResponse, UsageResponse } from "@/types/api";

export function ModelsPage() {
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [modelsRes, usageRes] = await Promise.all([
        api.models(),
        api.usage(),
      ]);
      setModels(modelsRes);
      setUsage(usageRes);
      setError(null);
    } catch (err) {
      setModels(null);
      setUsage(null);
      setError(
        err instanceof ApiError
          ? err.message
          : "Failed to load models from backend",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const usageById = useMemo(() => {
    const map = new Map<string, NonNullable<UsageResponse["items"]>[number]>();
    usage?.items.forEach((item) => map.set(item.model_id, item));
    return map;
  }, [usage]);

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">
            Models
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-muted">
            Registry plus local Ollama discovery. Token columns are{" "}
            <strong>in/out</strong> (prompt tokens sent / completion tokens
            returned). Local Ollama has no dollar cost.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          className="border border-border bg-surface-muted px-3 py-1.5 text-sm text-ink hover:bg-surface"
        >
          Refresh
        </button>
      </header>

      {error ? (
        <div className="border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-ink">
          {error}. Start the FastAPI backend and ensure Ollama is running if you
          expect local models.
        </div>
      ) : null}

      {loading && !models ? (
        <p className="text-sm text-ink-muted">Loading model registry...</p>
      ) : null}

      {models ? (
        <>
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
                Registry
              </h2>
              <span className="font-mono text-xs text-ink-subtle">
                Ollama {models.ollama_available ? "reachable" : "offline"}
              </span>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {models.registry.map((entry) => {
                const u = usageById.get(entry.id);
                const status = !models.ollama_available
                  ? "offline"
                  : entry.available
                    ? "available"
                    : "unavailable";
                return (
                  <ModelStatusCard
                    key={entry.id}
                    title={entry.id}
                    provider={entry.provider}
                    modelName={entry.resolved_model ?? entry.model}
                    status={status}
                    requests={u?.request_count}
                    footer={
                      <p className="text-xs text-ink-subtle">
                        Roles: {entry.roles.join(", ") || "none"}
                      </p>
                    }
                  />
                );
              })}
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-xs uppercase tracking-[0.16em] text-ink-subtle">
              Discovered (Ollama)
            </h2>
            <DataTable
              columns={[
                {
                  key: "name",
                  header: "Model",
                  className: "font-mono",
                  render: (row) => row.name,
                },
                {
                  key: "provider",
                  header: "Provider",
                  render: (row) => row.provider,
                },
              ]}
              rows={models.discovered}
              getRowId={(row) => row.name}
              emptyMessage={
                models.ollama_available
                  ? "Ollama is up but no models are installed."
                  : "No models discovered - is Ollama running?"
              }
            />
          </section>

          <section>
            <h2 className="mb-3 text-xs uppercase tracking-[0.16em] text-ink-subtle">
              Usage ledger
            </h2>
            <DataTable
              columns={[
                {
                  key: "model_id",
                  header: "ID",
                  className: "font-mono",
                  render: (row) => row.model_id,
                },
                {
                  key: "requests",
                  header: "Requests",
                  className: "font-mono",
                  render: (row) => String(row.request_count),
                },
                {
                  key: "tokens",
                  header: "Tokens in/out",
                  className: "font-mono",
                  render: (row) =>
                    `${row.prompt_tokens}/${row.completion_tokens}`,
                },
              ]}
              rows={usage?.items ?? []}
              getRowId={(row) => row.model_id}
              emptyMessage="No usage recorded yet."
            />
          </section>
        </>
      ) : null}
    </div>
  );
}
