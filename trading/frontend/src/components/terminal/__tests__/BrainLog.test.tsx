import { render, screen } from "@testing-library/react";
import { BrainLog } from "../BrainLog";

describe("BrainLog", () => {
  it("renders signal-pipeline LLM draft tickets as brain decisions", () => {
    render(
      <BrainLog
        decisions={[
          {
            ts: "2026-07-01T16:47:18+07:00",
            type: "llm_draft_ticket",
            symbol: "ETH-USDT",
            action: "OPEN_LONG",
            confidence: 0.82,
            playbook_id: "PB_CRYPTO_TREND_CONTINUATION_001",
            reasoning: "Berkshire signal and trend regime agree.",
          },
        ]}
      />,
    );

    expect(screen.getByText("OPEN_LONG")).toBeInTheDocument();
    expect(screen.getByText("82%")).toBeInTheDocument();
    expect(screen.getByText(/ETH-USDT/)).toBeInTheDocument();
    expect(screen.getByText(/PB_CRYPTO_TREND_CONTINUATION_001/)).toBeInTheDocument();
    expect(screen.getByText(/Berkshire signal and trend regime agree/)).toBeInTheDocument();
  });
});
