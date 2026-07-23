import { Menu } from "lucide-react";
import { MiniHistory, type MiniTrade } from "@/components/terminal/MiniHistory";
import { QuickActions } from "@/components/terminal/QuickActions";
import { StatusBar } from "@/components/terminal/StatusBar";
import { cn } from "@/components/terminal/primitives";

/**
 * BottomBar — sticky 40px strip below the main content.
 *
 * Layout: [nav] [mini history] [quick actions] [status]
 *
 * `onOpenNav` is the catch-all navigation button (left-most) that
 * surfaces every route. Keep it on the far left so the eye anchors
 * here first; quick actions and status follow.
 */
export function BottomBar({
  onOpenNav,
  recentTrades,
  lastTs,
  scanIntervalS,
  running,
  refreshAgeMs,
}: {
  onOpenNav: () => void;
  recentTrades: MiniTrade[];
  lastTs: string | null;
  scanIntervalS: number;
  running: boolean;
  refreshAgeMs: number;
}) {
  return (
    <footer className="tt-glass flex h-10 shrink-0 items-center justify-between gap-3 px-2">
      <button
        type="button"
        onClick={onOpenNav}
        className={cn(
          "tt-focus shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-ttcc-surface-2/50 px-2 py-1",
          "text-[10px] font-semibold uppercase tracking-wider text-ttcc-text-secondary",
          "hover:bg-ttcc-accent/10 hover:text-ttcc-accent transition-colors"
        )}
        title="Open navigation"
        aria-label="Open navigation"
      >
        <Menu className="h-3 w-3" />
        <span>nav</span>
      </button>
      <div className="flex min-w-0 flex-1 items-center">
        <MiniHistory trades={recentTrades} />
      </div>
      <div className="shrink-0">
        <QuickActions />
      </div>
      <div className="shrink-0">
        <StatusBar
          lastTs={lastTs}
          scanIntervalS={scanIntervalS}
          running={running}
          refreshAgeMs={refreshAgeMs}
        />
      </div>
    </footer>
  );
}
