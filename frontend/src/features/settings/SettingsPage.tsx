import { useCallback, useEffect, useState } from "react";
import { useTheme } from "@/hooks/useTheme";
import { api, ApiError } from "@/lib/api";
import type { SecretsStatus } from "@/types/api";
import { cn } from "@/lib/cn";

type Tab = "general" | "keys" | "trading";

type SecretField =
 | "ollama_base_url"
 | "openrouter_api_key"
 | "groq_api_key"
 | "gemini_api_key"
 | "alpaca_paper_key"
 | "alpaca_paper_secret"
 | "alpaca_live_key"
 | "alpaca_live_secret"
 | "fred_api_key";

const SECRET_FIELDS: SecretField[] = [
  "ollama_base_url",
  "openrouter_api_key",
  "groq_api_key",
  "gemini_api_key",
  "alpaca_paper_key",
  "alpaca_paper_secret",
  "alpaca_live_key",
  "alpaca_live_secret",
  "fred_api_key",
];

const EMPTY_DRAFT: Record<SecretField, string> = {
  ollama_base_url: "",
  openrouter_api_key: "",
  groq_api_key: "",
  gemini_api_key: "",
  alpaca_paper_key: "",
  alpaca_paper_secret: "",
  alpaca_live_key: "",
  alpaca_live_secret: "",
  fred_api_key: "",
};

const EMPTY_DIRTY: Record<SecretField, boolean> = {
  ollama_base_url: false,
  openrouter_api_key: false,
  groq_api_key: false,
  gemini_api_key: false,
  alpaca_paper_key: false,
  alpaca_paper_secret: false,
  alpaca_live_key: false,
  alpaca_live_secret: false,
  fred_api_key: false,
};

/** Shown in the input when a value is stored (never the real secret). */
const MASK = "****************";

function isConfigured(status: SecretsStatus | null, field: SecretField): boolean {
  return Boolean(status?.keys?.[field]);
}

function fieldSaveState(
  configured: boolean,
  dirty: boolean,
  draft: string,
): { label: string; tone: "saved" | "pending" | "empty" } {
  const typed = draft.trim().length > 0;
  if (dirty && typed) {
    return { label: "Not saved - click Save keys", tone: "pending" };
  }
  if (dirty && !typed && configured) {
    return {
      label: "Unchanged - leave blank to keep the saved value",
      tone: "saved",
    };
  }
  if (configured) {
    return { label: "Saved", tone: "saved" };
  }
  return { label: "Not set", tone: "empty" };
}

export function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const [tab, setTab] = useState<Tab>("keys");
  const [status, setStatus] = useState<SecretsStatus | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [dirty, setDirty] = useState(EMPTY_DIRTY);
  const [tradingMode, setTradingMode] = useState("paper_local");
  const [liveConfirmed, setLiveConfirmed] = useState(false);
  const [killDisabled, setKillDisabled] = useState(false);
  const [killBusy, setKillBusy] = useState(false);

  const applyStatus = useCallback((data: SecretsStatus) => {
    setStatus(data);
    setTradingMode(data.trading_mode || "paper_local");
    setLiveConfirmed(Boolean(data.live_trading_confirmed));
    setKillDisabled(Boolean(data.kill_switch?.trading_disabled));
    setDraft({
      ...EMPTY_DRAFT,
      // Non-secret URL can be shown in full after load.
      ollama_base_url: data.ollama_base_url ?? "",
    });
    setDirty({
      ...EMPTY_DIRTY,
      // URL is already the saved value - don't treat as pending.
      ollama_base_url: false,
    });
  }, []);

  const refresh = useCallback(async () => {
    try {
      const data = await api.secretsStatus();
      applyStatus(data);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load secrets status");
    }
  }, [applyStatus]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function updateField(field: SecretField, value: string) {
    setDraft((prev) => ({ ...prev, [field]: value }));
    setDirty((prev) => ({ ...prev, [field]: true }));
  }

  function beginEdit(field: SecretField) {
    if (dirty[field]) return;
    if (!isConfigured(status, field)) return;
    // Clear mask so the user can type a replacement; blank keeps existing on save.
    setDraft((prev) => ({ ...prev, [field]: "" }));
    setDirty((prev) => ({ ...prev, [field]: true }));
  }

  async function save() {
    setMessage(null);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        trading_mode: tradingMode,
        live_trading_confirmed: liveConfirmed,
      };
      for (const key of SECRET_FIELDS) {
        if (!dirty[key]) continue;
        const value = draft[key].trim();
        if (!value) continue;
        // Never persist a mask string if it somehow remains in the draft.
        if (value === MASK || /^[-]+$/.test(value)) continue;
        payload[key] = value;
      }
      const next = await api.updateSecrets(payload);
      applyStatus(next);
      setMessage("Saved. Keys are stored locally and never shown again.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Save failed");
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">
          Settings
        </h1>
        <p className="mt-2 text-sm text-ink-muted">
          Everything stays free by default. Paid or broker features only activate
          when you paste keys you obtained yourself.
        </p>
      </header>

      <div className="flex gap-2 border-b border-border pb-2 text-sm">
        {(
          [
            ["general", "General"],
            ["keys", "API keys"],
            ["trading", "Trading mode"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "px-3 py-1.5",
              tab === id
                ? "border border-border bg-surface-muted text-ink"
                : "text-ink-muted hover:text-ink",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {error ? (
        <div className="border border-danger/40 bg-danger/10 px-4 py-3 text-sm">{error}</div>
      ) : null}
      {message ? (
        <div className="border border-success/40 bg-success/10 px-4 py-3 text-sm">{message}</div>
      ) : null}

      {tab === "general" ? (
        <section className="space-y-4 border border-border bg-surface-raised/80 p-5">
          <label className="flex items-center justify-between gap-4 text-sm">
            <span>Theme</span>
            <select
              value={theme}
              onChange={(e) =>
                setTheme(e.target.value as "light" | "dark" | "system")
              }
              className="border border-border bg-surface px-3 py-1.5"
            >
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>
          <p className="font-mono text-xs text-ink-subtle">API {api.baseUrl}</p>
        </section>
      ) : null}

      {tab === "keys" ? (
        <section className="space-y-5 border border-border bg-surface-raised/80 p-5">
          <p className="text-sm text-ink-muted">
            Keys are written to a local gitignored file. Saved secrets show as
            dots in the field - the real values are never displayed again.
          </p>
          <SecretInput
            label="Ollama base URL"
            field="ollama_base_url"
            draft={draft.ollama_base_url}
            dirty={dirty.ollama_base_url}
            configured={isConfigured(status, "ollama_base_url")}
            placeholder="http://127.0.0.1:11434"
            inputType="text"
            hint="Local and free"
            onChange={updateField}
            onBeginEdit={beginEdit}
          />
          <SecretInput
            label="OpenRouter key (optional)"
            field="openrouter_api_key"
            draft={draft.openrouter_api_key}
            dirty={dirty.openrouter_api_key}
            configured={isConfigured(status, "openrouter_api_key")}
            hint="Disabled unless you paste a key"
            onChange={updateField}
            onBeginEdit={beginEdit}
          />
          <SecretInput
            label="Groq key (optional)"
            field="groq_api_key"
            draft={draft.groq_api_key}
            dirty={dirty.groq_api_key}
            configured={isConfigured(status, "groq_api_key")}
            onChange={updateField}
            onBeginEdit={beginEdit}
          />
          <SecretInput
            label="Gemini key (optional)"
            field="gemini_api_key"
            draft={draft.gemini_api_key}
            dirty={dirty.gemini_api_key}
            configured={isConfigured(status, "gemini_api_key")}
            onChange={updateField}
            onBeginEdit={beginEdit}
          />
          <SecretInput
            label="FRED API key (optional Autopilot macro)"
            field="fred_api_key"
            draft={draft.fred_api_key}
            dirty={dirty.fred_api_key}
            configured={isConfigured(status, "fred_api_key")}
            onChange={updateField}
            onBeginEdit={beginEdit}
          />
          <div className="border-t border-border pt-4">
            <h3 className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Alpaca (optional broker)
            </h3>
            <p className="mt-1 text-xs text-ink-muted">
              Paper keys are free from alpaca.markets. Live keys spend real money.
            </p>
            <div className="mt-3 space-y-3">
              <SecretInput
                label="Alpaca paper key"
                field="alpaca_paper_key"
                draft={draft.alpaca_paper_key}
                dirty={dirty.alpaca_paper_key}
                configured={isConfigured(status, "alpaca_paper_key")}
                onChange={updateField}
                onBeginEdit={beginEdit}
              />
              <SecretInput
                label="Alpaca paper secret"
                field="alpaca_paper_secret"
                draft={draft.alpaca_paper_secret}
                dirty={dirty.alpaca_paper_secret}
                configured={isConfigured(status, "alpaca_paper_secret")}
                onChange={updateField}
                onBeginEdit={beginEdit}
              />
              <SecretInput
                label="Alpaca live key"
                field="alpaca_live_key"
                draft={draft.alpaca_live_key}
                dirty={dirty.alpaca_live_key}
                configured={isConfigured(status, "alpaca_live_key")}
                onChange={updateField}
                onBeginEdit={beginEdit}
              />
              <SecretInput
                label="Alpaca live secret"
                field="alpaca_live_secret"
                draft={draft.alpaca_live_secret}
                dirty={dirty.alpaca_live_secret}
                configured={isConfigured(status, "alpaca_live_secret")}
                onChange={updateField}
                onBeginEdit={beginEdit}
              />
            </div>
          </div>
          <button
            type="button"
            onClick={() => void save()}
            className="border border-accent bg-accent px-4 py-2 text-sm text-accent-fg"
          >
            Save keys
          </button>
        </section>
      ) : null}

      {tab === "trading" ? (
        <section className="space-y-4 border border-border bg-surface-raised/80 p-5">
          <p className="text-sm text-ink-muted">
            Active backend:{" "}
            <span className="font-mono text-ink">
              {status?.active_backend ?? "paper_local"}
            </span>
          </p>
          <label className="block space-y-1.5 text-sm">
            <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Mode
            </span>
            <select
              value={tradingMode}
              onChange={(e) => setTradingMode(e.target.value)}
              className="w-full border border-border bg-surface px-3 py-2"
            >
              <option value="paper_local">Paper - local free ledger (default)</option>
              <option value="paper_alpaca">Paper - Alpaca paper account</option>
              <option value="live_alpaca">Live - Alpaca real money</option>
            </select>
          </label>
          {tradingMode === "live_alpaca" ? (
            <label className="flex items-start gap-2 text-sm text-danger">
              <input
                type="checkbox"
                checked={liveConfirmed}
                onChange={(e) => setLiveConfirmed(e.target.checked)}
              />
              I understand live mode places real brokerage orders with my Alpaca
              live keys.
            </label>
          ) : null}
          <ul className="space-y-2 text-xs text-ink-muted">
            {status
              ? Object.entries(status.notes).map(([key, note]) => (
                  <li key={key}>
                    <span className="font-mono text-ink">{key}</span>: {note}
                  </li>
                ))
              : null}
          </ul>
          <button
            type="button"
            onClick={() => void save()}
            className="border border-accent bg-accent px-4 py-2 text-sm text-accent-fg"
          >
            Save trading mode
          </button>

          <div className="border-t border-border pt-4 space-y-3">
            <h3 className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
              Emergency kill switch
            </h3>
            <p className="text-xs text-ink-muted">
              Blocks NEW orders and stops Autopilot. Does not liquidate positions
              or cancel broker open orders.
            </p>
            <p className="text-sm text-ink">
              Status:{" "}
              <span className={killDisabled ? "text-danger" : "text-success"}>
                {killDisabled ? "DISABLED (no new trades)" : "Enabled"}
              </span>
            </p>
            <button
              type="button"
              disabled={killBusy}
              onClick={() => {
                void (async () => {
                  setKillBusy(true);
                  try {
                    await api.setKillSwitch(!killDisabled);
                    await refresh();
                    setMessage(
                      !killDisabled
                        ? "Kill switch ON - trading halted."
                        : "Kill switch OFF - trading allowed again.",
                    );
                  } catch (err) {
                    setError(
                      err instanceof ApiError
                        ? err.message
                        : "Kill switch update failed",
                    );
                  } finally {
                    setKillBusy(false);
                  }
                })();
              }}
              className={cn(
                "border px-4 py-2 text-sm",
                killDisabled
                  ? "border-success/40 bg-success/10 text-success"
                  : "border-danger/40 bg-danger/10 text-danger",
              )}
            >
              {killDisabled ? "Re-enable trading" : "Disable all new trades"}
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function SecretInput({
  label,
  field,
  draft,
  dirty,
  configured,
  onChange,
  onBeginEdit,
  placeholder,
  hint,
  inputType = "password",
}: {
  label: string;
  field: SecretField;
  draft: string;
  dirty: boolean;
  configured: boolean;
  onChange: (field: SecretField, value: string) => void;
  onBeginEdit: (field: SecretField) => void;
  placeholder?: string;
  hint?: string;
  inputType?: "text" | "password";
}) {
  const showMask = configured && !dirty && inputType === "password";
  const showStoredUrl = configured && !dirty && inputType === "text";
  const value = showMask ? MASK : draft;
  const state = fieldSaveState(configured, dirty, draft);

  return (
    <label className="block space-y-1.5 text-sm">
      <span className="text-xs uppercase tracking-[0.14em] text-ink-subtle">
        {label}
      </span>
      <input
        type={inputType}
        autoComplete="off"
        spellCheck={false}
        value={value}
        placeholder={
          showStoredUrl || showMask
            ? undefined
            : placeholder ?? (configured ? undefined : "leave blank")
        }
        onFocus={() => {
          if (inputType === "password") onBeginEdit(field);
        }}
        onChange={(e) => onChange(field, e.target.value)}
        className="w-full border border-border bg-surface px-3 py-2 font-mono text-ink"
      />
      <span
        className={cn(
          "block text-xs",
          state.tone === "saved" && "text-success",
          state.tone === "pending" && "text-warning",
          state.tone === "empty" && "text-ink-subtle",
        )}
      >
        {state.label}
      </span>
      {hint ? <span className="block text-xs text-ink-subtle">{hint}</span> : null}
    </label>
  );
}
