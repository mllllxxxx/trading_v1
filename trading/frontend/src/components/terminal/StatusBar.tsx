import { cn, fmtAge } from "@/components/terminal/primitives";

/**
 * StatusBar — last-scan / next-scan countdown for the bottom strip.
 *
 * Shows:
 *   - last decision/scan age (from server timestamp)
 *   - countdown to next scheduled cycle (interval-based)
 *   - poll status
 */
export function StatusBar({
  lastTs,
  scanIntervalS,
  running,
  refreshAgeMs,
}: {
  lastTs: string | null;
  scanIntervalS: number;
  running: boolean;
  refreshAgeMs: number;
}) {
  const lastAge = lastTs ? fmtAge(lastTs) : "—";
  // Best-effort "next" estimate: refreshAge is polling cadence; for trader
  // we approximate next scan as `interval - refreshAge`.
  const pollS = Math.max(1, Math.round(refreshAgeMs / 1000));
  const nextS = Math.max(0, scanIntervalS - pollS);
  const nextLabel = nextS >= 60 ? `${Math.floor(nextS / 60)}m${nextS % 60 ? ` ${nextS % 60}s` : ""}` : `${nextS}s`;
  return (
    <div className="flex items-center gap-3 font-mono text-[10px] text-ttcc-text-secondary tabular px-3">
      <span className="flex items-center gap-1">
        <span className="text-ttcc-text-muted">last scan</span>
        <span className="text-ttcc-text">{lastAge} ago</span>
      </span>
      <span className="text-ttcc-text-muted/40">·</span>
      <span className="flex items-center gap-1">
        <span className="text-ttcc-text-muted">next</span>
        <span className="text-ttcc-text">{nextLabel}</span>
      </span>
      <span className="text-ttcc-text-muted/40">·</span>
      <span className="flex items-center gap-1">
        <span className="text-ttcc-text-muted">poll</span>
        <span className={cn(running ? "text-ttcc-green" : "text-ttcc-text-muted")}>
          {running ? `${pollS}s` : "stopped"}
        </span>
      </span>
      <span className="text-ttcc-text-muted/40">·</span>
      <span className="flex items-center gap-1">
        <span className="text-ttcc-text-muted">interval</span>
        <span className="text-ttcc-text">{scanIntervalS}s</span>
      </span>
    </div>
  );
}
