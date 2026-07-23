import { Brain, ShieldAlert, ShieldCheck, Zap } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
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
  accountSourceLabel,
  accountSyncedAt,
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
  accountSourceLabel?: string;
  accountSyncedAt?: string | null;
  onKillToggle: () => void;
  onNavigateHome?: () => void;
}) {
  const { t } = useTranslation();
  const pnlUp = pnlTodayUsd >= 0;
  const accountSource = accountSourceLabel || t("terminal.currentCapitalAccount");
  const accountTitle = accountSyncedAt
    ? t("terminal.currentCapitalTitleAt", { source: accountSource, time: accountSyncedAt })
    : t("terminal.currentCapitalTitle", { source: accountSource });
  return (
    <header className="flex items-center gap-0 h-10 border-b border-ttcc-border bg-ttcc-bg shrink-0">
      {/* Brand */}
      <div className="flex h-full items-center gap-2 border-r border-ttcc-border/60 bg-ttcc-surface px-3 shrink-0">
        <Link
          to="/trader"
          onClick={onNavigateHome}
          className="flex h-6 w-6 items-center justify-center rounded bg-ttcc-accent/15 text-ttcc-accent"
          title={t("terminal.brandTitle")}
        >
          <Zap className="h-3.5 w-3.5" />
        </Link>
        <div className="flex flex-col leading-none">
          <span className="text-[13px] font-bold tracking-tight text-ttcc-text">VIBE·TRADE</span>
          <span className="text-[9px] uppercase tracking-[0.12em] text-ttcc-text-secondary">{t("terminal.commandCenter")}</span>
        </div>
      </div>

      {/* Ticker scroll */}
      <Ticker tickers={tickers} symbols={symbols} />

      {/* Right cluster: stats + controls */}
      <div className="flex h-full items-center gap-1.5 border-l border-ttcc-border/60 bg-ttcc-surface px-3 shrink-0">
        {/* Capital */}
        <div className="flex items-center gap-1.5 rounded border border-ttcc-border bg-ttcc-surface-2 px-2 py-0.5" title={accountTitle}>
          <span className="text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-muted">{t("terminal.cap")}</span>
          <span className="font-mono text-[11px] font-semibold text-ttcc-text tabular">
            ${capitalUsd.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </span>
          {accountSourceLabel ? (
            <span className="hidden rounded border border-ttcc-border/70 px-1 py-px font-mono text-[8px] uppercase tracking-wider text-ttcc-text-muted lg:inline">
              {accountSourceLabel.includes("exchange") ? t("terminal.sourceExch") : t("terminal.sourceJournal")}
            </span>
          ) : null}
        </div>

        {/* PnL today */}
        <div className={cn(
          "flex items-center gap-1.5 rounded border px-2 py-0.5",
          pnlUp
            ? "border-ttcc-green/40 bg-ttcc-green/10 text-ttcc-green"
            : "border-ttcc-red/40 bg-ttcc-red/10 text-ttcc-red"
        )} title={t("terminal.todayPnl")}>
          <span className="text-[9px] font-semibold uppercase tracking-wider opacity-80">{t("terminal.pnl")}</span>
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
          title={killActive ? t("terminal.killArmed") : t("terminal.killArm")}
        >
          {killActive ? <ShieldAlert className="h-3 w-3" /> : <ShieldCheck className="h-3 w-3" />}
          <span className="text-[10px] font-bold uppercase tracking-wider tabular">
            {killActive ? t("terminal.kill") : t("terminal.arm")}
          </span>
          {killActive ? <span className="tt-live-dot !h-1.5 !w-1.5" /> : null}
        </button>

        {/* Model */}
        <div className="flex items-center gap-1.5 rounded border border-ttcc-border bg-ttcc-surface-2 px-2 py-0.5" title={t("terminal.modelLabel", { name: modelName })}>
          <Brain className="h-3 w-3 text-ttcc-blue" />
          <span className="font-mono text-[10px] text-ttcc-text-secondary tabular truncate max-w-[120px]">{modelName}</span>
        </div>

        {/* Refresh indicator */}
        <div className="flex items-center gap-1.5 rounded border border-ttcc-border bg-ttcc-surface-2 px-2 py-0.5" title={t("terminal.pollingStatus")}>
          <LiveDot idle={!running} />
          <span className="font-mono text-[10px] text-ttcc-text-secondary tabular">
            {running ? t("terminal.live") : t("terminal.idle")}
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
