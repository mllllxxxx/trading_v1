import { Link } from "react-router-dom";
import { Beaker, BookOpen, FileSpreadsheet, Play } from "lucide-react";
import { cn } from "@/components/terminal/primitives";

type QuickAction = {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  hint?: string;
};

/**
 * QuickActions — bottom-bar shortcut row linking to heavy research flows
 * that live outside the terminal center. Each one is a plain <Link> so
 * router navigation just works (terminal shell stays mounted).
 */
export function QuickActions() {
  const actions: QuickAction[] = [
    { to: "/agent?prompt=" + encodeURIComponent("Open a manual paper-trade ticket for the current market"), label: "Manual Trade", icon: Play, hint: "/agent" },
    { to: "/alpha-zoo/bench", label: "Alpha Bench", icon: Beaker, hint: "/alpha-zoo" },
    { to: "/agent?prompt=" + encodeURIComponent("Run a backtest on the latest alpha"), label: "Backtest", icon: FileSpreadsheet, hint: "/agent" },
    { to: "/trader/history", label: "Journal", icon: BookOpen, hint: "/trader/history" },
  ];

  return (
    <div className="flex items-center gap-1.5">
      {actions.map(({ to, label, icon: Icon, hint }) => (
        <Link
          key={to}
          to={to}
          className={cn(
            "group flex items-center gap-1.5 rounded-lg px-2.5 py-1",
            "text-[11px] font-semibold uppercase tracking-wider text-ttcc-text-secondary",
            "hover:bg-ttcc-blue/10 hover:text-ttcc-blue hover:shadow-tt-sm transition-all duration-150"
          )}
          title={hint}
        >
          <Icon className="h-3.5 w-3.5" />
          <span>{label}</span>
        </Link>
      ))}
    </div>
  );
}
