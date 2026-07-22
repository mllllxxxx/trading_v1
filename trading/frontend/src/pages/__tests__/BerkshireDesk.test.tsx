import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BerkshireDesk } from "../BerkshireDesk";
import type { BerkshireCryptoScan, BerkshireResearchRun, BerkshireState } from "@/lib/api";

const apiMock = vi.hoisted(() => ({
  getBerkshireState: vi.fn(),
  createBerkshireResearch: vi.fn(),
  createBerkshireCryptoScan: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: apiMock,
  };
});

function makeRun(overrides: Partial<BerkshireResearchRun> = {}): BerkshireResearchRun {
  return {
    id: "brk_test",
    created_at: "2026-06-27T03:20:00Z",
    lane: "crypto",
    symbol: "BTC-USDT",
    skill: "investment-team",
    status: "complete",
    mode: "research_only",
    verdict: "pass_research",
    info_grade: "A",
    conviction: 76,
    summary: "BTC-USDT completed investment-team run with pass_research.",
    catalyst: "ETF inflow acceleration.",
    thesis: "BTC trend remains supported with clear invalidation.",
    analysts: [
      {
        key: "business_model",
        name: "Duan Yongping lens",
        focus: "Business quality",
        question: "Does the thesis describe a durable edge?",
        score: 4.1,
        stance: "support",
        finding: "Researchable setup.",
        concern: "Needs live evidence refresh.",
      },
    ],
    checklist: [
      { label: "Forex readiness", status: "pass", tone: "success", detail: "Crypto lane can feed advisory context" },
    ],
    financial_checks: {
      status: "ok",
      tone: "success",
      summary: "long setup, R/R 2.6667, risk 4.62%",
      risk_reward: "2.6667",
      risk_pct: "4.62",
      items: [{ label: "risk_reward", value: "2.6667", tone: "success" }],
    },
    audit: [{ time: "03:20", label: "Execution guard", value: "research_only, no order payload generated", tone: "success" }],
    report_markdown: "# Berkshire Research: BTC-USDT",
    ...overrides,
  };
}

function makeScan(overrides: Partial<BerkshireCryptoScan> = {}): BerkshireCryptoScan {
  return {
    id: "bscan_test",
    created_at: "2026-06-27T03:22:00Z",
    market: "crypto",
    mode: "signal_only",
    source: "okx_public_tickers",
    provider_error: null,
    universe_count: 2,
    signal_count: 1,
    top_symbol: "BTC-USDT",
    top_signal: "strong_candidate",
    signals: [
      {
        signal_id: "sig_test",
        generated_at: "2026-06-27T03:22:00Z",
        source: "berkshire_crypto_scanner",
        symbol: "BTC-USDT",
        market: "crypto",
        timeframe: "24h_ticker",
        direction: "long",
        status: "strong_candidate",
        signal: "strong_candidate",
        score: 88,
        grade: "A",
        confidence: 0.88,
        action_hint: "OPEN_LONG",
        mode: "signal_only",
        time_horizon: "swing_2d_7d",
        promotion_gate: "eligible_for_draft_ticket",
        last_price: "105.0000",
        change_pct_24h: "5.00",
        range_pct_24h: "8.57",
        volume_usd_24h: "2000000000.0000",
        spread_bps: "1.90",
        entry_zone: "104.7375 - 105.2625",
        invalidation: "102.4286",
        target_zone: "110.1428",
        risk_reward: "2.0000",
        reasons: ["24h momentum points long at 5.00%."],
        why: ["24h momentum points long at 5.00%."],
        blockers: [],
        llm_context: {
          role: "advisory_signal_context",
          candidate_action: "OPEN_LONG",
          ticket_gate: "eligible_for_draft_ticket",
          instruction: "Use this Berkshire signal as advisory evidence only.",
          prompt_context: "BTC-USDT advisory context",
        },
        evidence: {
          provider_source: "okx_public_tickers",
          last_price: "105.0000",
          change_pct_24h: "5.00",
          range_pct_24h: "8.57",
          volume_usd_24h: "2000000000.0000",
          spread_bps: "1.90",
        },
      },
    ],
    audit: [{ time: "03:22", label: "Crypto scan guard", value: "signal_only, no order payload generated", tone: "success" }],
    ...overrides,
  };
}

function makeState(overrides: Partial<BerkshireState> = {}): BerkshireState {
  const run = makeRun();
  const scan = makeScan();
  return {
    status: "ok",
    ts: "2026-06-27T03:20:00Z",
    schema_version: "berkshire.v1",
    lanes: [
      {
        key: "crypto",
        label: "Crypto Futures",
        status: "live",
        status_label: "Live lane",
        subtitle: "OKX swap execution.",
        execution: "OKX USDT SWAP",
        universe: "Top 50 market cap coins",
        risk_policy: "Dynamic risk",
        readiness: 82,
        instruments: ["BTC-USDT", "ETH-USDT"],
        blockers: ["Cross-lane exposure ledger pending"],
        telemetry: [{ label: "runtime", value: "connected", tone: "success" }],
      },
      {
        key: "forex",
        label: "Forex",
        status: "foundation",
        status_label: "Foundation lane",
        subtitle: "Parallel research desk.",
        execution: "Research-only, broker adapter planned",
        universe: "Majors, crosses, XAU, XAG",
        risk_policy: "Pending spread controls",
        readiness: 34,
        instruments: ["EUR/USD", "GBP/USD"],
        blockers: ["Broker adapter missing", "FX journal schema not extended"],
        telemetry: [{ label: "runtime", value: "planned", tone: "neutral" }],
      },
    ],
    pipelines: {
      crypto: [
        { title: "News pulse", owner: "Catalyst desk", status: "operational", tone: "success", description: "Create catalyst-aware research." },
        { title: "Quality screen", owner: "Moat desk", status: "operational", tone: "success", description: "Score quality." },
      ],
      forex: [
        { title: "Session model", owner: "Market desk", status: "planned", tone: "warning", description: "Separate market sessions." },
      ],
    },
    analyst_pods: [
      { label: "Business quality", value: "Moat, liquidity, durability", detail: "Quality-screen thinking." },
      { label: "Market structure", value: "Trend, range, volatility", detail: "Confluence context." },
      { label: "Risk governance", value: "Sizing, invalidation, exposure", detail: "Advisory only." },
      { label: "Evidence audit", value: "Source quality, stale context", detail: "Audit checks." },
    ],
    roadmap: [
      { stage: "Now", title: "Research workflow API", state: "done", tone: "success", detail: "API is live." },
    ],
    capabilities: [{ label: "State API", value: "GET /api/berkshire/state", tone: "success" }],
    requirements: [
      { label: "LLM multi-agent workers", status: "needed", tone: "warning", detail: "Use existing LLM/swarm layer." },
    ],
    crypto_scans: [scan],
    latest_crypto_scan: scan,
    runs: [run],
    active_run: run,
    audit_events: [
      { time: "03:20", label: "AI Berkshire source mapped", value: "skills plus tools", tone: "info" },
      { time: "03:21", label: "Signal contract active", value: "Berkshire emits SignalCandidate records", tone: "success" },
    ],
    ...overrides,
  };
}

describe("BerkshireDesk page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.getBerkshireState.mockResolvedValue(makeState());
    apiMock.createBerkshireResearch.mockResolvedValue({
      status: "ok",
      run: makeRun(),
      state: makeState(),
    });
    apiMock.createBerkshireCryptoScan.mockResolvedValue({
      status: "ok",
      scan: makeScan(),
      state: makeState(),
    });
  });

  it("loads the operational Crypto and Forex research desk from API", async () => {
    render(<BerkshireDesk />);

    expect(await screen.findByText("AI Berkshire Desk")).toBeInTheDocument();
    expect(screen.getByText("api live")).toBeInTheDocument();
    expect(screen.getAllByText("Crypto Futures").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Forex").length).toBeGreaterThan(0);
    expect(screen.getByText("Parallel research command for Crypto and Forex")).toBeInTheDocument();
    expect(apiMock.getBerkshireState).toHaveBeenCalledTimes(1);
  });

  it("switches to the Forex foundation lane without implying execution is live", async () => {
    render(<BerkshireDesk />);

    await screen.findByText("AI Berkshire Desk");
    fireEvent.click(screen.getByRole("button", { name: /ForexFoundation lane/ }));

    expect(screen.getAllByText("Research-only, broker adapter planned").length).toBeGreaterThan(0);
    expect(screen.getAllByText("EUR/USD").length).toBeGreaterThan(0);
    expect(screen.getByText("FX journal schema not extended")).toBeInTheDocument();
    expect(screen.getAllByText("Foundation lane").length).toBeGreaterThan(0);
  });

  it("shows pipeline and audit states as separate desk tabs", async () => {
    render(<BerkshireDesk />);

    await screen.findByText("AI Berkshire Desk");
    fireEvent.click(screen.getByRole("button", { name: /Pipeline/ }));
    expect(screen.getAllByText("News pulse").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Quality screen").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /Audit/ }));
    expect(screen.getByText("AI Berkshire source mapped")).toBeInTheDocument();
    expect(screen.getByText("Signal contract active")).toBeInTheDocument();
  });

  it("scans crypto signals and keeps them signal-only for LLM context", async () => {
    render(<BerkshireDesk />);

    await screen.findByText("AI Berkshire Desk");
    fireEvent.click(screen.getByRole("button", { name: /Scan top 50/ }));

    await waitFor(() => expect(apiMock.createBerkshireCryptoScan).toHaveBeenCalledTimes(1));
    expect(apiMock.createBerkshireCryptoScan).toHaveBeenCalledWith({
      limit: 50,
    });
    expect(await screen.findByText("latest crypto scan")).toBeInTheDocument();
    expect(screen.getAllByText("strong_candidate").length).toBeGreaterThan(0);
    expect(screen.getByText(/conf 88%/i)).toBeInTheDocument();
    expect(screen.getByText(/advisory evidence only/)).toBeInTheDocument();
  });

  it("creates a research run and opens the report tab", async () => {
    render(<BerkshireDesk />);

    await screen.findByText("AI Berkshire Desk");
    fireEvent.change(screen.getByLabelText("thesis"), {
      target: { value: "BTC has trend support with clear invalidation." },
    });
    fireEvent.change(screen.getByLabelText("entry"), { target: { value: "65000" } });
    fireEvent.change(screen.getByLabelText("stop"), { target: { value: "62000" } });
    fireEvent.change(screen.getByLabelText("target"), { target: { value: "73000" } });
    fireEvent.click(screen.getByRole("button", { name: /Create research run/ }));

    await waitFor(() => expect(apiMock.createBerkshireResearch).toHaveBeenCalledTimes(1));
    expect(apiMock.createBerkshireResearch).toHaveBeenCalledWith(
      expect.objectContaining({
        lane: "crypto",
        symbol: "BTC-USDT",
        entry_price: "65000",
        stop_loss: "62000",
        target_price: "73000",
      }),
    );
    expect(await screen.findByText("Checklist and financial rigor")).toBeInTheDocument();
    expect(screen.getByText("# Berkshire Research: BTC-USDT")).toBeInTheDocument();
  });
});
