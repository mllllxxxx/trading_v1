import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Activity, Banknote, Bell, History as HistoryIcon } from "lucide-react";
import {
  TabBar,
  TabPanel,
  type TabSpec,
} from "@/components/terminal/TabBar";
import {
  PositionCard,
  EmptyPositions,
  type Position,
} from "@/components/terminal/PositionCard";
import {
  fmtTime,
  PillBadge,
  Skeleton,
  cn,
} from "@/components/terminal/primitives";
import type { TickerEntry } from "@/components/terminal/Ticker";
import { ClosedTradesTable } from "@/components/terminal/ClosedTradesTable";
import { AdaptivePolicyBadge } from "@/components/terminal/AdaptivePolicyBadge";
import { mergePositionFeeds } from "@/lib/traderUtils";
import type { AlertItem } from "@/lib/api";
import { api } from "@/lib/api";
import { useTraderStatusStore } from "@/stores/traderStatus";
import type {
  AdaptivePolicyControllerStatus,
  ClosedTrade,
  ShadowScoreCanaryStatus,
  ShadowScoreReviewControllerStatus,
  ShadowScoringExperimentStatus,
  Stats,
} from "@/types/api";

// Re-export canonical types and primitives so existing imports
// (`@/pages/Trader`) keep working — the public surface is unchanged.
export type {
  AdaptivePolicyControllerStatus,
  ShadowScoreCanaryStatus,
  ShadowScoreReviewControllerStatus,
  ShadowScoringExperimentStatus,
  Stats,
};
export { fmtUsd, fmtPct, fmtPctSigned, fmtPx, fmtTime, colorClass } from "@/components/terminal/primitives";
export { PillBadge as Pill } from "@/components/terminal/primitives";
export { ConfluenceBadge, RrBadge, SideBadge, TeamBadge } from "@/components/terminal/PositionCard";

// Re-export extracted components for backward compat with `@/pages/Trader`
// importers (Cockpit.tsx, Trader.test.tsx).
export { ClosedTradesTable } from "@/components/terminal/ClosedTradesTable";
export { AdaptivePolicyBadge } from "@/components/terminal/AdaptivePolicyBadge";
export { canonicalPositionSymbol, mergePositionFeeds } from "@/lib/traderUtils";

// Re-exported for backward compat with TraderHistory.tsx — ClosedTrade now
// comes from the canonical types module.
export type { ClosedTrade };

const STATUS_REFRESH_MS = 5_000;
const HISTORY_PAGE_SIZE = 20;

// ====================================================================
// PositionsTab
// ====================================================================

function PositionsTab({
  positions,
  tickers,
  loading,
}: {
  positions: Position[];
  tickers: TickerEntry[];
  loading: boolean;
}) {
  return (
    <div className="grid gap-2 p-2 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
      {loading && positions.length === 0 ? (
        <>
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </>
      ) : positions.length === 0 ? (
        <div className="md:col-span-2 xl:col-span-3">
          <EmptyPositions />
        </div>
      ) : (
        positions.map((p, i) => {
          const tk = tickers.find((x) => x.symbol === p.symbol);
          return (
            <PositionCard
              key={`${p.symbol}-${i}`}
              p={p}
              mark={tk?.price ?? null}
              sequenceNumber={i + 1}
              sequenceTotal={positions.length}
            />
          );
        })
      )}
    </div>
  );
}

// ====================================================================
// HistoryTab — paginated closed trades table
// ====================================================================

function HistoryTab({
  trades,
  loading,
}: {
  trades: ClosedTrade[];
  loading: boolean;
}) {
  const [page, setPage] = useState(0);
  const totalPages = Math.max(1, Math.ceil(trades.length / HISTORY_PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const slice = trades.slice(safePage * HISTORY_PAGE_SIZE, (safePage + 1) * HISTORY_PAGE_SIZE);

  return (
    <div>
      {loading && !trades.length ? (
        <div className="space-y-1 p-2">
          <Skeleton className="h-6" />
          <Skeleton className="h-6" />
          <Skeleton className="h-6" />
        </div>
      ) : trades.length === 0 ? (
        <div className="flex h-24 items-center justify-center text-[11px] text-ttcc-text-secondary">
          No closed trades yet
        </div>
      ) : (
        <ClosedTradesTable trades={slice} startIndex={safePage * HISTORY_PAGE_SIZE} totalTrades={trades.length} />
      )}
      {trades.length > HISTORY_PAGE_SIZE ? (
        <div className="flex items-center justify-between border-t border-ttcc-border bg-ttcc-surface px-2.5 py-1.5 text-[10px] text-ttcc-text-secondary tabular">
          <span>
            page {safePage + 1}/{totalPages} · {trades.length} trades
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={safePage === 0}
              className="rounded border border-ttcc-border bg-ttcc-surface-2 px-1.5 py-0.5 disabled:opacity-40"
            >
              prev
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={safePage >= totalPages - 1}
              className="rounded border border-ttcc-border bg-ttcc-surface-2 px-1.5 py-0.5 disabled:opacity-40"
            >
              next
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ====================================================================
// AlertsTab — feed of recent alerts (polled every 5s alongside status)
// ====================================================================

function AlertsTab() {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const seenIds = useRef<Set<string>>(new Set());
  const initialized = useRef(false);

  const load = useCallback(async () => {
    try {
      const res = await api.getTraderAlerts(100);
      if (res.error) {
        setError(res.error);
        setLoading(false);
        return;
      }
      // Mark every alert we've already shown so only the new ones get a row-in animation.
      const next = res.alerts;
      const newOnes: AlertItem[] = [];
      for (const a of next) {
        const id = `${a.ts}-${a.type}-${a.message}`;
        if (!seenIds.current.has(id)) {
          if (initialized.current) newOnes.push(a);
          seenIds.current.add(id);
        }
      }
      if (seenIds.current.size > 500) {
        // Keep the dedup set bounded.
        const arr = Array.from(seenIds.current).slice(-500);
        seenIds.current = new Set(arr);
      }
      setAlerts(next);
      setError(null);
      initialized.current = true;
      setLoading(false);
      // New-row slide-in handled by AlertsList effect on `next`.
      // We stash a one-shot pulse on the latest unseen ids.
      pulseNewOnes(newOnes);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "failed";
      setError(msg);
      setLoading(false);
    }
  }, []);

  // Pulse ids for the row-in animation. Lives at module scope to avoid useState churn.
  const [pulseIds, setPulseIds] = useState<Set<string>>(new Set());
  const pulseNewOnes = (items: AlertItem[]) => {
    if (!items.length) return;
    const ids = new Set(items.map((a) => `${a.ts}-${a.type}-${a.message}`));
    setPulseIds(ids);
    window.setTimeout(() => setPulseIds(new Set()), 1500);
  };

  useEffect(() => {
    load();
    const t = window.setInterval(load, STATUS_REFRESH_MS);
    return () => window.clearInterval(t);
  }, [load]);

  if (loading && !alerts.length) {
    return (
      <div className="space-y-1 p-2">
        <Skeleton className="h-8" />
        <Skeleton className="h-8" />
        <Skeleton className="h-8" />
      </div>
    );
  }
  if (error && !alerts.length) {
    return (
      <div className="flex h-24 items-center justify-center text-[11px] text-ttcc-red">{error}</div>
    );
  }
  if (!alerts.length) {
    return (
      <div className="flex h-24 items-center justify-center text-[11px] text-ttcc-text-secondary">
        No alerts in the last ~1000 events
      </div>
    );
  }

  return (
    <ul className="max-h-[70vh] overflow-y-auto">
      {alerts.map((a) => {
        const id = `${a.ts}-${a.type}-${a.message}`;
        const isNew = pulseIds.has(id);
        return (
          <li
            key={id}
            className={cn(
              "flex items-start gap-2 border-b border-ttcc-border/40 px-2.5 py-1.5 last:border-b-0",
              isNew && "ttcc-row-in"
            )}
          >
            <SeverityBadge severity={a.severity} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 text-[11px]">
                <span className="font-mono tabular text-[10px] text-ttcc-text-muted shrink-0">{fmtTime(a.ts)}</span>
                {a.symbol ? (
                  <span className="font-mono text-[11px] font-semibold text-ttcc-text">{a.symbol.replace("-USDT", "")}</span>
                ) : null}
                <PillBadge tone="neutral" mono>{a.type}</PillBadge>
              </div>
              <div className="mt-0.5 text-[11px] text-ttcc-text-secondary truncate">{a.message}</div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function SeverityBadge({ severity }: { severity: AlertItem["severity"] }) {
  const tone =
    severity === "critical" ? "bg-ttcc-red/20 text-ttcc-red border-ttcc-red/50"
    : severity === "warning" ? "bg-ttcc-yellow/15 text-ttcc-yellow border-ttcc-yellow/40"
    : "bg-ttcc-blue/15 text-ttcc-blue border-ttcc-blue/40";
  return (
    <span className={cn(
      "mt-0.5 inline-flex h-5 w-12 shrink-0 items-center justify-center rounded border text-[9px] font-bold uppercase tracking-wider",
      tone
    )}>
      {severity}
    </span>
  );
}

// ====================================================================
// Trader — center content for the /trader route.
// Heavy metrics/controls live in the TerminalLayout shell.
// ====================================================================

type TraderTab = "positions" | "history" | "alerts";

export function Trader() {
  const { t } = useTranslation();
  const { status, tickers, loading } = useTraderStatusStore();
  const [tab, setTab] = useState<TraderTab>("positions");

  const positions = useMemo(
    () => mergePositionFeeds(status?.positions ?? [], status?.exchange_positions ?? []),
    [status?.positions, status?.exchange_positions]
  );
  const syncStatus = status?.sync_status;
  const adaptiveController = status?.adaptive_policy_controller;
  const shadowScoreReviewController = status?.shadow_score_review_controller;
  const shadowScoreCanary = status?.shadow_score_canary;
  const shadowScoreExperiment = status?.adaptive_evaluation
    ?.shadow_scoring_experiment_evaluation?.continuous_conflict_v2;
  const recentTrades = useMemo(
    () => (status?.closed_trades ?? []).slice(-200).reverse(),
    [status?.closed_trades]
  );

  const tabs: TabSpec<TraderTab>[] = [
    {
      key: "positions",
      label: t("trader.positionsTitle", "Positions"),
      icon: Activity,
      badge: <span className="font-mono">{positions.length}</span>,
    },
    {
      key: "history",
      label: t("trader.closedTitle", "History"),
      icon: HistoryIcon,
      badge: <span className="font-mono">{status?.closed_trades?.length ?? 0}</span>,
    },
    {
      key: "alerts",
      label: "Alerts",
      icon: Bell,
    },
  ];

  return (
    <div className="flex h-full flex-col">
      <TabBar
        tabs={tabs}
        active={tab}
        onChange={setTab}
        right={
          <span className="flex items-center gap-1.5 text-[10px] text-ttcc-text-secondary tabular">
            <AdaptivePolicyBadge
              controller={adaptiveController}
              experiment={shadowScoreExperiment}
              reviewController={shadowScoreReviewController}
              canary={shadowScoreCanary}
            />
            {syncStatus?.status ? (
              <span
                className={cn(
                  "rounded border px-1 py-0.5 font-mono uppercase",
                  syncStatus.status === "in_sync"
                    ? "border-ttcc-green/30 text-ttcc-green"
                    : "border-ttcc-yellow/40 text-ttcc-yellow"
                )}
              >
                {syncStatus.status} {syncStatus.positions_on_exchange ?? 0}/
                {syncStatus.positions_in_journal ?? 0}
              </span>
            ) : null}
            <Banknote className="h-3 w-3" />
            last {status?.timestamp ? fmtTime(status.timestamp) : "—"}
          </span>
        }
      />
      <TabPanel active={tab}>
        {tab === "positions" ? (
          <PositionsTab positions={positions} tickers={tickers} loading={loading} />
        ) : tab === "history" ? (
          <HistoryTab trades={recentTrades} loading={loading} />
        ) : (
          <AlertsTab />
        )}
      </TabPanel>
    </div>
  );
}
