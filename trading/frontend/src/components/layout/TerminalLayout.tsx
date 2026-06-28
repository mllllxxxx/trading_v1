import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Outlet, useLocation, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { BrainCircuit, ChevronRight, LayoutGrid, X } from "lucide-react";
import { useDarkMode } from "@/hooks/useDarkMode";
import { useAgentStore } from "@/stores/agent";
import { cn } from "@/components/terminal/primitives";
import { TopBar } from "@/components/terminal/TopBar";
import { LeftPanel } from "@/components/terminal/LeftPanel";
import { RightPanel } from "@/components/terminal/RightPanel";
import { BottomBar } from "@/components/terminal/BottomBar";
import { ConnectionBanner } from "@/components/layout/ConnectionBanner";
import type { TickerEntry } from "@/components/terminal/Ticker";
import type { BrainDecision } from "@/components/terminal/BrainLog";
import type { MiniTrade } from "@/components/terminal/MiniHistory";

// ============= Types (mirrors backend /api/trader/status) =============

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
  daily_llm_cost?: {
    date: string;
    cost_usd: number;
    calls: number;
    cap_usd: number;
    remaining_usd: number;
    pct_of_cap: number;
    cap_reached: boolean;
    monthly_cost_usd: number;
    monthly_date: string;
  };
};

type StatusPayload = {
  timestamp?: string;
  running?: boolean;
  started_at?: string | null;
  symbols?: string[];
  stats?: Stats;
  positions?: unknown[];
  closed_trades?: MiniTrade[];
  decisions?: BrainDecision[];
  llm_decisions?: BrainDecision[];
  kill_switch_active?: boolean;
};

const STATUS_REFRESH_MS = 5_000;
const TICKER_REFRESH_MS = 10_000;
const TICKER_SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT"];
const SCAN_INTERVAL_S = 600; // default; backend reports its own cycle
const MAX_POSITIONS = 3;

// ============= Minimal fetch helper =============

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    method: init?.method ?? "GET",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

// ============= MiniNav — compact nav strip for non-trader routes =============

type NavItem = { to: string; label: string; icon: React.ComponentType<{ className?: string }>; accent?: boolean };

function MiniNav({ pathname, onClose }: { pathname: string; onClose: () => void }) {
  const items: NavItem[] = [
    { to: "/", label: "Home", icon: LayoutGrid },
    { to: "/agent", label: "Agent", icon: LayoutGrid },
    { to: "/trader", label: "Trader", icon: LayoutGrid, accent: true },
    { to: "/runtime", label: "Runtime", icon: LayoutGrid },
    { to: "/berkshire", label: "Berkshire", icon: BrainCircuit, accent: true },
    { to: "/alpha-zoo", label: "Alpha Zoo", icon: LayoutGrid },
    { to: "/correlation", label: "Correlation", icon: LayoutGrid },
    { to: "/settings", label: "Settings", icon: LayoutGrid },
    { to: "/trader/history", label: "Journal", icon: LayoutGrid },
  ];
  return (
    <div className="absolute inset-0 z-40 flex bg-black/40" onClick={onClose}>
      <nav
        className="flex w-64 flex-col gap-1 border-r border-ttcc-border bg-ttcc-surface p-3 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ttcc-text-secondary">
            Navigation
          </span>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-ttcc-text-secondary hover:bg-ttcc-surface-2 hover:text-ttcc-text"
            title="Close"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
        {items.map((it) => {
          const Icon = it.icon;
          const active = it.to === "/" ? pathname === "/" : pathname.startsWith(it.to);
          return (
            <a
              key={it.to}
              href={it.to}
              className={cn(
                "flex items-center gap-2 rounded border px-2.5 py-1.5 text-[12px] font-medium transition-colors",
                active
                  ? "border-ttcc-accent/50 bg-ttcc-accent/15 text-ttcc-accent"
                  : "border-ttcc-border bg-ttcc-surface-2 text-ttcc-text-secondary hover:text-ttcc-text",
                it.accent && !active && "ring-1 ring-ttcc-accent/20"
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              <span>{it.label}</span>
              {it.accent ? (
                <span className="ml-auto rounded border border-ttcc-accent/40 bg-ttcc-accent/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-ttcc-accent">
                  here
                </span>
              ) : null}
            </a>
          );
        })}
      </nav>
    </div>
  );
}

// ============= TerminalLayout =============

export function TerminalLayout() {
  const { dark, toggle } = useDarkMode();
  const { pathname } = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const sseStatus = useAgentStore((s) => s.sseStatus);
  const sseRetryAttempt = useAgentStore((s) => s.sseRetryAttempt);

  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [tickers, setTickers] = useState<TickerEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshAgeMs, setRefreshAgeMs] = useState(0);
  const [confirmKill, setConfirmKill] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [showSide, setShowSide] = useState(true);
  const prevClosedRef = useRef<Set<string>>(new Set());
  const seenTradesInitRef = useRef(false);

  const isTraderRoute = pathname === "/" || pathname === "/trader" || pathname.startsWith("/trader/");

  const loadStatus = useCallback(async () => {
    try {
      const next = await request<StatusPayload>("/api/trader/status");
      setStatus((_prev) => {
        const newTrades: MiniTrade[] = [];
        for (const tr of next.closed_trades ?? []) {
          const key = `${tr.closed_at}|${tr.symbol}|${tr.side}|${tr.pnl_usd}`;
          if (!prevClosedRef.current.has(key)) {
            if (seenTradesInitRef.current) newTrades.push(tr);
            prevClosedRef.current.add(key);
          }
        }
        if (prevClosedRef.current.size > 200) {
          prevClosedRef.current = new Set(
            Array.from(prevClosedRef.current).slice(-200)
          );
        }
        if (newTrades.length && seenTradesInitRef.current) {
          for (const tr of newTrades.slice(0, 3)) {
            const win = tr.pnl_usd >= 0;
            toast(
              `${tr.symbol.replace("-USDT", "")} ${tr.side.toUpperCase()} ${win ? "✓" : "✗"} ${tr.pnl_usd >= 0 ? "+" : ""}${tr.pnl_usd.toFixed(2)}`,
              {
                description: `${tr.exit_reason || "exit"}`,
                className: win ? "border-ttcc-green/40" : "border-ttcc-red/40",
              }
            );
          }
        }
        seenTradesInitRef.current = true;
        return next;
      });
      setRefreshAgeMs(0);
      setLoading(false);
    } catch {
      /* silent — keep last state */
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
    const ageTimer = window.setInterval(() => setRefreshAgeMs((x) => x + 1000), 1000);
    return () => {
      window.clearInterval(sTimer);
      window.clearInterval(tTimer);
      window.clearInterval(ageTimer);
    };
  }, [loadStatus, loadTicker]);

  // Drop the auto-injected ?ts=… query param that some navigation paths add.
  useEffect(() => {
    if (searchParams.has("ts")) {
      const next = new URLSearchParams(searchParams);
      next.delete("ts");
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  // ============= Derived metrics =============

  const stats = status?.stats ?? {};
  const totalPnl = stats.total_pnl_usd ?? 0;
  const currentCapital = stats.current_capital ?? 10000;
  const startingCapital = stats.starting_capital ?? 10000;
  const openPositions = stats.open_count ?? (status?.positions?.length ?? 0);
  const winrate = stats.winrate ?? 0;
  const wins = stats.wins ?? 0;
  const losses = stats.losses ?? 0;
  const totalTrades = stats.total_trades ?? 0;
  const consecutiveLosses = stats.consecutive_losses ?? 0;
  const symbols = status?.symbols ?? TICKER_SYMBOLS;
  const running = !!status?.running;
  const killActive = !!status?.kill_switch_active;
  const lastTs = status?.timestamp ?? null;

  const recentClosed = (status?.closed_trades ?? []).slice(0, 3);

  const llmDecisions = useMemo(() => {
    return (status?.llm_decisions ?? []).slice(-30).reverse();
  }, [status?.llm_decisions]);

  const modelName = useMemo(() => {
    const last = (status?.llm_decisions ?? []).slice(-1)[0] as Record<string, unknown> | undefined;
    return String(last?.model ?? "deepseek-v4-flash");
  }, [status?.llm_decisions]);

  const avgLatency = useMemo(() => {
    const recent = (status?.llm_decisions ?? []).slice(-10);
    if (!recent.length) return "—";
    const total = recent.reduce(
      (s: number, d: any) => s + (Number(d?.latency_s) || 0),
      0
    );
    return (total / recent.length).toFixed(1) + "s";
  }, [status?.llm_decisions]);

  const recentDecisionCount = useMemo(() => {
    const today = new Date().toISOString().substring(0, 10);
    return (status?.llm_decisions ?? []).filter((d: any) =>
      String(d?.ts || "").startsWith(today)
    ).length;
  }, [status?.llm_decisions]);

  const handleKillConfirm = () => {
    setConfirmKill(false);
    if (killActive) {
      request("/api/trader/resume", { method: "POST" }).catch(() => undefined);
      toast.success("Kill switch disarmed", { description: "Trading resumed" });
    } else {
      request("/api/trader/kill", { method: "POST" }).catch(() => undefined);
      toast.warning("Kill switch armed", {
        description: "All new entries blocked",
        className: "border-ttcc-red/50",
      });
    }
  };

  return (
    <div className={cn(
      "ttcc-root flex h-screen flex-col bg-ttcc-bg text-ttcc-text antialiased",
      !dark && "ring-1 ring-inset ring-ttcc-border/30"
    )}>
      <ConnectionBanner status={sseStatus} retryAttempt={sseRetryAttempt} />

      <TopBar
        tickers={tickers}
        symbols={TICKER_SYMBOLS}
        refreshAgeMs={refreshAgeMs}
        running={running}
        killActive={killActive}
        modelName={modelName}
        capitalUsd={currentCapital}
        pnlTodayUsd={totalPnl}
        onKillToggle={() => setConfirmKill(true)}
      />

      <div className="relative flex flex-1 min-h-0 overflow-hidden">
        {/* Nav button + side panels — LeftPanel collapses to icon strip
            when `showSide=false` or when not on a trader route. */}
        {isTraderRoute ? (
          showSide ? (
            <LeftPanel
              totalPnl={totalPnl}
              currentCapital={currentCapital}
              startingCapital={startingCapital}
              winrate={winrate}
              wins={wins}
              losses={losses}
              totalTrades={totalTrades}
              consecutiveLosses={consecutiveLosses}
              openPositions={openPositions}
              maxPositions={MAX_POSITIONS}
              symbols={symbols}
              modelName={modelName}
              avgLatency={avgLatency}
              recentDecisionCount={recentDecisionCount}
              lastUpdate={status?.timestamp ?? null}
              running={running}
              killActive={killActive}
              cost={stats.daily_llm_cost ?? null}
              onKillToggle={() => setConfirmKill(true)}
            />
          ) : (
            <aside className="flex w-9 shrink-0 flex-col items-center gap-2 border-r border-ttcc-border bg-ttcc-bg py-2">
              <button
                type="button"
                onClick={() => setShowSide(true)}
                className="flex h-7 w-7 items-center justify-center rounded border border-ttcc-border bg-ttcc-surface text-ttcc-text-secondary hover:text-ttcc-text transition-colors"
                title="Show metrics panel"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
              <span className="font-mono text-[9px] uppercase tracking-wider text-ttcc-text-muted [writing-mode:vertical-rl] rotate-180">
                pnl · cap · kill
              </span>
            </aside>
          )
        ) : null}

        {/* Center = route content */}
        <main className="flex-1 min-w-0 overflow-y-auto bg-ttcc-bg relative">
          <Outlet />

          {loading && !status ? (
            <div className="flex h-full items-center justify-center text-[11px] text-ttcc-text-secondary">
              <div className="flex items-center gap-2">
                <span className="tt-live-dot" />
                loading terminal data…
              </div>
            </div>
          ) : null}
        </main>

        {isTraderRoute ? (
          <RightPanel decisions={llmDecisions} />
        ) : null}

        {/* Mini-nav overlay (any route). */}
        {navOpen ? <MiniNav pathname={pathname} onClose={() => setNavOpen(false)} /> : null}
      </div>

      <BottomBar
        onOpenNav={() => setNavOpen(true)}
        recentTrades={recentClosed}
        lastTs={lastTs}
        scanIntervalS={SCAN_INTERVAL_S}
        running={running}
        refreshAgeMs={refreshAgeMs}
      />

      {/* Theme toggle is hidden in the bottom-right corner for now. */}
      <button
        type="button"
        onClick={toggle}
        className="absolute bottom-10 right-2 z-30 rounded border border-ttcc-border bg-ttcc-surface px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-ttcc-text-secondary opacity-40 hover:opacity-100 transition-opacity"
        title={dark ? "Switch to light theme" : "Switch to dark theme"}
      >
        {dark ? "dark" : "light"}
      </button>

      <ConfirmKillDialog
        open={confirmKill}
        active={killActive}
        onConfirm={handleKillConfirm}
        onCancel={() => setConfirmKill(false)}
      />
    </div>
  );
}

// Inline minimal confirm dialog — local copy so the layout has no extra deps.
function ConfirmKillDialog({
  open,
  active,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  active: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter") onConfirm();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onConfirm, onCancel]);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="w-[360px] max-w-[92vw] rounded-md border border-ttcc-border bg-ttcc-surface p-4 shadow-2xl tt-toast-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 text-sm font-semibold text-ttcc-text">
          <span className={cn(
            "flex h-6 w-6 items-center justify-center rounded",
            active ? "bg-ttcc-red/15 text-ttcc-red" : "bg-ttcc-green/15 text-ttcc-green"
          )}>!</span>
          {active ? "Disarm kill switch?" : "Arm kill switch?"}
        </div>
        <div className="mt-2 text-xs text-ttcc-text-secondary">
          {active
            ? "Trading will resume. New entries will be permitted on the next cycle."
            : "All new entries will be blocked. Open positions remain until SL/TP hits or manual close."}
        </div>
        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded border border-ttcc-border bg-ttcc-surface-2 px-2.5 py-1 text-xs text-ttcc-text-secondary hover:text-ttcc-text transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={cn(
              "rounded border px-2.5 py-1 text-xs font-semibold transition-colors",
              active
                ? "border-ttcc-green/60 bg-ttcc-green/15 text-ttcc-green hover:bg-ttcc-green/25"
                : "border-ttcc-red/60 bg-ttcc-red/15 text-ttcc-red hover:bg-ttcc-red/25"
            )}
          >
            {active ? "Disarm" : "Arm"}
          </button>
        </div>
      </div>
    </div>
  );
}
