import { Brain, ShieldAlert, ShieldCheck, Zap } from "lucide-react";
import { Link } from "react-router-dom";
import { cn, LiveDot, fmtAge } from "@/components/terminal/primitives";
import { Ticker, type TickerEntry } from "@/components/terminal/Ticker";

/**
 * TopBar — sticky header for the Trading Command Center.
 *
 * Layout: brand · ticker scroll · capital stats · kill switch · model name · live indicator
 */
export function TopBar({
  tickers,
  symbols,
  refreshAgeMs,
  running,
  killActive,
  modelName,
  capitalUsd,
  pnlTodayUsd,
  onKillToggle,
  onNavigateHome,
}: {
  tickers: TickerEntry[];
  symbols: string[];
  refreshAgeMs: number;
  running: boolean;
  killActive: boolean;
  modelName: string;
  capitalUsd: number;
  pnlTodayUsd: number;
  onKillToggle: () => void;
  onNavigateHome?: () => void;
}) {
  const pnlUp = pnlTodayUsd >= 0;
  return (
    <header className="flex items-center gap-0 h-10 border-b border-ttcc-border bg-ttcc-bg shrink-0">
      {/* Brand */}
      <div className="flex h-full items-center gap-2 border-r border-ttcc-border/60 bg-ttcc-surface px-3 shrink-0">
        <Link
          to="/trader"
          onClick={onNavigateHome}
          className="flex h-6 w-6 items-center justify-center rounded bg-ttcc-accent/15 text-ttcc-accent"
          title="Vibe-Trading Command Center"
        >
          <Zap className="h-3.5 w-3.5" />
        </Link>
        <div className="flex flex-col leading-none">
          <span className="text-[13px] font-bold tracking-tight text-ttcc-text">VIBE·TRADE</span>
          <span className="text-[9px] uppercase tracking-[0.12em] text-ttcc-text-secondary">command center</span>
        </div>
      </div>

      {/* Ticker scroll */}
      <Ticker tickers={tickers} symbols={symbols} />

      {/* Right cluster: stats + controls */}
      <div className="flex h-full items-center gap-1.5 border-l border-ttcc-border/60 bg-ttcc-surface px-3 shrink-0">
        {/* Capital */}
        <div className="flex items-center gap-1.5 rounded border border-ttcc-border bg-ttcc-surface-2 px-2 py-0.5" title="Current capital">
          <span className="text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-muted">cap</span>
          <span className="font-mono text-[11px] font-semibold text-ttcc-text tabular">
            ${capitalUsd.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </span>
        </div>

        {/* PnL today */}
        <div className={cn(
          "flex items-center gap-1.5 rounded border px-2 py-0.5",
          pnlUp
            ? "border-ttcc-green/40 bg-ttcc-green/10 text-ttcc-green"
            : "border-ttcc-red/40 bg-ttcc-red/10 text-ttcc-red"
        )} title="Today's PnL">
          <span className="text-[9px] font-semibold uppercase tracking-wider opacity-80">pnl</span>
          <span className="font-mono text-[11px] font-bold tabular">
            {pnlUp ? "+" : ""}{pnlTodayUsd.toFixed(2)}
          </span>
        </div>

        {/* Kill switch */}
        <button
          type="button"
          onClick={onKillToggle}
          className={cn(
            "flex items-center gap-1.5 rounded border px-2 py-0.5 transition-colors tt-card-hover",
            killActive
              ? "border-ttcc-red/60 bg-ttcc-red/15 text-ttcc-red"
              : "border-ttcc-green/40 bg-ttcc-green/10 text-ttcc-green"
          )}
          title={killActive ? "Kill switch armed — click to disarm" : "Arm kill switch"}
        >
          {killActive ? <ShieldAlert className="h-3 w-3" /> : <ShieldCheck className="h-3 w-3" />}
          <span className="text-[10px] font-bold uppercase tracking-wider tabular">
            {killActive ? "KILL" : "ARM"}
          </span>
          {killActive ? <span className="tt-live-dot !h-1.5 !w-1.5" /> : null}
        </button>

        {/* Model */}
        <div className="flex items-center gap-1.5 rounded border border-ttcc-border bg-ttcc-surface-2 px-2 py-0.5" title={`Model: ${modelName}`}>
          <Brain className="h-3 w-3 text-ttcc-blue" />
          <span className="font-mono text-[10px] text-ttcc-text-secondary tabular truncate max-w-[120px]">{modelName}</span>
        </div>

        {/* Refresh indicator */}
        <div className="flex items-center gap-1.5 rounded border border-ttcc-border bg-ttcc-surface-2 px-2 py-0.5" title="Polling status">
          <LiveDot idle={!running} />
          <span className="font-mono text-[10px] text-ttcc-text-secondary tabular">
            {running ? "LIVE" : "IDLE"}
          </span>
          <span className="text-ttcc-text-muted/40">·</span>
          <span className="font-mono text-[10px] text-ttcc-text-secondary tabular">
            {fmtAge(new Date(Date.now() - refreshAgeMs).toISOString())}
          </span>
        </div>
      </div>
    </header>
  );
}
