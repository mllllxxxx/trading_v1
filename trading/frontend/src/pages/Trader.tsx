import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useOutletContext } from "react-router-dom";
import { Activity, Banknote, Bell, History as HistoryIcon, SlidersHorizontal } from "lucide-react";
import {
  TabBar,
  TabPanel,
  type TabSpec,
} from "@/components/terminal/TabBar";
import {
  PositionCard,
  EmptyPositions,
  type Position,
  type PositionDecisionContext,
  type PositionMarketContext,
  SideBadge,
  TeamBadge,
  ConfluenceBadge,
} from "@/components/terminal/PositionCard";
import {
  fmtUsd,
  fmtPx,
  fmtTime,
  colorClass,
  PillBadge,
  Skeleton,
  cn,
} from "@/components/terminal/primitives";
import type { TickerEntry } from "@/components/terminal/Ticker";
import type { AlertItem } from "@/lib/api";
import { api } from "@/lib/api";

// ====================================================================
// Re-exports for backward compatibility with TraderHistory.tsx.
// TraderHistory imports these from "@/pages/Trader" — keep the same
// public API even though the components now live in
// @/components/terminal/*.
// ====================================================================
export { fmtUsd, fmtPct, fmtPctSigned, fmtPx, fmtTime, colorClass } from "@/components/terminal/primitives";
export { PillBadge as Pill } from "@/components/terminal/primitives";
export { ConfluenceBadge, RrBadge, SideBadge, TeamBadge } from "@/components/terminal/PositionCard";

// ====================================================================
// Types (mirror backend shapes)
// ====================================================================

type Stats = {
  total_trades?: number;
  wins?: number;
  losses?: number;
  total_pnl_usd?: number;
  open_count?: number;
  max_drawdown_usd?: number;
  starting_capital?: number;
  current_capital?: number;
  winrate?: number;
  consecutive_losses?: number;
};

type ClosedTrade = {
  closed_at: string;
  symbol: string;
  side: string;
  entry: number;
  exit_price: number;
  position_size: number;
  pnl_usd: number;
  exit_reason: string;
  confluence_score: number;
  team_id?: string | null;
  team_name?: string | null;
  strategy_id?: string | null;
  strategy_name?: string | null;
  source_signal_id?: string;
  decision_id?: string;
  open_reason?: string;
  market_context?: PositionMarketContext;
  decision_context?: PositionDecisionContext;
};

type Status = {
  timestamp?: string;
  running?: boolean;
  symbols?: string[];
  stats?: Stats;
  positions?: Position[];
  exchange_positions?: Position[];
  sync_status?: {
    status?: string;
    positions_on_exchange?: number;
    positions_in_journal?: number;
    missing_in_journal?: string[];
    missing_on_exchange?: string[];
    errors?: string[];
  };
  closed_trades?: ClosedTrade[];
  kill_switch_active?: boolean;
  adaptive_policy_controller?: AdaptivePolicyControllerStatus;
  shadow_score_review_controller?: ShadowScoreReviewControllerStatus;
  shadow_score_canary?: ShadowScoreCanaryStatus;
  adaptive_evaluation?: {
    shadow_scoring_experiment_evaluation?: {
      continuous_conflict_v2?: ShadowScoringExperimentStatus;
    };
  };
};

export type AdaptivePolicyControllerStatus = {
  status?: string;
  mode?: string;
  revision?: number;
  active_zones?: {
    strong_min_score?: number;
    gray_min_score?: number;
  };
  effective_source?: string;
  last_action?: string | null;
  last_reason?: string | null;
  state_error?: string | null;
  strategy_coverage_failures?: Array<{
    strategy_id?: string;
    eligible_records?: number;
    minimum_records?: number;
  }>;
};

export type ShadowScoreReviewControllerStatus = {
  status?: string;
  revision?: number;
  operator_approved?: boolean;
  active_for_routing?: boolean;
  canary_enabled?: boolean;
  candidate?: {
    strong_min_score?: number | null;
    gray_min_score?: number | null;
    confirmations?: number;
    required_confirmations?: number;
  } | null;
  last_reason?: string | null;
};

export type ShadowScoreCanaryStatus = {
  status?: string;
  routing_enabled?: boolean;
  approval_id?: string | null;
  candidate_fingerprint?: string | null;
  candidate_thresholds?: {
    strong_min_score?: number;
    gray_min_score?: number;
  } | null;
  allocation_rate?: number;
  risk_multiplier?: number;
  last_reason?: string | null;
  rollback_metrics?: {
    closed_trades?: number;
    average_r_lower_bound?: number | null;
    profit_factor?: number | null;
    cumulative_r?: number;
  };
};

export type ShadowScoringExperimentStatus = {
  mode?: string;
  active_for_routing?: boolean;
  eligible_records?: number;
  score_coverage?: {
    valid?: number;
    total?: number;
    ratio?: number;
    exclusion_reasons?: Record<string, number>;
  };
  score_delta_v2_minus_v1?: {
    average?: number | null;
    average_absolute?: number | null;
  };
  zone_transitions?: Record<string, number>;
  threshold_calibration?: {
    status?: string;
    sample_reasons?: string[];
    candidate_thresholds?: {
      strong_min_score?: number;
      gray_min_score?: number;
      active_for_routing?: boolean;
    } | null;
    objective_comparison_vs_active_v1?: {
      validation_delta_v2_minus_v1?: number | null;
    } | null;
  };
  review_eligibility?: {
    status?: string;
    eligible?: boolean;
    blocking_reasons?: string[];
  };
  auto_apply?: boolean;
};

const STATUS_REFRESH_MS = 5_000;
const TICKER_REFRESH_MS = 10_000;
const TICKER_SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT"];
const HISTORY_PAGE_SIZE = 20;

// ====================================================================
// Fetch helper (also used by Status + Alerts inside TraderCenter)
// ====================================================================

async function request<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" } });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

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

export function ClosedTradesTable({
  trades,
  startIndex = 0,
  totalTrades,
}: {
  trades: ClosedTrade[];
  startIndex?: number;
  totalTrades?: number;
}) {
  if (!trades.length) {
    return null;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead className="bg-ttcc-surface-2 text-[10px] uppercase tracking-wider text-ttcc-text-secondary">
          <tr className="border-b border-ttcc-border">
            <th className="px-2.5 py-1.5 text-left font-medium">#</th>
            <th className="px-2.5 py-1.5 text-left font-medium">Closed</th>
            <th className="px-2.5 py-1.5 text-left font-medium">Team</th>
            <th className="px-2.5 py-1.5 text-left font-medium">Symbol</th>
            <th className="px-2.5 py-1.5 text-left font-medium">Side</th>
            <th className="px-2.5 py-1.5 text-right font-medium">Entry</th>
            <th className="px-2.5 py-1.5 text-right font-medium">Exit</th>
            <th className="px-2.5 py-1.5 text-right font-medium">Size</th>
            <th className="px-2.5 py-1.5 text-right font-medium">PnL</th>
            <th className="px-2.5 py-1.5 text-left font-medium">Reason</th>
            <th className="px-2.5 py-1.5 text-right font-medium">Conf.</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => {
            const pnl = parseFloat(String(t.pnl_usd));
            const reason = t.exit_reason || "";
            const tradeNumber = startIndex + i + 1;
            const openReason = t.open_reason || t.decision_context?.thesis || t.decision_context?.reasoning_summary || "";
            const tone = reason.includes("profit") || reason.includes("tp")
              ? "tp"
              : reason.includes("stop") || reason.includes("sl")
              ? "sl"
              : "neutral";
            return (
              <tr key={i} className="border-b border-ttcc-border/40 hover:bg-ttcc-surface-2">
                <td
                  className="px-2.5 py-1 font-mono text-[10px] font-bold tabular text-ttcc-accent"
                  title={`Trade ${tradeNumber}${totalTrades ? ` of ${totalTrades}` : ""}`}
                >
                  #{tradeNumber}
                </td>
                <td className="px-2.5 py-1 font-mono tabular text-ttcc-text-muted">{fmtTime(t.closed_at)}</td>
                <td className="px-2.5 py-1">
                  <TeamBadge teamId={t.team_id} teamName={t.team_name || t.strategy_name} />
                </td>
                <td className="px-2.5 py-1 font-mono font-medium text-ttcc-text">{t.symbol.replace("-USDT", "")}</td>
                <td className="px-2.5 py-1"><SideBadge side={t.side} /></td>
                <td className="px-2.5 py-1 text-right font-mono tabular text-ttcc-text">{fmtPx(t.entry)}</td>
                <td className="px-2.5 py-1 text-right font-mono tabular text-ttcc-text">{fmtPx(t.exit_price)}</td>
                <td className="px-2.5 py-1 text-right font-mono tabular text-ttcc-text">{t.position_size}</td>
                <td className={cn(
                  "px-2.5 py-1 text-right font-mono font-semibold tabular",
                  colorClass(pnl)
                )}>
                  <span className="inline-flex items-center gap-0.5">
                    {pnl >= 0 ? "▲" : "▼"}{fmtUsd(pnl)}
                  </span>
                </td>
                <td className="px-2.5 py-1">
                  <PillBadge tone={tone as "tp" | "sl" | "neutral"}>{reason}</PillBadge>
                  {openReason ? (
                    <div
                      className="mt-1 max-w-[320px] truncate text-[10px] leading-tight text-ttcc-text-secondary"
                      title={openReason}
                    >
                      {openReason}
                    </div>
                  ) : null}
                </td>
                <td className="px-2.5 py-1 text-right"><ConfluenceBadge score={t.confluence_score} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function canonicalPositionSymbol(symbol: string | undefined | null): string {
  let raw = String(symbol || "").trim().toUpperCase();
  if (!raw) {
    return "";
  }
  if (raw.includes(":")) {
    raw = raw.split(":", 1)[0];
  }
  raw = raw.replace("/", "-");
  if (raw.endsWith("-SWAP")) {
    raw = raw.slice(0, -"-SWAP".length);
  }
  const parts = raw.split("-").filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0]}-${parts[1]}`;
  }
  return raw;
}

export function mergePositionFeeds(
  journalPositions: Position[] = [],
  exchangePositions: Position[] = [],
): Position[] {
  const bySymbol = new Map<string, Position>();
  const order: string[] = [];

  const putExchange = (position: Position) => {
    const key = canonicalPositionSymbol(position.symbol);
    if (!key) return;
    if (!bySymbol.has(key)) {
      order.push(key);
    }
    bySymbol.set(key, {
      ...position,
      symbol: key,
      source: position.source || "exchange",
    });
  };

  const putJournal = (position: Position) => {
    const key = canonicalPositionSymbol(position.symbol);
    if (!key) return;
    const exchange = bySymbol.get(key);
    if (!exchange) {
      order.push(key);
      bySymbol.set(key, { ...position, symbol: key });
      return;
    }
    bySymbol.set(key, {
      ...exchange,
      ...position,
      symbol: key,
      mark_price: position.mark_price ?? exchange.mark_price,
      unrealized_pnl: position.unrealized_pnl ?? exchange.unrealized_pnl,
      leverage: position.leverage ?? exchange.leverage,
      margin_mode: position.margin_mode ?? exchange.margin_mode,
      contracts: position.contracts ?? exchange.contracts,
      contract_size: position.contract_size ?? exchange.contract_size,
      broker_sync_at: position.broker_sync_at ?? exchange.broker_sync_at,
      sync_status: position.sync_status ?? exchange.sync_status,
      status: position.status ?? exchange.status,
      source: position.source ?? exchange.source,
      mode: position.mode ?? exchange.mode,
      instId: position.instId ?? exchange.instId,
      ccxt_symbol: position.ccxt_symbol ?? exchange.ccxt_symbol,
      protective_orders: position.protective_orders ?? exchange.protective_orders,
      orders: position.orders ?? exchange.orders,
      market_context: position.market_context ?? exchange.market_context,
      decision_context: position.decision_context ?? exchange.decision_context,
      open_reason: position.open_reason ?? exchange.open_reason,
    });
  };

  exchangePositions.forEach(putExchange);
  journalPositions.forEach(putJournal);
  return order.map((key) => bySymbol.get(key)).filter((item): item is Position => Boolean(item));
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

export function AdaptivePolicyBadge({
  controller,
  experiment,
  reviewController,
  canary,
}: {
  controller?: AdaptivePolicyControllerStatus;
  experiment?: ShadowScoringExperimentStatus;
  reviewController?: ShadowScoreReviewControllerStatus;
  canary?: ShadowScoreCanaryStatus;
}) {
  const strong = controller?.active_zones?.strong_min_score;
  const gray = controller?.active_zones?.gray_min_score;
  if (strong === undefined || gray === undefined) return null;
  const status = controller?.status || "baseline";
  const revision = controller?.revision ?? 0;
  const experimentRoutingError = experiment?.active_for_routing === true;
  const tone = controller?.state_error || status === "error" || experimentRoutingError
    ? "border-ttcc-red/50 text-ttcc-red"
    : status === "staged"
      ? "border-ttcc-yellow/50 text-ttcc-yellow"
      : status === "active" || revision > 0
        ? "border-ttcc-green/40 text-ttcc-green"
        : "border-ttcc-border text-ttcc-text-secondary";
  const coverageFailures = controller?.strategy_coverage_failures?.length ?? 0;
  const experimentValid = experiment?.score_coverage?.valid;
  const experimentTotal = experiment?.score_coverage?.total;
  const hasExperimentCoverage = experimentValid !== undefined && experimentTotal !== undefined;
  const scoreDelta = experiment?.score_delta_v2_minus_v1?.average;
  const readinessStatus = experiment?.review_eligibility?.status;
  const readinessBlockers = experiment?.review_eligibility?.blocking_reasons ?? [];
  const calibration = experiment?.threshold_calibration;
  const calibrationCandidate = calibration?.candidate_thresholds;
  const calibrationStrong = calibrationCandidate?.strong_min_score;
  const calibrationGray = calibrationCandidate?.gray_min_score;
  const hasCalibrationCandidate = calibrationStrong !== undefined
    && calibrationGray !== undefined;
  const calibrationValidationDelta = calibration
    ?.objective_comparison_vs_active_v1?.validation_delta_v2_minus_v1;
  const transitions = Object.entries(experiment?.zone_transitions ?? {})
    .map(([transition, count]) => `${transition}:${count}`)
    .join(", ");
  const title = [
    `Adaptive policy ${status}`,
    `effective ${strong}/${gray}, revision ${revision}`,
    controller?.effective_source ? `source ${controller.effective_source}` : "",
    controller?.last_action ? `action ${controller.last_action}` : "",
    controller?.last_reason ? `reason ${controller.last_reason}` : "",
    coverageFailures ? `${coverageFailures} strategy coverage gate(s) pending` : "",
    hasExperimentCoverage ? `V2 shadow coverage ${experimentValid}/${experimentTotal}` : "",
    calibration?.status ? `V2 calibration ${calibration.status}` : "",
    hasCalibrationCandidate ? `V2 candidate ${calibrationStrong}/${calibrationGray}` : "",
    calibrationValidationDelta !== undefined && calibrationValidationDelta !== null
      ? `V2 holdout objective delta ${calibrationValidationDelta}`
      : "",
    calibration?.sample_reasons?.length
      ? `V2 calibration blockers ${calibration.sample_reasons.join(",")}`
      : "",
    reviewController?.status
      ? `V2 review ${reviewController.status}`
      : "",
    reviewController?.candidate
      ? `V2 review confirmations ${reviewController.candidate.confirmations ?? 0}/${reviewController.candidate.required_confirmations ?? 0}`
      : "",
    reviewController?.operator_approved === false
      ? "V2 operator approved false"
      : "",
    reviewController?.active_for_routing === false
      ? "V2 active for routing false"
      : "",
    canary?.status ? `V2 canary ${canary.status}` : "",
    canary?.routing_enabled
      ? `V2 canary allocation ${(canary.allocation_rate ?? 0) * 100}%, risk x${canary.risk_multiplier ?? 0}`
      : "",
    canary?.candidate_thresholds
      ? `V2 canary zones ${canary.candidate_thresholds.strong_min_score ?? "--"}/${canary.candidate_thresholds.gray_min_score ?? "--"}`
      : "",
    canary?.candidate_fingerprint
      ? `V2 candidate fingerprint ${canary.candidate_fingerprint.slice(0, 12)}`
      : "",
    canary?.approval_id ? `V2 approval ${canary.approval_id.slice(0, 12)}` : "",
    canary?.rollback_metrics?.closed_trades !== undefined
      ? `V2 canary closes ${canary.rollback_metrics.closed_trades}, LCB ${canary.rollback_metrics.average_r_lower_bound ?? "--"}, PF ${canary.rollback_metrics.profit_factor ?? "--"}, cumulative R ${canary.rollback_metrics.cumulative_r ?? 0}`
      : "",
    canary?.last_reason ? `V2 canary reason ${canary.last_reason}` : "",
    readinessStatus ? `V2 readiness ${readinessStatus}` : "",
    readinessBlockers.length ? `V2 blockers ${readinessBlockers.join(",")}` : "",
    scoreDelta !== undefined && scoreDelta !== null ? `V2 score delta ${scoreDelta}` : "",
    transitions ? `V2 zone transitions ${transitions}` : "",
    experimentRoutingError ? "error V2 unexpectedly marked active for routing" : "",
    controller?.state_error ? `error ${controller.state_error}` : "",
  ].filter(Boolean).join(" | ");
  const ariaLabel = [
    `Adaptive policy strong ${strong}, gray ${gray}, revision ${revision}`,
    hasExperimentCoverage ? `V2 coverage ${experimentValid} of ${experimentTotal}` : "",
  ].filter(Boolean).join(", ");
  return (
    <span
      className={cn(
        "hidden h-5 shrink-0 items-center gap-1 rounded border px-1.5 font-mono text-[9px] font-semibold uppercase tabular md:inline-flex",
        tone
      )}
      title={title}
      aria-label={ariaLabel}
    >
      <SlidersHorizontal className="h-2.5 w-2.5" />
      <span>ADP {strong}/{gray} R{revision}</span>
      {canary?.routing_enabled ? (
        <span className="border-l border-current/30 pl-1 text-ttcc-yellow">V2 CANARY</span>
      ) : null}
      {hasExperimentCoverage ? (
        <span className="border-l border-current/30 pl-1">V2 {experimentValid}/{experimentTotal}</span>
      ) : null}
    </span>
  );
}

// ====================================================================
// Trader — center content for the /trader route.
// Heavy metrics/controls live in the TerminalLayout shell.
// ====================================================================

type TraderTab = "positions" | "history" | "alerts";

type TraderRouteContext = {
  status: Status | null;
  tickers: TickerEntry[];
  loading: boolean;
};

export function Trader() {
  const { t } = useTranslation();
  const routeContext = useOutletContext<TraderRouteContext | undefined>();
  const hasRouteContext = routeContext !== undefined;
  const [localStatus, setLocalStatus] = useState<Status | null>(null);
  const [localTickers, setLocalTickers] = useState<TickerEntry[]>([]);
  const [localLoading, setLocalLoading] = useState(true);
  const [tab, setTab] = useState<TraderTab>("positions");
  const status = hasRouteContext ? routeContext?.status ?? null : localStatus;
  const tickers = hasRouteContext ? routeContext?.tickers ?? [] : localTickers;
  const loading = hasRouteContext ? routeContext?.loading ?? false : localLoading;

  const loadStatus = useCallback(async () => {
    try {
      const next = await request<Status>("/api/trader/status");
      setLocalStatus(next);
      setLocalLoading(false);
    } catch {
      /* silent */
    }
  }, []);

  const loadTicker = useCallback(async () => {
    try {
      const r = await request<{ tickers: TickerEntry[] }>(
        `/api/trader/ticker?symbols=${TICKER_SYMBOLS.join(",")}`
      );
      setLocalTickers(r.tickers ?? []);
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    if (hasRouteContext) return undefined;
    loadStatus();
    loadTicker();
    const sTimer = window.setInterval(loadStatus, STATUS_REFRESH_MS);
    const tTimer = window.setInterval(loadTicker, TICKER_REFRESH_MS);
    return () => {
      window.clearInterval(sTimer);
      window.clearInterval(tTimer);
    };
  }, [hasRouteContext, loadStatus, loadTicker]);

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
