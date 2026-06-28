import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Banknote,
  Calendar,
  Filter,
  Flame,
  GaugeCircle,
  History as HistoryIcon,
  Loader2,
  Target,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fmtUsd,
  fmtPct,
  fmtTime,
  colorClass,
  Pill,
} from "@/pages/Trader";

// ============= Types =============
type HistoryStats = {
  total: number;
  wins: number;
  losses: number;
  winrate: number;
  total_pnl_usd: number;
  avg_pnl_usd: number;
  best_trade_usd: number;
  worst_trade_usd: number;
  avg_rr: number;
  avg_duration_s: number;
  max_consec_wins: number;
  max_consec_losses: number;
  by_symbol: Record<string, { wins: number; losses: number; pnl: number; n: number; winrate_pct: number }>;
  by_regime: Record<string, { wins: number; losses: number; pnl: number; n: number; winrate_pct: number }>;
  by_exit_reason: Record<string, { n: number; pnl: number }>;
};

type Trade = {
  closed_at: string;
  symbol: string;
  side: string;
  entry: number;
  exit_price: number;
  position_size: number;
  pnl_usd: number;
  rr_ratio: number;
  exit_reason: string;
  opened_at: string;
  regime: string;
  confluence_score: number;
};

type HistoryResponse = {
  trades: Trade[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
};

const REFRESH_MS = 30000;
const ALL_SYMBOLS = ["", "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT", "DOGE-USDT", "ADA-USDT", "AVAX-USDT", "LINK-USDT", "DOT-USDT"];

const fmtDuration = (s: number): string => {
  if (!s || s <= 0) return "—";
  if (s < 3600) return Math.round(s / 60) + "m";
  if (s < 86400) return (s / 3600).toFixed(1) + "h";
  return (s / 86400).toFixed(1) + "d";
};

// ============= Helpers =============
function buildEquityCurve(trades: Trade[]): { ts: string; cumulative: number }[] {
  // Sort by close time ascending, compute cumulative PnL
  const sorted = [...trades].sort((a, b) => a.closed_at.localeCompare(b.closed_at));
  let cum = 0;
  return sorted.map((t) => {
    cum += parseFloat(String(t.pnl_usd));
    return { ts: t.closed_at, cumulative: cum };
  });
}

function EquitySparkline({ data, height = 120 }: { data: { ts: string; cumulative: number }[]; height?: number }) {
  if (data.length < 2) {
    return (
      <div className="flex h-[120px] items-center justify-center rounded-md border bg-muted/30 text-xs text-muted-foreground">
        Need ≥ 2 trades to render equity curve
      </div>
    );
  }
  const W = 800; // viewBox width
  const H = height;
  const padX = 10;
  const padY = 10;
  const minY = Math.min(...data.map((d) => d.cumulative));
  const maxY = Math.max(...data.map((d) => d.cumulative));
  const rangeY = Math.max(maxY - minY, 0.01);
  const xStep = (W - padX * 2) / Math.max(data.length - 1, 1);
  const points = data.map((d, i) => {
    const x = padX + i * xStep;
    const y = padY + ((maxY - d.cumulative) / rangeY) * (H - padY * 2);
    return [x, y] as const;
  });
  const pathD = points.map(([x, y], i) => (i === 0 ? `M ${x},${y}` : `L ${x},${y}`)).join(" ");
  const lastY = points[points.length - 1][1];
  const isUp = data[data.length - 1].cumulative >= data[0].cumulative;
  const color = isUp ? "rgb(34 197 94)" : "rgb(239 68 68)"; // green-500 / red-500
  const fillD = `${pathD} L ${points[points.length - 1][0]},${H - padY} L ${points[0][0]},${H - padY} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" preserveAspectRatio="none" style={{ height }}>
      <defs>
        <linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.25} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={fillD} fill="url(#equity-fill)" />
      <path d={pathD} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
      <circle cx={points[points.length - 1][0]} cy={lastY} r={3} fill={color} />
    </svg>
  );
}

function CalendarHeatmap({ data }: { data: Trade[] }) {
  // Group trades by date (last 60 days)
  const days = 60;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const counts: Record<string, { n: number; pnl: number }> = {};
  for (const t of data) {
    const day = t.closed_at?.substring(0, 10);
    if (!day) continue;
    if (!counts[day]) counts[day] = { n: 0, pnl: 0 };
    counts[day].n += 1;
    counts[day].pnl += parseFloat(String(t.pnl_usd));
  }
  // Build a row for each day, last 60 days
  const cells: { date: string; n: number; pnl: number }[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    const ds = d.toISOString().substring(0, 10);
    cells.push({
      date: ds,
      n: counts[ds]?.n ?? 0,
      pnl: counts[ds]?.pnl ?? 0,
    });
  }
  // Color: green intensity based on profit, red based on loss
  const getColor = (n: number, pnl: number) => {
    if (n === 0) return "bg-muted/40";
    if (pnl > 0) return "bg-green-500/70 hover:bg-green-500";
    if (pnl < 0) return "bg-red-500/70 hover:bg-red-500";
    return "bg-amber-500/50";
  };
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
        <span>Last {days} days · 1 cell = 1 day</span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-3 rounded bg-muted/40 border" /> no trade
          <span className="h-3 w-3 rounded bg-green-500/70" /> win
          <span className="h-3 w-3 rounded bg-red-500/70" /> loss
        </span>
      </div>
      <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${days}, minmax(0, 1fr))` }}>
        {cells.map((c) => (
          <div
            key={c.date}
            title={`${c.date}: ${c.n} trade${c.n !== 1 ? "s" : ""} · ${c.pnl >= 0 ? "+" : ""}$${c.pnl.toFixed(2)}`}
            className={cn("aspect-square rounded-sm transition-colors cursor-help", getColor(c.n, c.pnl))}
          />
        ))}
      </div>
    </div>
  );
}

async function request<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" } });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

// ============= Page =============
export function TraderHistory() {
  const { t } = useTranslation();
  const [stats, setStats] = useState<HistoryStats | null>(null);
  const [page, setPage] = useState<HistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [symbol, setSymbol] = useState("");
  const [result, setResult] = useState<"" | "win" | "loss">("");
  const [limit, setLimit] = useState(50);
  const [offset, setOffset] = useState(0);

  const buildQuery = useCallback(() => {
    const p = new URLSearchParams();
    if (symbol) p.set("symbol", symbol);
    if (result) p.set("result", result);
    p.set("limit", String(limit));
    p.set("offset", String(offset));
    return p.toString();
  }, [symbol, result, limit, offset]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, p] = await Promise.all([
        request<HistoryStats>("/api/trader/history/stats"),
        request<HistoryResponse>(`/api/trader/history?${buildQuery()}`),
      ]);
      setStats(s);
      setPage(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [buildQuery]);

  useEffect(() => {
    load();
    const t = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(t);
  }, [load]);

  const applyFilters = () => { setOffset(0); load(); };
  const resetFilters = () => { setSymbol(""); setResult(""); setLimit(50); setOffset(0); load(); };
  const prevPage = () => { setOffset(Math.max(0, offset - limit)); };
  const nextPage = () => { setOffset(offset + limit); };

  const bySym = useMemo(
    () => Object.entries(stats?.by_symbol || {}) as [string, { wins: number; losses: number; pnl: number; n: number; winrate_pct: number }][],
    [stats],
  );
  const byRegime = useMemo(
    () => Object.entries(stats?.by_regime || {}) as [string, { wins: number; losses: number; pnl: number; n: number; winrate_pct: number }][],
    [stats],
  );
  const byReason = useMemo(
    () => Object.entries(stats?.by_exit_reason || {}) as [string, { n: number; pnl: number }][],
    [stats],
  );

  const equityCurve = useMemo(() => buildEquityCurve(page?.trades || []), [page]);

  // ============= Derived hero metrics =============
  const totalPnl = stats?.total_pnl_usd ?? 0;
  const isUp = totalPnl >= 0;
  const totalTrades = stats?.total ?? 0;
  const winrate = stats?.winrate ?? 0;
  const avgPnl = stats?.avg_pnl_usd ?? 0;
  const avgRr = stats?.avg_rr ?? 0;
  const bestTrade = stats?.best_trade_usd ?? 0;
  const worstTrade = stats?.worst_trade_usd ?? 0;
  const maxWins = stats?.max_consec_wins ?? 0;
  const maxLosses = stats?.max_consec_losses ?? 0;
  const avgDur = stats?.avg_duration_s ?? 0;

  return (
    <div className="flex flex-col gap-6 p-6 lg:p-8">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">

        {/* Header */}
        <header className="flex flex-col gap-4 border-b pb-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs font-medium text-muted-foreground">
              <HistoryIcon className="h-3.5 w-3.5" />
              {t("traderHistory.badge", "Trade history")}
            </div>
            <h1 className="text-3xl font-bold tracking-tight">
              {t("traderHistory.title", "Trade history")}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t("traderHistory.lastUpdate", "Auto-refresh every 30s · Newest first · Testnet only")}
            </p>
          </div>
          <a
            href="/trader"
            className="inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium transition hover:bg-muted"
          >
            <ArrowLeft className="h-4 w-4" />
            {t("traderHistory.backToDashboard", "Back to Dashboard")}
          </a>
        </header>

        {error ? (
          <section className="rounded-md border border-amber-500/30 bg-amber-500/5 p-4 text-sm">
            <div className="font-medium text-amber-700 dark:text-amber-300">{error}</div>
          </section>
        ) : null}

        {/* Hero panel — performance summary */}
        {stats && (
          <section
            className={cn(
              "relative overflow-hidden rounded-xl border bg-gradient-to-br p-6 lg:p-8",
              isUp
                ? "from-green-500/5 via-card to-card border-green-500/20"
                : "from-red-500/5 via-card to-card border-red-500/20"
            )}
          >
            <div className="pointer-events-none absolute -right-4 -top-4 opacity-[0.04]">
              <Banknote className="h-48 w-48" />
            </div>
            <div className="relative grid gap-6 md:grid-cols-3">
              <div className="md:col-span-2 space-y-2">
                <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <Banknote className="h-3.5 w-3.5" />
                  Total Realized PnL
                </div>
                <div className={cn(
                  "text-5xl font-bold tabular-nums lg:text-6xl",
                  isUp ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"
                )}>
                  {isUp ? "+" : ""}{totalPnl.toFixed(2)}
                  <span className="ml-2 text-base font-medium text-muted-foreground">USD</span>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Pill tone={isUp ? "ok" : "fail"}>{isUp ? "PROFIT" : "LOSS"}</Pill>
                  <span className="text-muted-foreground">
                    from <b className="text-foreground">{totalTrades}</b> closed trade{totalTrades !== 1 ? "s" : ""}
                  </span>
                </div>
              </div>
              <div className="space-y-3">
                <div className="rounded-lg border bg-background/60 p-3 backdrop-blur">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground inline-flex items-center gap-1.5">
                      <GaugeCircle className="h-3 w-3" /> Winrate
                    </span>
                    <span className={cn(
                      "font-bold tabular-nums",
                      winrate >= 50 ? "text-green-600 dark:text-green-400" : "text-foreground"
                    )}>{fmtPct(winrate)}</span>
                  </div>
                </div>
                <div className="rounded-lg border bg-background/60 p-3 backdrop-blur">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground inline-flex items-center gap-1.5">
                      <TrendingUp className="h-3 w-3" /> Avg PnL / trade
                    </span>
                    <span className={cn(
                      "font-bold tabular-nums",
                      avgPnl > 0 ? "text-green-600 dark:text-green-400" : avgPnl < 0 ? "text-red-600 dark:text-red-400" : ""
                    )}>{avgPnl >= 0 ? "+" : ""}{avgPnl.toFixed(2)}</span>
                  </div>
                </div>
                <div className="rounded-lg border bg-background/60 p-3 backdrop-blur">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground inline-flex items-center gap-1.5">
                      <Target className="h-3 w-3" /> Avg R:R
                    </span>
                    <span className="font-bold tabular-nums">1:{avgRr.toFixed(2)}</span>
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* Equity curve + summary metrics */}
        {stats && (
          <section className="grid gap-4 lg:grid-cols-3">
            <div className="rounded-lg border bg-card p-4 lg:col-span-2">
              <div className="mb-3 flex items-center justify-between">
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Equity curve
                </div>
                <div className="text-xs text-muted-foreground tabular-nums">
                  start: 0 → end: <span className={cn("font-semibold", isUp ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400")}>
                    {isUp ? "+" : ""}{totalPnl.toFixed(2)}
                  </span>
                </div>
              </div>
              <EquitySparkline data={equityCurve} />
            </div>
            <div className="grid grid-cols-2 gap-3 content-start">
              <SmallStat icon={ArrowUp} label="Best trade" value={fmtUsd(bestTrade)} tone="good" />
              <SmallStat icon={ArrowDown} label="Worst trade" value={fmtUsd(worstTrade)} tone="bad" />
              <SmallStat icon={Flame} label="Streak W / L" value={`${maxWins} / ${maxLosses}`} />
              <SmallStat icon={Calendar} label="Avg duration" value={fmtDuration(avgDur)} />
            </div>
          </section>
        )}

        {/* Activity heatmap (last 60 days) */}
        {page && (
          <section className="rounded-lg border bg-card p-4">
            <div className="mb-3 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <Calendar className="h-3.5 w-3.5" />
              Trading activity heatmap
            </div>
            <CalendarHeatmap data={page.trades} />
          </section>
        )}

        {/* Filters + table */}
        <section>
          <div className="mb-3 flex items-center gap-2">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
              {t("traderHistory.closedTitle", "Closed trades")}
            </h2>
          </div>
          <div className="mb-3 flex flex-wrap items-center gap-3 rounded-md border bg-card p-3">
            <label className="text-xs text-muted-foreground">{t("traderHistory.symbol", "Symbol")}</label>
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="rounded-md border bg-background px-2 py-1 text-sm"
            >
              {ALL_SYMBOLS.map((s) => (
                <option key={s} value={s}>{s || "All"}</option>
              ))}
            </select>
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-muted-foreground">{t("traderHistory.result", "Result")}</span>
              <div className="inline-flex rounded-md border bg-background p-0.5 text-xs">
                {([["", "All"], ["win", "Wins"], ["loss", "Losses"]] as const).map(([v, label]) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setResult(v as "" | "win" | "loss")}
                    className={cn(
                      "rounded px-2.5 py-1 font-medium transition-colors",
                      result === v ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <label className="text-xs text-muted-foreground">{t("traderHistory.perPage", "Per page")}</label>
            <select
              value={limit}
              onChange={(e) => setLimit(parseInt(e.target.value) || 50)}
              className="rounded-md border bg-background px-2 py-1 text-sm"
            >
              <option value={20}>20</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
            <button
              type="button"
              onClick={applyFilters}
              className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1 text-sm font-medium text-primary-foreground transition hover:opacity-90"
            >
              {t("traderHistory.apply", "Apply")}
            </button>
            <button
              type="button"
              onClick={resetFilters}
              className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1 text-sm font-medium transition hover:bg-muted"
            >
              {t("traderHistory.reset", "Reset")}
            </button>
          </div>

          {loading && !page ? (
            <div className="flex items-center justify-center gap-2 rounded-md border bg-card py-12 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("common.loading", "Loading…")}
            </div>
          ) : (
            <ClosedTradesTableFull trades={page?.trades || []} />
          )}

          {/* Pagination */}
          {page ? (
            <div className="mt-3 flex items-center justify-end gap-2 text-sm text-muted-foreground">
              <span>
                {t("traderHistory.showing", "Showing {{start}}-{{end}} of {{total}}", {
                  start: page.total === 0 ? 0 : page.offset + 1,
                  end: Math.min(page.offset + page.limit, page.total),
                  total: page.total,
                })}
              </span>
              <button
                type="button"
                onClick={prevPage}
                disabled={page.offset === 0}
                className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-sm disabled:opacity-40"
              >
                <ArrowLeft className="h-3.5 w-3.5" /> {t("common.prev", "Prev")}
              </button>
              <button
                type="button"
                onClick={nextPage}
                disabled={page.offset + page.limit >= page.total}
                className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-sm disabled:opacity-40"
              >
                {t("common.next", "Next")} <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : null}
        </section>

        {/* Performance breakdown */}
        {stats && (
          <section>
            <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">
              {t("traderHistory.breakdownTitle", "Performance breakdown")}
            </h2>
            <div className="grid gap-4 lg:grid-cols-3">
              <BreakdownCard
                title={t("traderHistory.bySymbol", "By symbol")}
                rows={bySym}
                colHeaders={["Symbol", "W/L", "Win%", "PnL"]}
                pnlCol={3}
              />
              <BreakdownCard
                title={t("traderHistory.byRegime", "By regime")}
                rows={byRegime}
                colHeaders={["Regime", "W/L", "Win%", "PnL"]}
                pnlCol={3}
              />
              <BreakdownCard
                title={t("traderHistory.byReason", "By exit reason")}
                rows={byReason}
                colHeaders={["Reason", "n", "PnL"]}
                pnlCol={2}
                simple
              />
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

// ============= Small stat card (for sub-grid) =============
function SmallStat({
  label, value, icon: Icon, tone,
}: {
  label: string;
  value: string;
  icon?: React.ComponentType<{ className?: string }>;
  tone?: "good" | "bad" | "neutral";
}) {
  const valueClass = tone === "good" ? "text-green-600 dark:text-green-400"
    : tone === "bad" ? "text-red-600 dark:text-red-400" : "";
  return (
    <div className="rounded-md border bg-card p-3">
      <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {Icon ? <Icon className="h-3 w-3" /> : null}
        {label}
      </div>
      <div className={cn("mt-1 text-lg font-bold tabular-nums", valueClass)}>{value}</div>
    </div>
  );
}

// ============= Breakdown card =============
function BreakdownCard({
  title, rows, colHeaders, pnlCol, simple,
}: {
  title: string;
  rows: [string, any][];
  colHeaders: string[];
  pnlCol: number;
  simple?: boolean;
}) {
  const sorted = [...rows].sort((a, b) => (b[1].pnl ?? 0) - (a[1].pnl ?? 0));
  return (
    <div className="rounded-md border bg-card p-4">
      <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</div>
      {sorted.length === 0 ? (
        <div className="py-4 text-center text-sm text-muted-foreground">No data</div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-muted-foreground">
              {colHeaders.map((h, i) => (
                <th key={i} className={cn("py-1 font-medium", i === pnlCol ? "text-right" : i === 0 ? "text-left" : "text-left")}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map(([k, v]) => (
              <tr key={k} className="border-t">
                <td className="py-1.5 font-medium">{k}</td>
                {simple ? (
                  <>
                    <td className="tabular-nums">{v.n}</td>
                    <td className={cn("text-right tabular-nums", colorClass(v.pnl))}>{fmtUsd(v.pnl)}</td>
                  </>
                ) : (
                  <>
                    <td className="tabular-nums">{v.wins}W/{v.losses}L</td>
                    <td className="tabular-nums">{v.winrate_pct}%</td>
                    <td className={cn("text-right tabular-nums", colorClass(v.pnl))}>{fmtUsd(v.pnl)}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ============= Closed trades table =============
function ClosedTradesTableFull({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) {
    return (
      <div className="rounded-md border bg-card px-3 py-6 text-center text-sm text-muted-foreground">
        No closed trades yet (or no match for current filter)
      </div>
    );
  }
  return (
    <div className="rounded-md border bg-card">
      <table className="w-full text-sm">
        <thead className="border-b bg-muted/30 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Closed</th>
            <th className="px-3 py-2 text-left font-medium">Symbol</th>
            <th className="px-3 py-2 text-left font-medium">Side</th>
            <th className="px-3 py-2 text-right font-medium">Entry</th>
            <th className="px-3 py-2 text-right font-medium">Exit</th>
            <th className="px-3 py-2 text-right font-medium">Size</th>
            <th className="px-3 py-2 text-right font-medium">PnL</th>
            <th className="px-3 py-2 text-right font-medium">R:R</th>
            <th className="px-3 py-2 text-left font-medium">Reason</th>
            <th className="px-3 py-2 text-left font-medium">Duration</th>
            <th className="px-3 py-2 text-left font-medium">Regime</th>
            <th className="px-3 py-2 text-right font-medium">Conf.</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => {
            const pnl = parseFloat(String(t.pnl_usd));
            const reason = t.exit_reason || "";
            const tone = reason.includes("profit") || reason.includes("tp") ? "tp"
              : reason.includes("stop") || reason.includes("sl") ? "sl" : "neutral";
            return (
              <tr key={i} className="border-t hover:bg-muted/30">
                <td className="px-3 py-2 text-muted-foreground">{fmtTime(t.closed_at)}</td>
                <td className="px-3 py-2 font-medium">{t.symbol}</td>
                <td className="px-3 py-2"><Pill tone={t.side === "buy" ? "long" : "short"}>{t.side.toUpperCase()}</Pill></td>
                <td className="px-3 py-2 text-right tabular-nums">{t.entry}</td>
                <td className="px-3 py-2 text-right tabular-nums">{t.exit_price}</td>
                <td className="px-3 py-2 text-right tabular-nums">{t.position_size}</td>
                <td className={cn("px-3 py-2 text-right font-semibold tabular-nums", colorClass(pnl))}>
                  {pnl >= 0 ? <ArrowUp className="mr-1 inline h-3 w-3" /> : <ArrowDown className="mr-1 inline h-3 w-3" />}
                  {fmtUsd(pnl)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{t.rr_ratio ? "1:" + parseFloat(String(t.rr_ratio)).toFixed(2) : "—"}</td>
                <td className="px-3 py-2"><Pill tone={tone}>{reason}</Pill></td>
                <td className="px-3 py-2 text-muted-foreground">
                  {(() => {
                    try {
                      const ms = new Date(t.closed_at).getTime() - new Date(t.opened_at).getTime();
                      return fmtDuration(Math.round(ms / 1000));
                    } catch { return "—"; }
                  })()}
                </td>
                <td className="px-3 py-2">{t.regime || "—"}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {t.confluence_score != null ? ((t.confluence_score >= 0 ? "+" : "") + t.confluence_score) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}