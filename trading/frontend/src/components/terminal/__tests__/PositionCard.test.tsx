import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PositionCard, type Position } from "../PositionCard";

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
    opened_at: "2026-06-30T10:00:00Z",
    ...overrides,
  };
}

describe("PositionCard", () => {
  it("keeps rationale in details until the operator opens it", async () => {
    const user = userEvent.setup();
    render(
      <PositionCard
        mark={102}
        p={makePosition({
          source_signal_id: "sig-demo-001",
          decision_id: "sigexec_sig-demo-001",
          open_reason: "Opened because Berkshire trend setup aligned with LLM thesis.",
          market_context: {
            candidate_direction: "long",
            data_quality: "fresh",
            data_source: "okx",
            data_age_s: 45,
            spread_state: "normal",
            funding_state: "neutral",
          },
          decision_context: {
            thesis: "Trend continuation remains valid above invalidation.",
            confidence: 0.82,
            playbook_id: "PB_CRYPTO_TREND_CONTINUATION_001",
            rule_citations: ["HARD_DATA_001"],
          },
          routing_experiment: {
            experiment_id: "continuous_conflict_v2",
            approval_id: "approval-123456789",
            candidate_fingerprint: "candidate-123456789",
            v1_score: 48,
            v1_zone: "reject",
            v2_score: 80,
            v2_zone: "strong",
            allocation_bucket: 0.12,
            allocation_rate: 0.2,
            risk_multiplier: 0.5,
          },
        })}
      />
    );

    expect(screen.queryByText("Open rationale")).not.toBeInTheDocument();
    expect(screen.getByRole("meter", { name: /confidence 82 of 100/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /details/i }));

    expect(screen.getByText("Open rationale")).toBeInTheDocument();
    expect(screen.getByText(/Berkshire trend setup/)).toBeInTheDocument();
    expect(screen.getByText(/Trend continuation remains valid/)).toBeInTheDocument();
    expect(screen.getByText("fresh")).toBeInTheDocument();
    expect(screen.getByText("okx")).toBeInTheDocument();
    expect(screen.getByText("45s")).toBeInTheDocument();
    expect(screen.getByText("82/100")).toBeInTheDocument();
    expect(screen.getByText("PB_CRYPTO_TREND_CONTINUATION_001")).toBeInTheDocument();
    expect(screen.getByText("HARD_DATA_001")).toBeInTheDocument();
    expect(screen.getByText("V2 canary")).toBeInTheDocument();
    expect(screen.getByText("reject 48")).toBeInTheDocument();
    expect(screen.getByText("strong 80")).toBeInTheDocument();
    expect(screen.getByText("x0.5")).toBeInTheDocument();
  });

  it("combines pnl and profit while showing timeframe once", () => {
    render(
      <PositionCard
        mark={102}
        p={makePosition({
          timeframe: "15m",
          market_context: { timeframe: "5m" },
        })}
      />
    );

    expect(screen.getByText("P&L")).toBeInTheDocument();
    expect(screen.getByText("+$0.40")).toBeInTheDocument();
    expect(screen.getByText("+2.00%")).toBeInTheDocument();
    expect(screen.queryByText("Profit")).not.toBeInTheDocument();
    expect(screen.queryByText("TF")).not.toBeInTheDocument();
    expect(screen.getAllByText("15m")).toHaveLength(1);
  });

  it("shows a compact sequence badge when provided", () => {
    render(
      <PositionCard
        mark={102}
        p={makePosition()}
        sequenceNumber={2}
        sequenceTotal={8}
      />
    );

    expect(screen.getByText("#2/8")).toBeInTheDocument();
  });

  it("shows team metadata on tagged positions", async () => {
    const user = userEvent.setup();
    render(
      <PositionCard
        mark={102}
        p={makePosition({
          team_id: "momentum",
          team_name: "Momentum",
          strategy_name: "Momentum Breakout",
          team_capital_usd: 200,
          target_risk_pct_equity: 0.04,
          preferred_playbook_ids: ["PB_CRYPTO_TREND_CONTINUATION_001"],
          entry_style: "Wait for pullback or retest after impulse.",
          avoid_conditions: ["late impulse chase"],
          profile_compliance_score: 0.74,
        })}
      />
    );

    expect(screen.getAllByText("Momentum")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: /details/i }));

    expect(screen.getByText("Momentum Breakout")).toBeInTheDocument();
    expect(screen.getByText("PB_CRYPTO_TREND_CONTINUATION_001")).toBeInTheDocument();
    expect(screen.getByText("Wait for pullback or retest after impulse.")).toBeInTheDocument();
    expect(screen.getByText("$200.00")).toBeInTheDocument();
    expect(screen.getByText("4.0%")).toBeInTheDocument();
    expect(screen.getByText("0.74")).toBeInTheDocument();
  });

  it("falls back to confluence for the confidence meter on a 100 point scale", () => {
    render(
      <PositionCard
        mark={101}
        p={makePosition({
          confluence_score: 4,
        })}
      />
    );

    expect(screen.getByRole("meter", { name: /confidence 50 of 100/i })).toHaveTextContent("50/100");
  });

  it("omits the rationale section for legacy positions", () => {
    render(<PositionCard mark={101} p={makePosition()} />);

    expect(screen.queryByText("Open rationale")).not.toBeInTheDocument();
  });

  it("renders exchange sync and order metadata inside details", async () => {
    const user = userEvent.setup();
    render(
      <PositionCard
        mark={null}
        p={makePosition({
          source: "exchange_reconciler",
          status: "exchange_open",
          sync_status: "exchange_reconciled",
          mode: "okx_demo",
          instId: "BTC-USDT-SWAP",
          ccxt_symbol: "BTC/USDT:USDT",
          mark_price: 102,
          unrealized_pnl: 3.5,
          leverage: 10,
          margin_mode: "isolated",
          contracts: 3,
          broker_sync_at: "2026-07-01T00:00:00Z",
          orders: { source: "exchange_reconciler", protective_order_count: 1 },
          protective_orders: [
            {
              algoId: "oco-1",
              ordType: "oco",
              state: "live",
              tpTriggerPx: "110",
              slTriggerPx: "95",
            },
          ],
        })}
      />
    );

    expect(screen.getAllByText("+$3.50").length).toBeGreaterThan(0);
    expect(screen.queryByText("Exchange sync")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /details/i }));

    expect(screen.getByText("Exchange sync")).toBeInTheDocument();
    expect(screen.getAllByText("exchange_open").length).toBeGreaterThan(0);
    expect(screen.getAllByText("exchange_reconciler").length).toBeGreaterThan(0);
    expect(screen.getByText("BTC-USDT-SWAP")).toBeInTheDocument();
    expect(screen.getByText("+3.5")).toBeInTheDocument();
    expect(screen.getAllByText("10x").length).toBeGreaterThan(0);
    expect(screen.getByText("isolated")).toBeInTheDocument();
    expect(screen.getByText("oco-1")).toBeInTheDocument();
  });
});
