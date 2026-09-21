import { ProgressStages, ScoreCard } from "@/components";
import { useHealth } from "@/hooks/useHealth";
import { api } from "@/lib/api";

export function DashboardPage() {
  const { health, error, loading } = useHealth();

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">
          Dashboard
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-muted">
          Infrastructure status for the local research backend. Discovery scoring
          and multi-agent counsel ship in later slices.
        </p>
      </header>

      <section className="grid gap-4 md:grid-cols-2">
        <article className="border border-border bg-surface-raised/80 p-5">
          <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
            Backend
          </h2>
          <p className="mt-3 font-mono text-sm text-ink">
            {loading
              ? "Checking..."
              : health
                ? `v${health.version} | ${health.status}`
                : error ?? "Offline"}
          </p>
          <p className="mt-2 font-mono text-xs text-ink-subtle">{api.baseUrl}</p>
        </article>

        <article className="border border-border bg-surface-raised/80 p-5">
          <h2 className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
            Ollama
          </h2>
          <p className="mt-3 font-mono text-sm text-ink">
            {health?.ollama.reachable
              ? `${health.ollama.model_count} model(s) discovered`
              : health?.ollama.enabled
                ? "Enabled but unreachable"
                : "Disabled in config"}
          </p>
          <p className="mt-2 font-mono text-xs text-ink-subtle">
            {health?.ollama.base_url ?? "-"}
          </p>
        </article>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <ScoreCard />
        <div className="border border-border bg-surface-raised/80 p-5">
          <h2 className="mb-3 text-xs uppercase tracking-[0.16em] text-ink-subtle">
            Pipeline preview
          </h2>
          <ProgressStages
            stages={[
              { id: "universe", label: "Universe loaded", status: "pending" },
              { id: "screen", label: "Initial screening", status: "pending" },
              { id: "research", label: "Candidate research", status: "pending" },
              { id: "score", label: "Final scoring", status: "pending" },
            ]}
          />
        </div>
      </section>
    </div>
  );
}
