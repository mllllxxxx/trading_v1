import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  Banknote,
  Brain,
  Cpu,
  GaugeCircle,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  Wallet,
  Power,
  Settings as SettingsIcon,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import {
  MetricCard,
  NumberCell,
  PanelLabel,
  PillBadge,
  fmtPct,
  useFlashClass,
  cn,
} from "@/components/terminal/primitives";

/**
 * LeftPanel — fixed-width metrics sidebar.
 * Shows: total PnL · capital · winrate · open positions · system status ·
 *        kill switch · symbols tracked · model · last update · LLM spend.
 *
 * Settings block collapses to keep the dense layout scannable.
 */
export function LeftPanel({
  totalPnl,
  currentCapital,
  startingCapital,
  winrate,
  wins,
  losses,
  totalTrades,
  consecutiveLosses,
  openPositions,
  maxPositions = 3,
  symbols,
  modelName,
  avgLatency,
  recentDecisionCount,
  lastUpdate,
  running,
  killActive,
  cost,
  onKillToggle,
}: {
  totalPnl: number;
  currentCapital: number;
  startingCapital: number;
  winrate: number;
  wins: number;
  losses: number;
  totalTrades: number;
  consecutiveLosses: number;
  openPositions: number;
  maxPositions?: number;
  symbols: string[];
  modelName: string;
  avgLatency: string;
  recentDecisionCount: number;
  lastUpdate: string | null;
  running: boolean;
  killActive: boolean;
  cost?: {
    cost_usd: number;
    cap_usd: number;
    calls: number;
    monthly_cost_usd: number;
    pct_of_cap: number;
    cap_reached: boolean;
  } | null;
  onKillToggle: () => void;
}) {
  const pnlFlashCls = useFlashClass(totalPnl);
  const isUp = totalPnl >= 0;
  const capitalPnlPct = startingCapital > 0 ? (totalPnl / startingCapital) * 100 : 0;
  const openTone = openPositions > 0 ? "bull" : "muted";
  const wrTone = winrate >= 50 ? "bull" : "muted";

  const [showSettings, setShowSettings] = useState(false);

  return (
    <aside className="flex w-[260px] shrink-0 flex-col gap-1.5 overflow-y-auto bg-ttcc-bg p-2 border-r border-ttcc-border">
      {/* Total PnL */}
      <MetricCard
        label="Total PnL"
        icon={Banknote}
        tone={isUp ? "bull" : "bear"}
      >
        <div className={cn("rounded px-2 py-1.5 -mx-0.5", pnlFlashCls)}>
          <div className={cn(
            "font-mono text-[26px] font-bold leading-none tabular tracking-tight",
            isUp ? "text-ttcc-green" : "text-ttcc-red"
          )}>
            {isUp ? "+" : ""}{totalPnl.toFixed(2)}
            <span className="ml-1 text-[11px] font-medium text-ttcc-text-secondary">USD</span>
          </div>
          <div className="mt-1.5 flex items-center gap-2 text-[10px] tabular">
            <span className={cn(
              "inline-flex items-center gap-0.5 rounded border px-1.5 py-0.5 font-mono font-semibold",
              isUp ? "border-ttcc-green/40 bg-ttcc-green/10 text-ttcc-green"
              : "border-ttcc-red/40 bg-ttcc-red/10 text-ttcc-red"
            )}>
              {isUp ? "▲" : "▼"}{capitalPnlPct.toFixed(2)}%
            </span>
            <span className="text-ttcc-text-secondary">vs start ${startingCapital.toFixed(0)}</span>
          </div>
        </div>
      </MetricCard>

      <div className="grid grid-cols-2 gap-1.5">
        <MetricCard label="Capital" icon={Wallet} dense tone="muted">
          <NumberCell value={`$${currentCapital.toFixed(2)}`} size="lg" bold />
          <div className="mt-1 flex items-baseline justify-between text-[10px] tabular">
            <span className="text-ttcc-text-secondary">since start</span>
            <span className={cn("font-mono", isUp ? "text-ttcc-green" : "text-ttcc-red")}>
              {isUp ? "+" : ""}{totalPnl.toFixed(2)}
            </span>
          </div>
        </MetricCard>

        <MetricCard label="Winrate" icon={GaugeCircle} dense tone={wrTone}>
          <NumberCell
            value={fmtPct(winrate)}
            size="lg"
            bold
            tone={winrate >= 50 ? "bull" : "default"}
          />
          <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-ttcc-surface-2">
            <div
              className="h-full bg-ttcc-green transition-all duration-300"
              style={{ width: `${Math.min(100, winrate)}%` }}
            />
          </div>
          <div className="mt-1 flex justify-between text-[10px] tabular text-ttcc-text-secondary">
            <span>
              <span className="text-ttcc-green">{wins}W</span>
              <span className="text-ttcc-text-muted">/</span>
              <span className="text-ttcc-red">{losses}L</span>
            </span>
            <span>{totalTrades} total</span>
          </div>
        </MetricCard>
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        <MetricCard label="Open" icon={Activity} dense tone={openTone}>
          <div className="flex items-baseline gap-1">
            <NumberCell
              value={openPositions}
              size="lg"
              bold
              tone={openPositions > 0 ? "bull" : "muted"}
            />
            <span className="font-mono text-[10px] text-ttcc-text-muted tabular">/ {maxPositions}</span>
          </div>
          <div className="mt-1 text-[10px] text-ttcc-text-secondary tabular">
            {openPositions === 0 ? "idle" : openPositions === maxPositions ? "at cap" : `${maxPositions - openPositions} slot open`}
          </div>
        </MetricCard>

        <MetricCard label="Loss streak" dense tone={consecutiveLosses > 0 ? "bear" : "muted"} icon={TrendingDown}>
          <NumberCell
            value={consecutiveLosses > 0 ? `${consecutiveLosses}` : "—"}
            size="lg"
            bold
            tone={consecutiveLosses >= 3 ? "bear" : "default"}
          />
          <div className="mt-1 text-[10px] text-ttcc-text-secondary tabular">
            {consecutiveLosses >= 3 ? "⚠ cool-down likely" : "healthy"}
          </div>
        </MetricCard>
      </div>

      {/* SYSTEM section */}
      <div className="mt-2">
        <PanelLabel icon={Power} tone="muted">System</PanelLabel>
        <div className="mt-1.5 flex flex-col gap-1.5">
          <MetricCard label="Kill switch" dense tone={killActive ? "bear" : "bull"}>
            <button
              type="button"
              onClick={onKillToggle}
              className={cn(
                "flex w-full items-center justify-between rounded border px-2 py-1 transition-colors",
                killActive
                  ? "border-ttcc-red/60 bg-ttcc-red/15 text-ttcc-red tt-kill-armed"
                  : "border-ttcc-green/40 bg-ttcc-green/10 text-ttcc-green hover:bg-ttcc-green/15"
              )}
            >
              <span className="flex items-center gap-1.5">
                {killActive ? <ShieldAlert className="h-3 w-3" /> : <ShieldCheck className="h-3 w-3" />}
                <span className="font-mono text-[10px] font-semibold uppercase tracking-wider">
                  {killActive ? "active · halted" : "armed"}
                </span>
              </span>
              <span className="font-mono text-[10px] tabular">
                {killActive ? "STOP" : "GO"}
              </span>
            </button>
          </MetricCard>

          <MetricCard label="Symbols tracked" dense tone="muted">
            <div className="flex flex-wrap gap-1">
              {symbols.slice(0, 10).map((s) => (
                <span
                  key={s}
                  className="rounded border border-ttcc-border bg-ttcc-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-ttcc-text-secondary"
                >
                  {s.replace("-USDT", "")}
                </span>
              ))}
              {symbols.length > 10 ? (
                <span className="font-mono text-[10px] text-ttcc-text-muted">+{symbols.length - 10}</span>
              ) : null}
            </div>
            <div className="mt-1 text-[10px] text-ttcc-text-secondary tabular">
              {symbols.length} active
            </div>
          </MetricCard>

          <MetricCard label="Model" dense tone="muted" icon={Brain}>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[11px] font-medium tabular text-ttcc-text truncate">{modelName}</span>
            </div>
            <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-0.5 text-[10px] tabular">
              <span className="text-ttcc-text-secondary">latency</span>
              <span className="text-right font-mono text-ttcc-text">{avgLatency}</span>
              <span className="text-ttcc-text-secondary">decisions · today</span>
              <span className="text-right font-mono text-ttcc-text">{recentDecisionCount}</span>
              <span className="text-ttcc-text-secondary">last update</span>
              <span className="text-right font-mono text-ttcc-text">
                {lastUpdate ? lastUpdate.substring(11, 19) : "—"}
              </span>
            </div>
          </MetricCard>

          <MetricCard label="LLM spend" dense tone={cost?.cap_reached ? "bear" : (cost?.pct_of_cap ?? 0) >= 80 ? "warn" : "muted"} icon={Cpu}>
            <div className="flex items-baseline justify-between">
              <span className="font-mono text-base font-bold tabular text-ttcc-text leading-none">
                ${cost?.cost_usd?.toFixed(4) ?? "0.0000"}
              </span>
              <span className="font-mono text-[10px] tabular text-ttcc-text-secondary">
                / ${cost?.cap_usd?.toFixed(2) ?? "0.10"}
              </span>
            </div>
            <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-ttcc-surface-2">
              <div
                className={cn(
                  "h-full transition-all",
                  cost?.cap_reached
                    ? "bg-ttcc-red"
                    : (cost?.pct_of_cap ?? 0) >= 80
                    ? "bg-ttcc-yellow"
                    : "bg-ttcc-green"
                )}
                style={{ width: `${Math.min(100, cost?.pct_of_cap ?? 0)}%` }}
              />
            </div>
            <div className="mt-1 flex justify-between text-[10px] tabular text-ttcc-text-secondary">
              <span>{cost?.calls ?? 0} calls</span>
              <span>${cost?.monthly_cost_usd?.toFixed(2) ?? "0.00"} / mo</span>
            </div>
          </MetricCard>
        </div>
      </div>

      {/* SETTINGS collapse */}
      <div className="mt-2">
        <button
          type="button"
          onClick={() => setShowSettings((v) => !v)}
          className="flex w-full items-center justify-between gap-2 rounded border border-ttcc-border bg-ttcc-surface px-2 py-1.5 hover:border-ttcc-text-secondary/40 transition-colors"
        >
          <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">
            {showSettings ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            <SettingsIcon className="h-3 w-3" />
            Settings
          </span>
        </button>
        {showSettings ? (
          <div className="mt-1.5 flex flex-col gap-1 rounded border border-ttcc-border bg-ttcc-surface p-2 text-[11px]">
            <Link
              to="/settings"
              className="flex items-center justify-between rounded px-2 py-1 hover:bg-ttcc-surface-2 transition-colors"
            >
              <span className="text-ttcc-text">LLM settings</span>
              <span className="font-mono text-[10px] text-ttcc-text-muted">→</span>
            </Link>
            <Link
              to="/runtime"
              className="flex items-center justify-between rounded px-2 py-1 hover:bg-ttcc-surface-2 transition-colors"
            >
              <span className="text-ttcc-text">Runtime monitor</span>
              <span className="font-mono text-[10px] text-ttcc-text-muted">→</span>
            </Link>
            <Link
              to="/correlation"
              className="flex items-center justify-between rounded px-2 py-1 hover:bg-ttcc-surface-2 transition-colors"
            >
              <span className="text-ttcc-text">Correlation matrix</span>
              <span className="font-mono text-[10px] text-ttcc-text-muted">→</span>
            </Link>
            <div className="mt-1 flex items-center justify-between px-2 py-1">
              <span className="text-ttcc-text-secondary">Polling</span>
              <PillBadge tone={running ? "ok" : "neutral"} mono>{running ? "5s · live" : "stopped"}</PillBadge>
            </div>
            <div className="flex items-center justify-between px-2 py-1">
              <span className="text-ttcc-text-secondary">Ticker</span>
              <span className="font-mono text-[10px] tabular text-ttcc-text-muted">10s</span>
            </div>
          </div>
        ) : null}
      </div>

      <div className="mt-2 px-2 text-[9px] uppercase tracking-[0.12em] text-ttcc-text-muted">
        v0.1.10 · testnet
      </div>
    </aside>
  );
}
