import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Activity,
  History as HistoryIcon,
  BarChart3,
  SlidersHorizontal,
  TrendingUp,
  Save,
  Trophy,
  Target,
} from "lucide-react";
import { toast } from "sonner";
import {
  PositionCard,
  EmptyPositions,
} from "@/components/terminal/PositionCard";
import { ClosedTradesTable } from "@/pages/Trader";
import { CorrelationMatrix } from "@/components/charts/CorrelationMatrix";
import type { TickerEntry } from "@/components/terminal/Ticker";
import { api } from "@/lib/api";
import type { ClosedTrade as ClosedTradeType, TraderStatusPayload } from "@/types/api";
import { useTraderStatusStore } from "@/stores/traderStatus";
import { useSettingsStore } from "@/stores/settings";
import { cn } from "@/lib/utils";

type ActiveTab = "history" | "confluence" | "correlation" | "settings";
type ClosedTrade = ClosedTradeType;
type StrategyTeamMetric = {
  team_id: string;
  team_name: string;
  strategy_id: string;
  strategy_name: string;
  method: string;
  color: string;
  preferred_playbook_ids?: string[];
  entry_style?: string;
  llm_guidance?: string;
  risk_personality?: string;
  team_capital_usd: number;
  target_risk_pct_equity: number;
  open_positions: number;
  closed_trades: number;
  wins: number;
  losses: number;
  winrate: number;
  realized_pnl_usd: number;
  unrealized_pnl_usd: number;
  current_equity_usd: number;
  max_drawdown_usd: number;
  max_drawdown_pct?: number;
  expectancy_r?: number;
  profit_factor?: number;
  wilson_winrate?: number;
  sample_reliability?: number;
  competition_score?: number;
  ranking_status?: "provisional" | "qualified";
  avg_actual_risk_pct_equity?: number | null;
  rank: number | null;
};
type StatusPayload = TraderStatusPayload & {
  strategy_teams?: StrategyTeamMetric[];
};

const TICKER_SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT"];

export function Cockpit() {
  const { status: storeStatus, tickers, loading } = useTraderStatusStore();
  const status = storeStatus as StatusPayload | null;
  const [activeTab, setActiveTab] = useState<ActiveTab>("history");

  const positions = useMemo(() => status?.positions ?? [], [status?.positions]);
  const recentTrades = useMemo(
    () => (status?.closed_trades ?? []).slice(-100).reverse(),
    [status?.closed_trades]
  );
  const watchlistSymbols = useMemo(
    () => status?.symbols ?? TICKER_SYMBOLS,
    [status?.symbols]
  );
  const strategyTeams = useMemo(
    () => status?.strategy_teams ?? [],
    [status?.strategy_teams]
  );

  return (
    <div className="flex h-full flex-col bg-ttcc-bg text-ttcc-text text-[12px] overflow-y-auto p-3.5 space-y-4 font-sans">
      {/* 1. Header Cockpit Label */}
      <div className="flex items-center justify-between border-b border-ttcc-border/60 pb-2 shrink-0">
        <div>
          <h1 className="text-sm font-bold uppercase tracking-widest text-ttcc-accent flex items-center gap-1.5">
            <TrendingUp className="h-4 w-4" /> Trading Control Cockpit
          </h1>
          <p className="text-[10px] text-ttcc-text-secondary mt-0.5">
            Realtime exchange execution desk integrated with AI reasoning co-pilot.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 text-[10px] text-ttcc-text-secondary tabular font-mono">
            <span className="tt-live-dot" />
            Live: {status?.timestamp ? new Date(status.timestamp).toLocaleTimeString() : "connecting..."}
          </span>
        </div>
      </div>

      <TeamLeaderboard teams={strategyTeams} loading={loading} />

      {/* 2. Active Positions Grid */}
      <div className="space-y-1.5 shrink-0">
        <div className="flex items-center justify-between px-1 text-[10px] uppercase font-bold text-ttcc-text-secondary tracking-wider">
          <span>Active Positions ({positions.length})</span>
          <span className="text-ttcc-text-muted">Leverage capped at 10x BTC / 3x Alts</span>
        </div>

        <div className="grid gap-3 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
          {loading && positions.length === 0 ? (
            <>
              <div className="h-28 rounded bg-ttcc-surface/50 border border-ttcc-border/40 animate-pulse" />
              <div className="h-28 rounded bg-ttcc-surface/50 border border-ttcc-border/40 animate-pulse" />
            </>
          ) : positions.length === 0 ? (
            <div className="col-span-full">
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
      </div>

      {/* 3. Bottom Panel Tabbed Workspace */}
      <div className="flex flex-col flex-1 min-h-[400px] border border-ttcc-border bg-ttcc-surface/20 rounded-md overflow-hidden">
        {/* Workspace Tab Header */}
        <div className="flex items-center justify-between border-b border-ttcc-border bg-ttcc-surface px-1 shrink-0">
          <div className="flex">
            <button
              onClick={() => setActiveTab("history")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-2 text-[10px] font-bold uppercase tracking-wider transition-colors border-r border-ttcc-border/40",
                activeTab === "history"
                  ? "bg-ttcc-bg text-ttcc-accent border-b border-b-ttcc-accent"
                  : "text-ttcc-text-secondary hover:text-ttcc-text hover:bg-ttcc-surface-2"
              )}
            >
              <HistoryIcon className="h-3.5 w-3.5" />
              Journal
            </button>
            <button
              onClick={() => setActiveTab("confluence")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-2 text-[10px] font-bold uppercase tracking-wider transition-colors border-r border-ttcc-border/40",
                activeTab === "confluence"
                  ? "bg-ttcc-bg text-ttcc-accent border-b border-b-ttcc-accent"
                  : "text-ttcc-text-secondary hover:text-ttcc-text hover:bg-ttcc-surface-2"
              )}
            >
              <Activity className="h-3.5 w-3.5" />
              Indicators Grid
            </button>
            <button
              onClick={() => setActiveTab("correlation")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-2 text-[10px] font-bold uppercase tracking-wider transition-colors border-r border-ttcc-border/40",
                activeTab === "correlation"
                  ? "bg-ttcc-bg text-ttcc-accent border-b border-b-ttcc-accent"
                  : "text-ttcc-text-secondary hover:text-ttcc-text hover:bg-ttcc-surface-2"
              )}
            >
              <BarChart3 className="h-3.5 w-3.5" />
              Correlation Matrix
            </button>
            <button
              onClick={() => setActiveTab("settings")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-2 text-[10px] font-bold uppercase tracking-wider transition-colors border-r border-ttcc-border/40",
                activeTab === "settings"
                  ? "bg-ttcc-bg text-ttcc-accent border-b border-b-ttcc-accent"
                  : "text-ttcc-text-secondary hover:text-ttcc-text hover:bg-ttcc-surface-2"
              )}
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
              Settings
            </button>
          </div>
        </div>

        {/* Workspace Panels */}
        <div className="flex-1 p-2 bg-ttcc-bg/40 overflow-y-auto">
          {activeTab === "history" && (
            <div className="space-y-1">
              <div className="text-[10px] uppercase font-bold text-ttcc-text-secondary tracking-wider px-1 pb-1">
                Closed Trades History Logs
              </div>
              <HistoryTab trades={recentTrades} loading={loading} />
            </div>
          )}

          {activeTab === "confluence" && (
            <div className="space-y-2">
              <div className="text-[10px] uppercase font-bold text-ttcc-text-secondary tracking-wider px-1">
                Asset Watchlist & Market Regime Indicators
              </div>
              <WatchlistGrid
                watchlist={watchlistSymbols}
                tickers={tickers}
                loading={loading}
              />
            </div>
          )}

          {activeTab === "correlation" && <CorrelationPanel />}

          {activeTab === "settings" && <CockpitSettings />}
        </div>
      </div>
    </div>
  );
}

function TeamLeaderboard({
  teams,
  loading,
}: {
  teams: StrategyTeamMetric[];
  loading: boolean;
}) {
  if (loading && teams.length === 0) {
    return (
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-24 rounded border border-ttcc-border/40 bg-ttcc-surface/50 animate-pulse" />
        ))}
      </div>
    );
  }

  if (!teams.length) {
    return null;
  }

  const rankedTeams = [...teams].sort(
    (left, right) => (left.rank ?? Number.MAX_SAFE_INTEGER) - (right.rank ?? Number.MAX_SAFE_INTEGER)
  );

  return (
    <div className="space-y-1.5 shrink-0">
      <div className="flex items-center justify-between px-1 text-[10px] uppercase font-bold text-ttcc-text-secondary tracking-wider">
        <span className="flex items-center gap-1.5">
          <Trophy className="h-3.5 w-3.5 text-ttcc-accent" />
          Strategy Team Tournament
        </span>
        <span className="text-ttcc-text-muted">composite / 30-trade gate</span>
      </div>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {rankedTeams.map((team) => (
          <div
            key={team.team_id}
            className={cn(
              "rounded border bg-ttcc-surface px-3 py-2.5",
              teamBorderClass(team.team_id)
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-[10px] font-bold text-ttcc-accent tabular">
                    #{team.rank ?? "-"}
                  </span>
                  <span className="truncate text-[12px] font-bold uppercase tracking-wider text-ttcc-text">
                    {team.team_name}
                  </span>
                  <span className="shrink-0 font-mono text-[8px] uppercase text-ttcc-text-muted">
                    {team.ranking_status === "qualified" ? "qualified" : "provisional"}
                  </span>
                </div>
                <div className="mt-0.5 truncate text-[10px] text-ttcc-text-secondary" title={team.strategy_name}>
                  {team.strategy_name}
                </div>
                <div
                  className="mt-0.5 truncate font-mono text-[9px] text-ttcc-text-muted"
                  title={team.entry_style || team.llm_guidance || team.method}
                >
                  {team.preferred_playbook_ids?.[0] ?? team.method}
                </div>
              </div>
              <span className="inline-flex shrink-0 items-center gap-1 rounded border border-ttcc-border bg-ttcc-bg px-1.5 py-0.5 font-mono text-[10px] text-ttcc-text-secondary">
                <Target className="h-3 w-3" />
                {formatPct(team.target_risk_pct_equity)}
              </span>
            </div>

            <div className="mt-2 grid grid-cols-4 gap-1.5">
              <TeamMetric label="Score" value={(team.competition_score ?? 0).toFixed(1)} tone={(team.competition_score ?? 0) >= 50 ? "good" : "warn"} />
              <TeamMetric label="WR" value={`${team.winrate.toFixed(1)}%`} tone={team.winrate >= 50 ? "good" : "warn"} />
              <TeamMetric label="Exp R" value={(team.expectancy_r ?? 0).toFixed(2)} tone={(team.expectancy_r ?? 0) > 0 ? "good" : "warn"} />
              <TeamMetric label="PF" value={(team.profit_factor ?? 0).toFixed(2)} tone={(team.profit_factor ?? 0) > 1 ? "good" : "warn"} />
            </div>

            <div className="mt-2 flex items-center justify-between gap-2 font-mono text-[10px] text-ttcc-text-muted tabular">
              <span>{team.closed_trades}/30 closed / {team.open_positions} open</span>
              <span>{formatSignedUsd(team.realized_pnl_usd)} / DD {formatUsd(team.max_drawdown_usd)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TeamMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "good" | "warn" | "bad";
}) {
  return (
    <div className="rounded border border-ttcc-border/60 bg-ttcc-surface-2 px-2 py-1">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-ttcc-text-muted">{label}</div>
      <div className={cn(
        "mt-0.5 truncate font-mono text-[11px] font-bold tabular",
        tone === "good" ? "text-ttcc-green" : tone === "bad" ? "text-ttcc-red" : "text-ttcc-yellow"
      )}>
        {value}
      </div>
    </div>
  );
}

/* ==================================================================== */
/*  Mini components for Tab panels                                      */
/* ==================================================================== */

// History Panel
function HistoryTab({ trades, loading }: { trades: ClosedTrade[]; loading: boolean }) {
  if (loading && !trades.length) {
    return (
      <div className="space-y-2 p-2 animate-pulse">
        <div className="h-5 bg-ttcc-surface rounded w-full" />
        <div className="h-5 bg-ttcc-surface rounded w-full" />
      </div>
    );
  }
  if (!trades.length) {
    return (
      <div className="flex h-24 items-center justify-center text-ttcc-text-secondary text-[11px]">
        No closed trades yet.
      </div>
    );
  }
  return <ClosedTradesTable trades={trades} />;
}

// Watchlist Grid & Market Regime Monitor
function WatchlistGrid({
  watchlist,
  tickers,
  loading,
}: {
  watchlist: string[];
  tickers: TickerEntry[];
  loading: boolean;
}) {
  if (loading && tickers.length === 0) {
    return (
      <div className="grid gap-2 grid-cols-2 md:grid-cols-4 p-1 animate-pulse">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-16 bg-ttcc-surface rounded" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid gap-3 grid-cols-2 md:grid-cols-4 p-1">
      {watchlist.map((symbol) => {
        const tk = tickers.find((t) => t.symbol === symbol);
        const change = tk?.change_24h_pct ?? 0;
        const up = change >= 0;
        return (
          <div
            key={symbol}
            className="flex flex-col justify-between rounded border border-ttcc-border bg-ttcc-surface p-2.5"
          >
            <div className="flex items-center justify-between">
              <span className="font-mono font-bold text-ttcc-text">
                {symbol.replace("-USDT", "")}
              </span>
              <span
                className={cn(
                  "font-mono text-[10px] font-bold px-1 py-0.5 rounded",
                  up
                    ? "bg-ttcc-green/10 text-ttcc-green border border-ttcc-green/20"
                    : "bg-ttcc-red/10 text-ttcc-red border border-ttcc-red/20"
                )}
              >
                {up ? "+" : ""}
                {change.toFixed(2)}%
              </span>
            </div>
            <div className="mt-2.5 flex items-baseline justify-between">
              <span className="font-mono text-sm font-bold text-ttcc-text tabular">
                ${tk?.price ? tk.price.toLocaleString() : "—"}
              </span>
              <span className="text-[9px] text-ttcc-text-secondary uppercase font-semibold">
                {change >= 1.5 ? "STRONG TREND" : change <= -1.5 ? "DOWNTREND" : "RANGING"}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Embedded Correlation Panel
function CorrelationPanel() {
  const [codes, setCodes] = useState("BTC-USDT,ETH-USDT,SOL-USDT,BNB-USDT");
  const [days, setDays] = useState<number>(90);
  const [method, setMethod] = useState<"pearson" | "spearman">("pearson");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [labels, setLabels] = useState<string[]>([]);
  const [matrix, setMatrix] = useState<number[][]>([]);

  const handleCompute = async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await api.getCorrelation(codes, days, method);
      setLabels(res.labels);
      setMatrix(res.matrix);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Compute failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3 p-1 text-[11px]">
      <div className="text-[10px] uppercase font-bold text-ttcc-text-secondary tracking-wider">
        Compute Asset Correlation Coefficient
      </div>

      <div className="grid gap-2 border border-ttcc-border bg-ttcc-surface/30 p-2.5 rounded">
        <div className="flex flex-col gap-1">
          <label className="font-semibold text-ttcc-text-secondary">Asset Codes</label>
          <input
            type="text"
            value={codes}
            onChange={(e) => setCodes(e.target.value)}
            placeholder="BTC-USDT,ETH-USDT"
            className="rounded border border-ttcc-border bg-ttcc-bg px-2 py-1 text-xs text-ttcc-text outline-none focus:border-ttcc-accent/60"
          />
        </div>

        <div className="flex flex-wrap gap-4 items-center">
          <div className="flex flex-col gap-1">
            <span className="font-semibold text-ttcc-text-secondary">Window (Days)</span>
            <div className="flex gap-1">
              {[30, 60, 90, 180].map((w) => (
                <button
                  key={w}
                  type="button"
                  onClick={() => setDays(w)}
                  className={cn(
                    "px-2 py-0.5 rounded border text-[10px]",
                    days === w
                      ? "bg-ttcc-accent text-white border-ttcc-accent"
                      : "border-ttcc-border bg-ttcc-surface text-ttcc-text-secondary hover:text-ttcc-text"
                  )}
                >
                  {w}d
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <span className="font-semibold text-ttcc-text-secondary">Method</span>
            <div className="flex gap-1">
              {(["pearson", "spearman"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMethod(m)}
                  className={cn(
                    "px-2 py-0.5 rounded border text-[10px] capitalize",
                    method === m
                      ? "bg-ttcc-accent text-white border-ttcc-accent"
                      : "border-ttcc-border bg-ttcc-surface text-ttcc-text-secondary hover:text-ttcc-text"
                  )}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={handleCompute}
            disabled={loading}
            className="mt-auto h-7 px-3 rounded bg-ttcc-accent text-white font-bold hover:opacity-90 disabled:opacity-40 flex items-center gap-1.5"
          >
            {loading ? <Loader2 className="h-3 w-3" /> : <Save className="h-3.5 w-3.5" />}
            Compute
          </button>
        </div>
      </div>

      {error && <div className="text-ttcc-red font-semibold">{error}</div>}

      {labels.length > 0 && (
        <div className="border border-ttcc-border bg-ttcc-surface/20 rounded p-2">
          <CorrelationMatrix labels={labels} matrix={matrix} height={280} />
        </div>
      )}
    </div>
  );
}

// Embedded Settings Panel
function CockpitSettings() {
  const {
    llmSettings,
    dataSourceSettings,
    llmLoading,
    loadLLMSettings,
    updateLLMSettings,
    loadDataSourceSettings,
    updateDataSourceSettings,
  } = useSettingsStore();
  const [model, setModel] = useState("");
  const [temp, setTemp] = useState(0.0);
  const [tushare, setTushare] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadLLMSettings();
    loadDataSourceSettings();
  }, [loadLLMSettings, loadDataSourceSettings]);

  useEffect(() => {
    if (llmSettings) {
      setModel(llmSettings.model_name);
      setTemp(llmSettings.temperature);
    }
  }, [llmSettings]);

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    if (!llmSettings) return;
    setSaving(true);
    try {
      await updateLLMSettings({
        provider: llmSettings.provider,
        model_name: model,
        base_url: llmSettings.base_url,
        temperature: temp,
        timeout_seconds: llmSettings.timeout_seconds,
        max_retries: llmSettings.max_retries,
      });
      if (tushare.trim()) {
        await updateDataSourceSettings({
          tushare_token: tushare.trim(),
        });
      }
      toast.success("Settings updated successfully");
    } catch {
      toast.error("Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  if (!llmSettings) {
    return (
      <div className="flex h-24 items-center justify-center text-ttcc-text-secondary text-[11px]">
        Loading settings metadata...
      </div>
    );
  }

  return (
    <form onSubmit={handleSave} className="space-y-3 p-1 text-[11px]">
      <div className="text-[10px] uppercase font-bold text-ttcc-text-secondary tracking-wider">
        LLM Agent & Environment Credentials
      </div>

      <div className="grid gap-2 md:grid-cols-2">
        <div className="flex flex-col gap-1">
          <label className="font-semibold text-ttcc-text-secondary">Model</label>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="rounded border border-ttcc-border bg-ttcc-bg px-2.5 py-1 text-xs text-ttcc-text outline-none"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="font-semibold text-ttcc-text-secondary">Temperature</label>
          <input
            type="number"
            step="0.1"
            value={temp}
            onChange={(e) => setTemp(parseFloat(e.target.value))}
            className="rounded border border-ttcc-border bg-ttcc-bg px-2.5 py-1 text-xs text-ttcc-text outline-none"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="font-semibold text-ttcc-text-secondary">Tushare Token (Optional)</label>
          <input
            type="password"
            value={tushare}
            onChange={(e) => setTushare(e.target.value)}
            placeholder={dataSourceSettings?.tushare_token_configured ? "******** (configured)" : "unconfigured"}
            className="rounded border border-ttcc-border bg-ttcc-bg px-2.5 py-1 text-xs text-ttcc-text outline-none font-mono"
          />
        </div>

        <div className="flex items-end">
          <button
            type="submit"
            disabled={saving || llmLoading}
            className="h-7 w-24 rounded bg-ttcc-accent text-white font-bold hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-1"
          >
            {saving ? <Loader2 className="h-3 w-3" /> : <Save className="h-3.5 w-3.5" />}
            Save
          </button>
        </div>
      </div>
    </form>
  );
}

function teamBorderClass(teamId: string): string {
  if (teamId === "momentum") {
    return "border-blue-400/40";
  }
  if (teamId === "mean_reversion") {
    return "border-ttcc-yellow/40";
  }
  if (teamId === "volatility_breakout") {
    return "border-ttcc-red/40";
  }
  return "border-ttcc-green/40";
}

function formatPct(value: number): string {
  if (!Number.isFinite(value)) {
    return "--";
  }
  return `${(value * 100).toFixed(0)}%`;
}

function formatUsd(value: number): string {
  if (!Number.isFinite(value)) {
    return "$0.00";
  }
  return `$${value.toFixed(2)}`;
}

function formatSignedUsd(value: number): string {
  if (!Number.isFinite(value)) {
    return "$0.00";
  }
  return value >= 0 ? `+$${value.toFixed(2)}` : `-$${Math.abs(value).toFixed(2)}`;
}

function Loader2({ className }: { className?: string }) {
  return (
    <svg
      className={cn("animate-spin", className)}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}
