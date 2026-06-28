import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Cockpit } from "../Cockpit";
import { vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  getLLMSettings: vi.fn(),
  getDataSourceSettings: vi.fn(),
  updateLLMSettings: vi.fn(),
  updateDataSourceSettings: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: apiMock,
}));

// Mock global fetch
const fetchMock = vi.fn();
globalThis.fetch = fetchMock;

describe("Cockpit page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchMock.mockReset();
    apiMock.getLLMSettings.mockReset();
    apiMock.getDataSourceSettings.mockReset();

    // Default fetch mocks
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/trader/status")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              timestamp: "2026-06-26T03:00:00Z",
              running: true,
              symbols: ["BTC-USDT", "ETH-USDT"],
              stats: {
                total_trades: 12,
                winrate: 58.3,
                current_capital: 10500,
              },
              positions: [],
            }),
        });
      }
      if (url.includes("/api/trader/ticker")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              tickers: [
                { symbol: "BTC-USDT", price: 65200, change_24h_pct: 1.8 },
                { symbol: "ETH-USDT", price: 3450, change_24h_pct: -0.5 },
              ],
            }),
        });
      }
      return Promise.reject(new Error("unknown fetch"));
    });

    apiMock.getLLMSettings.mockResolvedValue({
      provider: "deepseek",
      model_name: "deepseek-chat",
      base_url: "https://api.deepseek.com",
      temperature: 0.1,
      timeout_seconds: 120,
      max_retries: 2,
      providers: [],
    });
    apiMock.getDataSourceSettings.mockResolvedValue({
      tushare_token_configured: true,
      baostock_supported: false,
    });
  });

  it("renders cockpit header and empty positions by default", async () => {
    render(<Cockpit />);

    expect(await screen.findByText("Trading Control Cockpit")).toBeInTheDocument();
    expect(screen.getByText("No open positions")).toBeInTheDocument();
  });

  it("allows switching tabs in the workspace deck", async () => {
    render(<Cockpit />);

    // Journal (History) is active by default
    expect(screen.getByText("Closed Trades History Logs")).toBeInTheDocument();

    // Switch to Indicators Grid tab
    fireEvent.click(screen.getByRole("button", { name: /Indicators Grid/ }));
    expect(screen.getByText("Asset Watchlist & Market Regime Indicators")).toBeInTheDocument();

    // Switch to Correlation Matrix tab
    fireEvent.click(screen.getByRole("button", { name: /Correlation Matrix/ }));
    expect(screen.getByText("Compute Asset Correlation Coefficient")).toBeInTheDocument();

    // Switch to Settings tab
    fireEvent.click(screen.getByRole("button", { name: /Settings/ }));
    expect(await screen.findByText("LLM Agent & Environment Credentials")).toBeInTheDocument();
  });
});
