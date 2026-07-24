import { MiniHistory, type MiniTrade } from "@/components/terminal/MiniHistory";
import { QuickActions } from "@/components/terminal/QuickActions";
import { StatusBar } from "@/components/terminal/StatusBar";

/**
 * BottomBar — sticky 36px strip below the main content.
 *
 * Layout: [mini history] [spacer] [quick actions] [status bar]
 *
 * Navigation now lives in the persistent left Sidebar, so this footer is
 * purely informational + quick actions.
 */
export function BottomBar({
  recentTrades,
  lastTs,
  scanIntervalS,
  running,
  refreshAgeMs,
}: {
  recentTrades: MiniTrade[];
  lastTs: string | null;
  scanIntervalS: number;
  running: boolean;
  refreshAgeMs: number;
}) {
  return (
    <footer className="tt-glass flex h-9 shrink-0 items-center gap-3 px-2">
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
