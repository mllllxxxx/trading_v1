import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { useTraderStatusStore } from "../traderStatus";
import type { TraderStatusPayload } from "@/types/api";

const apiMock = vi.hoisted(() => ({
  getTraderStatus: vi.fn(),
  getTraderTicker: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMock }));

const toastMock = vi.hoisted(() => ({ toast: vi.fn() }));
vi.mock("sonner", () => ({ toast: toastMock.toast }));

const emptyPayload: TraderStatusPayload = {};

describe("useTraderStatusStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTraderStatusStore.setState({
      status: null,
      tickers: [],
      loading: true,
      error: null,
      refreshAgeMs: 0,
      polling: false,
    });
    useTraderStatusStore.getState().stopPolling();
  });

  afterEach(() => {
    useTraderStatusStore.getState().stopPolling();
  });

  // ── 1. initial state ──────────────────────────────────────────
  describe("initial state", () => {
    it("has correct defaults", () => {
      const s = useTraderStatusStore.getState();
      expect(s.status).toBeNull();
      expect(s.tickers).toEqual([]);
      expect(s.loading).toBe(true);
      expect(s.error).toBeNull();
      expect(s.polling).toBe(false);
    });
  });

  // ── 2. startPolling ────────────────────────────────────────────
  describe("startPolling", () => {
    it("sets polling=true and calls refresh (which calls api.getTraderStatus)", async () => {
      apiMock.getTraderStatus.mockResolvedValue(emptyPayload);
      apiMock.getTraderTicker.mockResolvedValue({ tickers: [] });

      useTraderStatusStore.getState().startPolling();

      expect(useTraderStatusStore.getState().polling).toBe(true);

      await vi.waitFor(() => {
        expect(apiMock.getTraderStatus).toHaveBeenCalledTimes(1);
        expect(apiMock.getTraderTicker).toHaveBeenCalledTimes(1);
      });
    });

    it("is idempotent — does not restart if already polling", async () => {
      apiMock.getTraderStatus.mockResolvedValue(emptyPayload);
      apiMock.getTraderTicker.mockResolvedValue({ tickers: [] });

      useTraderStatusStore.getState().startPolling();
      useTraderStatusStore.getState().startPolling();

      await vi.waitFor(() => {
        expect(apiMock.getTraderStatus).toHaveBeenCalledTimes(1);
      });
    });
  });

  // ── 3. stopPolling ─────────────────────────────────────────────
  describe("stopPolling", () => {
    it("sets polling=false and clears intervals", async () => {
      vi.useFakeTimers();
      try {
        apiMock.getTraderStatus.mockResolvedValue(emptyPayload);
        apiMock.getTraderTicker.mockResolvedValue({ tickers: [] });

        useTraderStatusStore.getState().startPolling();
        await vi.advanceTimersByTimeAsync(0); // flush fire-and-forget microtasks

        useTraderStatusStore.getState().stopPolling();
        expect(useTraderStatusStore.getState().polling).toBe(false);

        const callsBefore = apiMock.getTraderStatus.mock.calls.length;
        vi.advanceTimersByTime(15_000); // past all interval periods (5s/10s/1s)
        expect(apiMock.getTraderStatus.mock.calls.length).toBe(callsBefore);
      } finally {
        vi.useRealTimers();
      }
    });
  });

  // ── 4–6. refresh ──────────────────────────────────────────────
  describe("refresh", () => {
    it("success: sets status, loading=false, error=null", async () => {
      const payload: TraderStatusPayload = {
        running: true,
        symbols: ["BTC-USDT"],
      };
      apiMock.getTraderStatus.mockResolvedValue(payload);

      await useTraderStatusStore.getState().refresh();

      const s = useTraderStatusStore.getState();
      expect(s.status).toEqual(payload);
      expect(s.loading).toBe(false);
      expect(s.error).toBeNull();
    });

    it("error: sets error and loading=false when api throws", async () => {
      apiMock.getTraderStatus.mockRejectedValue(new Error("boom"));

      await useTraderStatusStore.getState().refresh();

      const s = useTraderStatusStore.getState();
      expect(s.error).toBe("boom");
      expect(s.loading).toBe(false);
    });

    it("error: uses default message for non-Error throws", async () => {
      apiMock.getTraderStatus.mockRejectedValue("oops");

      await useTraderStatusStore.getState().refresh();

      expect(useTraderStatusStore.getState().error).toBe(
        "Trader status unavailable",
      );
      expect(useTraderStatusStore.getState().loading).toBe(false);
    });

    // ── 6. statusPayloadError ───────────────────────────────────
    it("statusPayloadError: extracts trimmed error string from payload", async () => {
      apiMock.getTraderStatus.mockResolvedValue({ error: "  something broke  " });

      await useTraderStatusStore.getState().refresh();

      const s = useTraderStatusStore.getState();
      expect(s.error).toBe("something broke");
      expect(s.loading).toBe(false);
      expect(s.status).toBeNull();
    });

    it("statusPayloadError: whitespace-only error is treated as no error", async () => {
      const payload = { error: "   " };
      apiMock.getTraderStatus.mockResolvedValue(payload);

      await useTraderStatusStore.getState().refresh();

      const s = useTraderStatusStore.getState();
      expect(s.error).toBeNull();
      expect(s.status).toEqual(payload);
    });

    // ── 7. new closed trades → toast ─────────────────────────────
    it("new closed trades: fires toast for new trades on subsequent refresh", async () => {
      const baseTrade = {
        closed_at: "2024-01-01T00:00:00Z",
        symbol: "BTC-USDT",
        side: "long",
        entry: 100,
        exit_price: 110,
        position_size: 1,
        pnl_usd: 10,
        exit_reason: "tp",
        confluence_score: 0.8,
      };
      const newTrade = {
        closed_at: "2024-01-02T00:00:00Z",
        symbol: "ETH-USDT",
        side: "short",
        entry: 50,
        exit_price: 45,
        position_size: 2,
        pnl_usd: -5,
        exit_reason: "stop",
        confluence_score: 0.6,
      };

      // First refresh — seeds prevClosedRef + flips seenTradesInitRef to true
      apiMock.getTraderStatus.mockResolvedValue({ closed_trades: [baseTrade] });
      await useTraderStatusStore.getState().refresh();
      toastMock.toast.mockClear();

      // Second refresh — newTrade is new → toast fires
      apiMock.getTraderStatus.mockResolvedValue({
        closed_trades: [baseTrade, newTrade],
      });
      await useTraderStatusStore.getState().refresh();

      expect(toastMock.toast).toHaveBeenCalledTimes(1);
      expect(toastMock.toast).toHaveBeenCalledWith(
        expect.stringContaining("ETH"),
        expect.objectContaining({ description: "stop" }),
      );
    });

    it("does not re-fire toast for already-seen trades", async () => {
      const trade = {
        closed_at: "2024-03-03T00:00:00Z",
        symbol: "SOL-USDT",
        side: "long",
        entry: 20,
        exit_price: 25,
        position_size: 3,
        pnl_usd: 15,
        exit_reason: "tp",
        confluence_score: 0.9,
      };

      apiMock.getTraderStatus.mockResolvedValue({ closed_trades: [trade] });
      await useTraderStatusStore.getState().refresh();
      toastMock.toast.mockClear();

      await useTraderStatusStore.getState().refresh();
      expect(toastMock.toast).not.toHaveBeenCalled();
    });
  });

  // ── 8. ticker fetch ───────────────────────────────────────────
  describe("ticker fetch", () => {
    it("startPolling fetches tickers via api.getTraderTicker and updates state", async () => {
      const tickers = [
        { symbol: "BTC-USDT", price: 50000, change_24h_pct: 2.5 },
        { symbol: "ETH-USDT", price: 3000, change_24h_pct: -1.2 },
      ];
      apiMock.getTraderStatus.mockResolvedValue(emptyPayload);
      apiMock.getTraderTicker.mockResolvedValue({ tickers });

      useTraderStatusStore.getState().startPolling();
      await vi.waitFor(() => {
        expect(useTraderStatusStore.getState().tickers).toEqual(tickers);
      });
    });

    it("ticker fetch failure is silent — does not set error", async () => {
      apiMock.getTraderStatus.mockResolvedValue(emptyPayload);
      apiMock.getTraderTicker.mockRejectedValue(new Error("network down"));

      useTraderStatusStore.getState().startPolling();
      await vi.waitFor(() => {
        expect(apiMock.getTraderTicker).toHaveBeenCalled();
      });

      expect(useTraderStatusStore.getState().tickers).toEqual([]);
      expect(useTraderStatusStore.getState().error).toBeNull();
    });
  });
});
