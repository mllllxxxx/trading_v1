import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  AdaptivePolicyBadge,
  ClosedTradesTable,
  canonicalPositionSymbol,
  mergePositionFeeds,
} from "../Trader";
import type { Position } from "@/components/terminal/PositionCard";

function makePosition(overrides: Partial<Position> = {}): Position {
  return {
    symbol: "BTC-USDT",
    side: "buy",
    entry: 100,
    stop_loss: 95,
    take_profit: 110,
    position_size: 0.2,
    rr_ratio: 2,
    confluence_score: 6,
    regime: "TRENDING_UP",
    opened_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

describe("trader position feed merge", () => {
  it("normalizes OKX and CCXT swap symbols", () => {
    expect(canonicalPositionSymbol("BTC-USDT-SWAP")).toBe("BTC-USDT");
    expect(canonicalPositionSymbol("BTC/USDT:USDT")).toBe("BTC-USDT");
  });

  it("falls back to exchange positions when the journal feed is empty", () => {
    const merged = mergePositionFeeds([], [
      makePosition({
        symbol: "BTC/USDT:USDT",
        source: "exchange_reconciler",
        status: "exchange_open",
        mark_price: 102,
      }),
    ]);

    expect(merged).toHaveLength(1);
    expect(merged[0].symbol).toBe("BTC-USDT");
    expect(merged[0].source).toBe("exchange_reconciler");
    expect(merged[0].mark_price).toBe(102);
  });

  it("prefers journal rationale while preserving exchange sync metadata", () => {
    const merged = mergePositionFeeds(
      [
        makePosition({
          symbol: "BTC-USDT",
          open_reason: "LLM approved trend continuation.",
        }),
      ],
      [
        makePosition({
          symbol: "BTC-USDT-SWAP",
          source: "exchange_reconciler",
          status: "exchange_open",
          mark_price: 102,
          protective_orders: [{ algoId: "oco-1" }],
        }),
      ]
    );

    expect(merged).toHaveLength(1);
    expect(merged[0].open_reason).toBe("LLM approved trend continuation.");
    expect(merged[0].status).toBe("exchange_open");
    expect(merged[0].mark_price).toBe(102);
    expect(merged[0].protective_orders?.[0]?.algoId).toBe("oco-1");
  });
});

describe("trader closed trade numbering", () => {
  it("numbers closed trades using the provided page offset", () => {
    render(
      <ClosedTradesTable
        startIndex={20}
        totalTrades={22}
        trades={[
          {
            closed_at: "2026-07-01T00:00:00Z",
            symbol: "BTC-USDT",
            side: "buy",
            entry: 100,
            exit_price: 110,
            position_size: 0.2,
            pnl_usd: 2,
            exit_reason: "tp",
            confluence_score: 6,
          },
          {
            closed_at: "2026-07-01T01:00:00Z",
            symbol: "ETH-USDT",
            side: "sell",
            entry: 100,
            exit_price: 95,
            position_size: 0.3,
            pnl_usd: 1.5,
            exit_reason: "tp",
            confluence_score: 5,
          },
        ]}
      />
    );

    expect(screen.getByText("#21")).toBeInTheDocument();
    expect(screen.getByText("#22")).toBeInTheDocument();
  });
});

describe("adaptive policy status badge", () => {
  it("shows effective zones and revision without another data surface", () => {
    render(
      <AdaptivePolicyBadge
        controller={{
          status: "active",
          revision: 2,
          active_zones: {
            strong_min_score: 75,
            gray_min_score: 55,
          },
          effective_source: "runtime_override",
          last_action: "activated",
        }}
        experiment={{
          mode: "shadow_only",
          active_for_routing: false,
          eligible_records: 20,
          score_coverage: { valid: 12, total: 20, ratio: 0.6 },
          score_delta_v2_minus_v1: { average: -1.25 },
          zone_transitions: { "gray->strong": 2 },
          threshold_calibration: {
            status: "candidate_ready",
            candidate_thresholds: {
              strong_min_score: 75,
              gray_min_score: 60,
              active_for_routing: false,
            },
            objective_comparison_vs_active_v1: {
              validation_delta_v2_minus_v1: 0.42,
            },
          },
          review_eligibility: {
            status: "collecting_evidence",
            eligible: false,
            blocking_reasons: ["valid_score_sample"],
          },
          auto_apply: false,
        }}
        reviewController={{
          status: "staged",
          revision: 1,
          candidate: {
            strong_min_score: 75,
            gray_min_score: 60,
            confirmations: 1,
            required_confirmations: 2,
          },
          operator_approved: false,
          active_for_routing: false,
          canary_enabled: false,
        }}
        canary={{
          status: "active",
          routing_enabled: true,
          approval_id: "approval-123456789",
          candidate_fingerprint: "candidate-123456789",
          candidate_thresholds: {
            strong_min_score: 76,
            gray_min_score: 54,
          },
          allocation_rate: 0.2,
          risk_multiplier: 0.5,
          last_reason: "approval_and_review_candidate_valid",
          rollback_metrics: {
            closed_trades: 4,
            average_r_lower_bound: 0.12,
            profit_factor: 1.3,
            cumulative_r: 1.1,
          },
        }}
      />
    );

    expect(screen.getByText("ADP 75/55 R2")).toBeInTheDocument();
    expect(screen.getByText("V2 12/20")).toBeInTheDocument();
    expect(screen.getByText("V2 CANARY")).toBeInTheDocument();
    expect(
      screen.getByLabelText(
        "Adaptive policy strong 75, gray 55, revision 2, V2 coverage 12 of 20"
      )
    )
      .toHaveAttribute("title", expect.stringContaining("runtime_override"));
    expect(
      screen.getByLabelText(
        "Adaptive policy strong 75, gray 55, revision 2, V2 coverage 12 of 20"
      )
    ).toHaveAttribute("title", expect.stringContaining("V2 score delta -1.25"));
    expect(
      screen.getByLabelText(
        "Adaptive policy strong 75, gray 55, revision 2, V2 coverage 12 of 20"
      )
    ).toHaveAttribute("title", expect.stringContaining("V2 readiness collecting_evidence"));
    expect(
      screen.getByLabelText(
        "Adaptive policy strong 75, gray 55, revision 2, V2 coverage 12 of 20"
      )
    ).toHaveAttribute("title", expect.stringContaining("V2 candidate 75/60"));
    expect(
      screen.getByLabelText(
        "Adaptive policy strong 75, gray 55, revision 2, V2 coverage 12 of 20"
      )
    ).toHaveAttribute("title", expect.stringContaining("V2 holdout objective delta 0.42"));
    expect(
      screen.getByLabelText(
        "Adaptive policy strong 75, gray 55, revision 2, V2 coverage 12 of 20"
      )
    ).toHaveAttribute("title", expect.stringContaining("V2 review confirmations 1/2"));
    expect(
      screen.getByLabelText(
        "Adaptive policy strong 75, gray 55, revision 2, V2 coverage 12 of 20"
      )
    ).toHaveAttribute("title", expect.stringContaining("V2 active for routing false"));
    expect(
      screen.getByLabelText(
        "Adaptive policy strong 75, gray 55, revision 2, V2 coverage 12 of 20"
      )
    ).toHaveAttribute("title", expect.stringContaining("V2 canary allocation 20%, risk x0.5"));
    expect(
      screen.getByLabelText(
        "Adaptive policy strong 75, gray 55, revision 2, V2 coverage 12 of 20"
      )
    ).toHaveAttribute("title", expect.stringContaining("V2 canary zones 76/54"));
  });
});
