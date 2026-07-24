import { ShieldAlert, ShieldCheck, Zap } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { cn } from "@/components/terminal/primitives";
import { Ticker, type TickerEntry } from "@/components/terminal/Ticker";

/**
 * TopBar — sticky header for the Trading Command Center.
 *
 * Layout: brand · ticker scroll · capital · pnl · kill switch
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
  // refreshAgeMs / running / modelName are surfaced by StatusBar and
  // LeftPanel elsewhere; they are intentionally unused here but kept in
  // the signature for layout-side wiring stability.
  void refreshAgeMs;
  void running;
  void modelName;
  const accountSource = accountSourceLabel || t("terminal.currentCapitalAccount");
  const accountTitle = accountSyncedAt
    ? t("terminal.currentCapitalTitleAt", { source: accountSource, time: accountSyncedAt })
    : t("terminal.currentCapitalTitle", { source: accountSource });
  return (
    <header className="tt-glass flex h-12 items-center shrink-0">
      {/* Brand */}
      <div className="flex h-full items-center gap-2 px-3 shrink-0">
        <Link
          to="/trader"
          onClick={onNavigateHome}
          className="flex h-6 w-6 items-center justify-center rounded-lg bg-ttcc-accent/15 text-ttcc-accent transition-shadow hover:tt-glow-accent"
          title={t("terminal.brandTitle")}
        >
          <Zap className="h-3.5 w-3.5" />
        </Link>
        <span className="text-[13px] font-bold tracking-tight text-ttcc-text">VIBE·TRADE</span>
      </div>

      {/* Ticker scroll */}
      <Ticker tickers={tickers} symbols={symbols} />

      {/* Right cluster: capital · pnl · kill switch */}
      <div className="flex h-full items-center gap-2 px-3 shrink-0">
        {/* Capital */}
        <div
          className="flex items-center gap-1.5 rounded-lg bg-ttcc-surface-2/40 px-2.5 py-1"
          title={accountTitle}
        >
          <span className="text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-muted">
            {t("terminal.cap")}
          </span>
          <span className="font-mono text-[11px] font-semibold text-ttcc-text tabular">
            ${capitalUsd.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </span>
          {accountSourceLabel ? (
            <span className="hidden rounded-lg bg-ttcc-surface-2/60 px-1 py-px font-mono text-[8px] uppercase tracking-wider text-ttcc-text-muted lg:inline">
              {accountSourceLabel.includes("exchange") ? t("terminal.sourceExch") : t("terminal.sourceJournal")}
            </span>
          ) : null}
        </div>

        {/* PnL today */}
        <div
          className={cn(
            "flex items-center gap-1.5 rounded-lg px-2.5 py-1",
            pnlUp ? "bg-ttcc-green/10 text-ttcc-green tt-glow-green" : "bg-ttcc-red/10 text-ttcc-red tt-glow-red"
          )}
          title={t("terminal.todayPnl")}
        >
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
            "tt-focus flex items-center gap-1.5 rounded-lg px-2 py-1 transition-colors",
            killActive
              ? "bg-ttcc-red/15 text-ttcc-red tt-glow-red"
              : "bg-ttcc-green/10 text-ttcc-green"
          )}
          title={killActive ? t("terminal.killArmed") : t("terminal.killArm")}
        >
          {killActive ? <ShieldAlert className="h-3 w-3" /> : <ShieldCheck className="h-3 w-3" />}
          <span className="text-[10px] font-bold uppercase tracking-wider tabular">
            {killActive ? t("terminal.kill") : t("terminal.arm")}
          </span>
          {killActive ? <span className="tt-live-dot !h-1.5 !w-1.5" /> : null}
        </button>
      </div>
    </header>
  );
}
