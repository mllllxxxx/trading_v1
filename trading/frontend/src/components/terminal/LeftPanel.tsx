import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
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
  accountSourceLabel,
  accountSyncedAt,
  accountAvailableBalance,
  accountMarginUsed,
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
  accountSourceLabel?: string;
  accountSyncedAt?: string | null;
  accountAvailableBalance?: number | null;
  accountMarginUsed?: number | null;
  cost?: {
    cost_usd: number;
    cap_usd: number;
    calls: number;
    call_cap?: number;
    remaining_calls?: number | null;
    hourly_calls?: number;
    hourly_call_cap?: number;
    remaining_hourly_calls?: number | null;
    monthly_cost_usd: number;
    pct_of_cap: number;
    cap_reached: boolean;
    cap_reason?: string;
    budget_skips?: number;
    last_budget_skip?: {
      ts?: string;
      source?: string;
      reason?: string;
      behavior?: string;
      calls?: number;
      call_cap?: number;
      hourly_calls?: number;
      hourly_call_cap?: number;
    } | null;
  } | null;
  onKillToggle: () => void;
}) {
  const { t } = useTranslation();
  const pnlFlashCls = useFlashClass(totalPnl);
  const isUp = totalPnl >= 0;
  const capitalPnlPct = startingCapital > 0 ? (totalPnl / startingCapital) * 100 : 0;
  const openTone = openPositions > 0 ? "bull" : "muted";
  const wrTone = winrate >= 50 ? "bull" : "muted";

  const [showSettings, setShowSettings] = useState(false);

  return (
    <aside
      className={cn(
        "relative flex w-[280px] shrink-0 flex-col gap-2 overflow-y-auto bg-ttcc-bg p-2",
        "before:absolute before:right-0 before:top-0 before:h-full before:w-px",
        "before:bg-gradient-to-b before:from-transparent before:via-ttcc-border/50 before:to-transparent",
        "before:pointer-events-none before:content-['']"
      )}
    >
      {/* Total PnL — hero card */}
      <MetricCard
        label={t("terminal.totalPnl")}
        icon={Banknote}
        tone={isUp ? "bull" : "bear"}
        className={isUp ? "tt-hero-gradient-green" : "tt-hero-gradient-red"}
      >
        <div className={cn("rounded-lg px-2 py-1.5 -mx-0.5", pnlFlashCls)}>
          <div className={cn(
            "font-mono text-[28px] font-bold leading-none tabular tracking-tight",
            isUp ? "text-ttcc-green" : "text-ttcc-red"
          )}>
            {isUp ? "+" : ""}{totalPnl.toFixed(2)}
            <span className="ml-1 text-[11px] font-medium text-ttcc-text-secondary">USD</span>
          </div>
          <div className="mt-1.5 flex items-center gap-2 text-[10px] tabular">
            <span className={cn(
              "inline-flex items-center gap-0.5 rounded-lg border px-1.5 py-0.5 font-mono font-semibold",
              isUp ? "border-ttcc-green/40 bg-ttcc-green/10 text-ttcc-green"
              : "border-ttcc-red/40 bg-ttcc-red/10 text-ttcc-red"
            )}>
              {isUp ? "▲" : "▼"}{capitalPnlPct.toFixed(2)}%
            </span>
            <span className="text-ttcc-text-secondary">{t("terminal.vsStart")} ${startingCapital.toFixed(0)}</span>
          </div>
        </div>
      </MetricCard>

      <div className="grid grid-cols-2 gap-2">
        <MetricCard label={t("terminal.capital")} icon={Wallet} dense tone="muted">
          <NumberCell value={`$${currentCapital.toFixed(2)}`} size="lg" bold />
          <div className="mt-1 flex items-baseline justify-between text-[10px] tabular">
            <span className="text-ttcc-text-secondary">{t("terminal.sinceStart")}</span>
            <span className={cn("font-mono", isUp ? "text-ttcc-green" : "text-ttcc-red")}>
              {isUp ? "+" : ""}{totalPnl.toFixed(2)}
            </span>
          </div>
          <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-0.5 border-t border-ttcc-border-subtle/60 pt-1 text-[9px] tabular">
            <span className="text-ttcc-text-secondary">{t("terminal.source")}</span>
            <span className="truncate text-right font-mono uppercase text-ttcc-text-muted" title={accountSyncedAt || undefined}>
              {accountSourceLabel || t("terminal.journalFallback")}
            </span>
            {accountAvailableBalance !== null && accountAvailableBalance !== undefined ? (
              <>
                <span className="text-ttcc-text-secondary">{t("terminal.available")}</span>
                <span className="text-right font-mono text-ttcc-text">${accountAvailableBalance.toFixed(2)}</span>
              </>
            ) : null}
            {accountMarginUsed !== null && accountMarginUsed !== undefined ? (
              <>
                <span className="text-ttcc-text-secondary">{t("terminal.margin")}</span>
                <span className="text-right font-mono text-ttcc-text">${accountMarginUsed.toFixed(2)}</span>
              </>
            ) : null}
          </div>
        </MetricCard>

        <MetricCard label={t("terminal.winrate")} icon={GaugeCircle} dense tone={wrTone}>
          <NumberCell
            value={fmtPct(winrate)}
            size="lg"
            bold
            tone={winrate >= 50 ? "bull" : "default"}
          />
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-ttcc-surface-2">
            <div
              className={cn(
                "h-full rounded-full bg-ttcc-green transition-all duration-300",
                winrate >= 50 && "tt-glow-green"
              )}
              style={{ width: `${Math.min(100, winrate)}%` }}
            />
          </div>
          <div className="mt-1 flex justify-between text-[10px] tabular text-ttcc-text-secondary">
            <span>
              <span className="text-ttcc-green">{wins}W</span>
              <span className="text-ttcc-text-muted">/</span>
              <span className="text-ttcc-red">{losses}L</span>
            </span>
            <span>{totalTrades} {t("terminal.total")}</span>
          </div>
        </MetricCard>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <MetricCard label={t("terminal.open")} icon={Activity} dense tone={openTone}>
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
            {openPositions === 0 ? t("terminal.openIdle") : openPositions === maxPositions ? t("terminal.openAtCap") : t("terminal.slotsOpen", { count: maxPositions - openPositions })}
          </div>
        </MetricCard>

        <MetricCard label={t("terminal.lossStreak")} dense tone={consecutiveLosses > 0 ? "bear" : "muted"} icon={TrendingDown}>
          <NumberCell
            value={consecutiveLosses > 0 ? `${consecutiveLosses}` : "—"}
            size="lg"
            bold
            tone={consecutiveLosses >= 3 ? "bear" : "default"}
          />
          <div className="mt-1 text-[10px] text-ttcc-text-secondary tabular">
            {consecutiveLosses >= 3 ? t("terminal.coolDownLikely") : t("terminal.healthy")}
          </div>
        </MetricCard>
      </div>

      {/* SYSTEM section */}
      <div className="mt-2">
        <PanelLabel icon={Power} tone="muted">{t("terminal.system")}</PanelLabel>
        <div className="mt-1.5 flex flex-col gap-2">
          <MetricCard label={t("terminal.killSwitch")} dense tone={killActive ? "bear" : "bull"}>
            <button
              type="button"
              onClick={onKillToggle}
              className={cn(
                "flex w-full items-center justify-between rounded-lg border px-2 py-1 transition-colors",
                killActive
                  ? "border-ttcc-red/60 bg-ttcc-red/15 text-ttcc-red tt-kill-armed tt-glow-red"
                  : "border-ttcc-green/40 bg-ttcc-green/10 text-ttcc-green hover:bg-ttcc-green/15"
              )}
            >
              <span className="flex items-center gap-1.5">
                {killActive ? <ShieldAlert className="h-3 w-3" /> : <ShieldCheck className="h-3 w-3" />}
                <span className="font-mono text-[10px] font-semibold uppercase tracking-wider">
                  {killActive ? t("terminal.activeHalted") : t("terminal.armed")}
                </span>
              </span>
              <span className="font-mono text-[10px] tabular">
                {killActive ? t("terminal.stop") : t("terminal.go")}
              </span>
            </button>
          </MetricCard>

          <MetricCard label={t("terminal.symbolsTracked")} dense tone="muted">
            <div className="flex flex-wrap gap-1">
              {symbols.slice(0, 10).map((s) => (
                <span
                  key={s}
                  className="rounded border border-ttcc-border-subtle bg-ttcc-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-ttcc-text-secondary"
                >
                  {s.replace("-USDT", "")}
                </span>
              ))}
              {symbols.length > 10 ? (
                <span className="font-mono text-[10px] text-ttcc-text-muted">+{symbols.length - 10}</span>
              ) : null}
            </div>
            <div className="mt-1 text-[10px] text-ttcc-text-secondary tabular">
              {symbols.length} {t("terminal.active")}
            </div>
          </MetricCard>

          <MetricCard label={t("terminal.model")} dense tone="muted" icon={Brain}>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[11px] font-medium tabular text-ttcc-text truncate">{modelName}</span>
            </div>
            <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-0.5 text-[10px] tabular">
              <span className="text-ttcc-text-secondary">{t("terminal.latency")}</span>
              <span className="text-right font-mono text-ttcc-text">{avgLatency}</span>
              <span className="text-ttcc-text-secondary">{t("terminal.decisionsToday")}</span>
              <span className="text-right font-mono text-ttcc-text">{recentDecisionCount}</span>
              <span className="text-ttcc-text-secondary">{t("terminal.lastUpdate")}</span>
              <span className="text-right font-mono text-ttcc-text">
                {lastUpdate ? lastUpdate.substring(11, 19) : "—"}
              </span>
            </div>
          </MetricCard>

          <MetricCard label={t("terminal.llmSpend")} dense tone={cost?.cap_reached ? "bear" : (cost?.pct_of_cap ?? 0) >= 80 ? "warn" : "muted"} icon={Cpu}>
            <div className="flex items-baseline justify-between">
              <span className="font-mono text-base font-bold tabular text-ttcc-text leading-none">
                ${cost?.cost_usd?.toFixed(4) ?? "0.0000"}
              </span>
              <span className="font-mono text-[10px] tabular text-ttcc-text-secondary">
                / ${cost?.cap_usd?.toFixed(2) ?? "0.10"}
              </span>
            </div>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-ttcc-surface-2">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-300",
                  cost?.cap_reached
                    ? "bg-ttcc-red tt-glow-red"
                    : (cost?.pct_of_cap ?? 0) >= 80
                    ? "bg-ttcc-yellow"
                    : "bg-ttcc-green tt-glow-green"
                )}
                style={{ width: `${Math.min(100, cost?.pct_of_cap ?? 0)}%` }}
              />
            </div>
            <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-0.5 text-[10px] tabular text-ttcc-text-secondary">
              <span>{t("terminal.calls")}</span>
              <span className="text-right font-mono text-ttcc-text">
                {cost?.calls ?? 0}/{cost?.call_cap ?? 120}
              </span>
              <span>{t("terminal.hour")}</span>
              <span className="text-right font-mono text-ttcc-text">
                {cost?.hourly_calls ?? 0}/{cost?.hourly_call_cap ?? 6}
              </span>
              <span>{t("terminal.remaining")}</span>
              <span className="text-right font-mono text-ttcc-text">
                {cost?.remaining_calls ?? Math.max(0, (cost?.call_cap ?? 120) - (cost?.calls ?? 0))}
              </span>
              <span>${cost?.monthly_cost_usd?.toFixed(2) ?? "0.00"} {t("terminal.perMonth")}</span>
              <span className="text-right font-mono text-ttcc-text">
                {cost?.budget_skips ?? 0} {t("terminal.skips")}
              </span>
            </div>
            {cost?.last_budget_skip?.reason ? (
              <div
                className="mt-1 truncate rounded-lg border border-ttcc-yellow/30 bg-ttcc-yellow/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-ttcc-yellow"
                title={`${cost.last_budget_skip.source ?? "llm"}: ${cost.last_budget_skip.reason}`}
              >
                {t("terminal.skip")} {cost.last_budget_skip.reason}
              </div>
            ) : null}
          </MetricCard>
        </div>
      </div>

      {/* SETTINGS collapse */}
      <div className="mt-2">
        <button
          type="button"
          onClick={() => setShowSettings((v) => !v)}
          className="flex w-full items-center justify-between gap-2 rounded-lg bg-ttcc-surface/50 px-2 py-1.5 hover:bg-ttcc-surface transition-colors"
        >
          <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">
            {showSettings ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            <SettingsIcon className="h-3 w-3" />
            {t("terminal.settings")}
          </span>
        </button>
        {showSettings ? (
          <div className="mt-1.5 flex flex-col gap-1 rounded-lg bg-ttcc-surface/50 p-2 text-[11px]">
            <Link
              to="/settings"
              className="flex items-center justify-between rounded-lg px-2 py-1 hover:bg-ttcc-surface-2/30 transition-colors"
            >
              <span className="text-ttcc-text">{t("terminal.llmSettings")}</span>
              <span className="font-mono text-[10px] text-ttcc-text-muted">→</span>
            </Link>
            <Link
              to="/runtime"
              className="flex items-center justify-between rounded-lg px-2 py-1 hover:bg-ttcc-surface-2/30 transition-colors"
            >
              <span className="text-ttcc-text">{t("terminal.runtimeMonitor")}</span>
              <span className="font-mono text-[10px] text-ttcc-text-muted">→</span>
            </Link>
            <Link
              to="/correlation"
              className="flex items-center justify-between rounded-lg px-2 py-1 hover:bg-ttcc-surface-2/30 transition-colors"
            >
              <span className="text-ttcc-text">{t("terminal.correlationMatrix")}</span>
              <span className="font-mono text-[10px] text-ttcc-text-muted">→</span>
            </Link>
            <div className="mt-1 flex items-center justify-between px-2 py-1">
              <span className="text-ttcc-text-secondary">{t("terminal.polling")}</span>
              <PillBadge tone={running ? "ok" : "neutral"} mono>{running ? t("terminal.live5s") : t("terminal.stopped")}</PillBadge>
            </div>
            <div className="flex items-center justify-between px-2 py-1">
              <span className="text-ttcc-text-secondary">{t("terminal.ticker10sLabel")}</span>
              <span className="font-mono text-[10px] tabular text-ttcc-text-muted">{t("terminal.ticker10s")}</span>
            </div>
          </div>
        ) : null}
      </div>

      <div className="mt-2 px-2 text-[9px] uppercase tracking-[0.12em] text-ttcc-text-muted/50">
        {t("terminal.versionTestnet")}
      </div>
    </aside>
  );
}
