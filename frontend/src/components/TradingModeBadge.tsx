import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

export function TradingModeBadge() {
  const [label, setLabel] = useState("PAPER");
  const [isLive, setIsLive] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const mode = await api.portfolioMode();
      setLabel(mode.label);
      setIsLive(Boolean(mode.is_live));
    } catch {
      setLabel("PAPER (local)");
      setIsLive(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(id);
  }, [refresh]);

  return (
    <Link
      to="/settings"
      className={cn(
        "rounded-sm border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em]",
        isLive
          ? "border-danger/50 bg-danger/15 text-danger"
          : "border-success/40 bg-success/10 text-success",
      )}
      title="Trading mode - click Settings to change keys"
    >
      {label}
    </Link>
  );
}
