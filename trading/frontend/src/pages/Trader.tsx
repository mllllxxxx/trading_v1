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
  SideBadge,
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
export { ConfluenceBadge, RrBadge, SideBadge } from "@/components/terminal/PositionCard";

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
};

type Status = {
  timestamp?: string;
  running?: boolean;
  symbols?: string[];
  stats?: Stats;
  positions?: Position[];
  closed_trades?: ClosedTrade[];
  kill_switch_active?: boolean;
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
          return <PositionCard key={`${p.symbol}-${i}`} p={p} mark={tk?.price ?? null} />;
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
        <ClosedTradesTable trades={slice} />
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

export function ClosedTradesTable({ trades }: { trades: ClosedTrade[] }) {
  if (!trades.length) {
    return null;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead className="bg-ttcc-surface-2 text-[10px] uppercase tracking-wider text-ttcc-text-secondary">
          <tr className="border-b border-ttcc-border">
            <th className="px-2.5 py-1.5 text-left font-medium">Closed</th>
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
            const tone = reason.includes("profit") || reason.includes("tp")
              ? "tp"
              : reason.includes("stop") || reason.includes("sl")
              ? "sl"
              : "neutral";
            return (
              <tr key={i} className="border-b border-ttcc-border/40 hover:bg-ttcc-surface-2">
                <td className="px-2.5 py-1 font-mono tabular text-ttcc-text-muted">{fmtTime(t.closed_at)}</td>
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
  const [status, setStatus] = useState<Status | null>(null);
  const [tickers, setTickers] = useState<TickerEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<TraderTab>("positions");

  const loadStatus = useCallback(async () => {
    try {
      const next = await request<Status>("/api/trader/status");
      setStatus(next);
      setLoading(false);
    } catch {
      /* silent */
    }
  }, []);

  const loadTicker = useCallback(async () => {
    try {
      const r = await request<{ tickers: TickerEntry[] }>(
        `/api/trader/ticker?symbols=${TICKER_SYMBOLS.join(",")}`
      );
      setTickers(r.tickers ?? []);
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    loadStatus();
    loadTicker();
    const sTimer = window.setInterval(loadStatus, STATUS_REFRESH_MS);
    const tTimer = window.setInterval(loadTicker, TICKER_REFRESH_MS);
    return () => {
      window.clearInterval(sTimer);
      window.clearInterval(tTimer);
    };
  }, [loadStatus, loadTicker]);

  const positions = useMemo(() => status?.positions ?? [], [status?.positions]);
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
