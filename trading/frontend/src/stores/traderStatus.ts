import { create } from "zustand";
import { toast } from "sonner";
import type { ClosedTrade, TraderStatusPayload } from "@/types/api";
import type { TickerEntry } from "@/components/terminal/Ticker";
import { api } from "@/lib/api";

// ============= Re-exports for backward compatibility =============
// TerminalLayout re-exports this from the store to keep historical imports
// (`@/components/layout/TerminalLayout`) working without a circular dep.
export function statusPayloadError(payload: { error?: unknown }): string | null {
  const message = typeof payload.error === "string" ? payload.error.trim() : "";
  return message || null;
}

const STATUS_REFRESH_MS = 5_000;
const TICKER_REFRESH_MS = 10_000;
const TICKER_SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT"];

let statusTimer: ReturnType<typeof setInterval> | null = null;
let tickerTimer: ReturnType<typeof setInterval> | null = null;
let ageTimer: ReturnType<typeof setInterval> | null = null;

const prevClosedRef = new Set<string>();
let seenTradesInitRef = false;

interface TraderStatusState {
  status: TraderStatusPayload | null;
  tickers: TickerEntry[];
  loading: boolean;
  error: string | null;
  refreshAgeMs: number;

  polling: boolean;
  startPolling: () => void;
  stopPolling: () => void;

  refresh: () => Promise<void>;

  setStatus: (status: TraderStatusPayload | null) => void;
  setTickers: (tickers: TickerEntry[]) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setRefreshAgeMs: (ms: number) => void;
}

export const useTraderStatusStore = create<TraderStatusState>((set, get) => ({
  status: null,
  tickers: [],
  loading: true,
  error: null,
  refreshAgeMs: 0,
  polling: false,

  setStatus: (status) => set({ status }),
  setTickers: (tickers) => set({ tickers }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  setRefreshAgeMs: (refreshAgeMs) => set({ refreshAgeMs }),

  refresh: async () => {
    try {
      const next = await api.getTraderStatus();
      const nextError = statusPayloadError(next);
      if (nextError) {
        set({ error: nextError, loading: false });
        return;
      }
      const newTrades: ClosedTrade[] = [];
      for (const tr of next.closed_trades ?? []) {
        const key = `${tr.closed_at}|${tr.symbol}|${tr.side}|${tr.pnl_usd}`;
        if (!prevClosedRef.has(key)) {
          if (seenTradesInitRef) newTrades.push(tr);
          prevClosedRef.add(key);
        }
      }
      if (prevClosedRef.size > 200) {
        const kept = Array.from(prevClosedRef).slice(-200);
        prevClosedRef.clear();
        for (const k of kept) prevClosedRef.add(k);
      }
      if (newTrades.length && seenTradesInitRef) {
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
      seenTradesInitRef = true;
      set({ status: next, error: null, loading: false, refreshAgeMs: 0 });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : "Trader status unavailable",
        loading: false,
      });
    }
  },

  startPolling: () => {
    if (get().polling) return;
    set({ polling: true });
    void get().refresh();
    void (async () => {
      try {
        const res = await api.getTraderTicker(TICKER_SYMBOLS);
        set({ tickers: res.tickers ?? [] });
      } catch {
        /* silent */
      }
    })();
    statusTimer = setInterval(() => { void get().refresh(); }, STATUS_REFRESH_MS);
    tickerTimer = setInterval(() => {
      void (async () => {
        try {
          const res = await api.getTraderTicker(TICKER_SYMBOLS);
          set({ tickers: res.tickers ?? [] });
        } catch {
          /* silent */
        }
      })();
    }, TICKER_REFRESH_MS);
    ageTimer = setInterval(() => {
      set({ refreshAgeMs: get().refreshAgeMs + 1000 });
    }, 1000);
  },

  stopPolling: () => {
    if (statusTimer) { clearInterval(statusTimer); statusTimer = null; }
    if (tickerTimer) { clearInterval(tickerTimer); tickerTimer = null; }
    if (ageTimer) { clearInterval(ageTimer); ageTimer = null; }
    set({ polling: false });
  },
}));
