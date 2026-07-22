import { describe, expect, it } from "vitest";
import { deriveAccountMetrics, statusPayloadError } from "../TerminalLayout";

describe("statusPayloadError", () => {
  it("surfaces backend journal errors instead of treating them as healthy data", () => {
    expect(statusPayloadError({ error: " positions.json corrupt " })).toBe(
      "positions.json corrupt"
    );
    expect(statusPayloadError({})).toBeNull();
  });
});

describe("deriveAccountMetrics", () => {
  it("prefers exchange account state for displayed capital and PnL", () => {
    const metrics = deriveAccountMetrics(
      {
        starting_capital: 10_000,
        current_capital: 10_059,
        total_pnl_usd: 59,
      },
      {
        source: "okx_demo",
        mode: "demo",
        synced_at: "2026-07-01T00:00:00Z",
        starting_capital_usd: 10_000,
        current_capital_usd: 10_023.45,
        total_pnl_usd: 23.45,
        unrealized_pnl_usd: -7.86,
        available_balance_usd: 9_980.12,
        margin_used_usd: 43.33,
        errors: [],
      }
    );

    expect(metrics.currentCapital).toBe(10_023.45);
    expect(metrics.totalPnl).toBe(23.45);
    expect(metrics.sourceLabel).toBe("exchange synced");
    expect(metrics.availableBalance).toBe(9_980.12);
    expect(metrics.marginUsed).toBe(43.33);
  });

  it("falls back to journal stats when account state is journal fallback", () => {
    const metrics = deriveAccountMetrics(
      {
        starting_capital: 10_000,
        current_capital: 10_059,
        total_pnl_usd: 59,
      },
      {
        source: "journal_fallback",
        current_capital_usd: 9_000,
        total_pnl_usd: -1_000,
        errors: ["balance unavailable"],
      }
    );

    expect(metrics.currentCapital).toBe(10_059);
    expect(metrics.totalPnl).toBe(59);
    expect(metrics.sourceLabel).toBe("journal fallback");
    expect(metrics.errors).toEqual(["balance unavailable"]);
  });

  it("labels capped OKX demo equity without falling back to journal stats", () => {
    const metrics = deriveAccountMetrics(
      {
        starting_capital: 10_000,
        current_capital: 10_059,
        total_pnl_usd: 59,
      },
      {
        source: "okx_demo_capped",
        risk_profile: "demo_small_200",
        simulation_equity_cap_usd: 200,
        starting_capital_usd: 200,
        current_capital_usd: 223.45,
        total_pnl_usd: 23.45,
        unrealized_pnl_usd: -7.86,
        journal_realized_pnl_usd: 31.31,
        available_balance_usd: 223.45,
        actual_current_capital_usd: 10_023.45,
        errors: ["equity_cap_active"],
      }
    );

    expect(metrics.currentCapital).toBe(223.45);
    expect(metrics.totalPnl).toBe(23.45);
    expect(metrics.startingCapital).toBe(200);
    expect(metrics.sourceLabel).toBe("exchange capped");
    expect(metrics.errors).toEqual(["equity_cap_active"]);
  });
});
