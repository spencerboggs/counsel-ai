import { Outlet } from "react-router-dom";
import { TradingModeBadge } from "@/components/TradingModeBadge";
import { UsageStrip } from "@/components/UsageStrip";
import { Sidebar } from "@/layouts/Sidebar";
import { useHealth } from "@/hooks/useHealth";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/cn";

export function AppShell() {
  const { health, error, loading } = useHealth();
  const { theme, setTheme } = useTheme();

  const ready = Boolean(health && health.status === "ok");
  const ollamaOk = Boolean(health?.ollama.reachable);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-surface-raised/90 px-4 backdrop-blur">
        <div className="flex items-center gap-3">
          <span className="font-display text-sm font-semibold tracking-[0.12em] text-ink">
            AI COUNSEL
          </span>
          <TradingModeBadge />
        </div>

        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-xs text-ink-muted">
            <span className="hidden sm:inline">Theme</span>
            <select
              value={theme}
              onChange={(e) =>
                setTheme(e.target.value as "light" | "dark" | "system")
              }
              className="border border-border bg-surface px-2 py-1 text-ink"
            >
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>

          <div className="flex items-center gap-2 text-xs">
            <span
              className={cn(
                "size-2 rounded-full",
                loading && "bg-warning",
                !loading && ready && "bg-success",
                !loading && !ready && "bg-danger",
              )}
            />
            <span className="text-ink-muted">
              {loading
                ? "Checking..."
                : ready
                  ? error
                    ? "Degraded"
                    : "System Ready"
                  : "Backend Offline"}
            </span>
            {ready ? (
              <span className="hidden font-mono text-ink-subtle md:inline">
                Ollama {ollamaOk ? "up" : "down"}
              </span>
            ) : null}
          </div>
        </div>
      </header>

      <UsageStrip />

      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
