import { NavLink } from "react-router-dom";
import {
  Bot,
  BriefcaseBusiness,
  ClipboardCheck,
  LayoutDashboard,
  Library,
  Receipt,
  Search,
  Settings,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/cn";

const nav = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  {
    label: "Stocks",
    children: [
      { to: "/stocks/discover", label: "Discover", icon: Search },
      { to: "/stocks/found", label: "Found stocks", icon: Library },
      { to: "/stocks/portfolio", label: "Paper book", icon: BriefcaseBusiness },
    ],
  },
  { to: "/autopilot", label: "Autopilot", icon: Bot },
  { to: "/tax", label: "Tax ledger", icon: Receipt },
  { to: "/compliance", label: "Compliance", icon: ClipboardCheck },
  { to: "/models", label: "Models", icon: Sparkles },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

export function Sidebar() {
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-surface-raised/70">
      <div className="border-b border-border px-4 py-5">
        <p className="font-display text-lg font-semibold tracking-[0.08em] text-ink">
          AI COUNSEL
        </p>
        <p className="mt-1 text-[11px] uppercase tracking-[0.18em] text-ink-subtle">
          Research terminal
        </p>
      </div>

      <nav className="flex-1 space-y-1 p-3">
        {nav.map((item) => {
          if ("children" in item) {
            return (
              <div key={item.label} className="pt-2">
                <p className="mb-1 px-2 text-[10px] uppercase tracking-[0.16em] text-ink-subtle">
                  {item.label}
                </p>
                <div className="space-y-0.5">
                  {item.children.map((child) => (
                    <SidebarLink
                      key={child.to}
                      to={child.to}
                      label={child.label}
                      icon={child.icon}
                    />
                  ))}
                </div>
              </div>
            );
          }

          return (
            <SidebarLink
              key={item.to}
              to={item.to}
              label={item.label}
              icon={item.icon}
              end={"end" in item ? item.end : false}
            />
          );
        })}
      </nav>
    </aside>
  );
}

function SidebarLink({
  to,
  label,
  icon: Icon,
  end,
}: {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  end?: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2.5 rounded-sm px-2.5 py-2 text-sm text-ink-muted transition-colors",
          isActive
            ? "bg-surface-muted text-ink"
            : "hover:bg-surface-muted/60 hover:text-ink",
        )
      }
    >
      <Icon className="size-4 shrink-0 opacity-80" />
      <span>{label}</span>
    </NavLink>
  );
}
