import type { Position } from "@/components/terminal/PositionCard";

export function canonicalPositionSymbol(symbol: string | undefined | null): string {
  let raw = String(symbol || "").trim().toUpperCase();
  if (!raw) {
    return "";
  }
  if (raw.includes(":")) {
    raw = raw.split(":", 1)[0];
  }
  raw = raw.replace("/", "-");
  if (raw.endsWith("-SWAP")) {
    raw = raw.slice(0, -"-SWAP".length);
  }
  const parts = raw.split("-").filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0]}-${parts[1]}`;
  }
  return raw;
}

export function mergePositionFeeds(
  journalPositions: Position[] = [],
  exchangePositions: Position[] = [],
): Position[] {
  const bySymbol = new Map<string, Position>();
  const order: string[] = [];

  const putExchange = (position: Position) => {
    const key = canonicalPositionSymbol(position.symbol);
    if (!key) return;
    if (!bySymbol.has(key)) {
      order.push(key);
    }
    bySymbol.set(key, {
      ...position,
      symbol: key,
      source: position.source || "exchange",
    });
  };

  const putJournal = (position: Position) => {
    const key = canonicalPositionSymbol(position.symbol);
    if (!key) return;
    const exchange = bySymbol.get(key);
    if (!exchange) {
      order.push(key);
      bySymbol.set(key, { ...position, symbol: key });
      return;
    }
    bySymbol.set(key, {
      ...exchange,
      ...position,
      symbol: key,
      mark_price: position.mark_price ?? exchange.mark_price,
      unrealized_pnl: position.unrealized_pnl ?? exchange.unrealized_pnl,
      leverage: position.leverage ?? exchange.leverage,
      margin_mode: position.margin_mode ?? exchange.margin_mode,
      contracts: position.contracts ?? exchange.contracts,
      contract_size: position.contract_size ?? exchange.contract_size,
      broker_sync_at: position.broker_sync_at ?? exchange.broker_sync_at,
      sync_status: position.sync_status ?? exchange.sync_status,
      status: position.status ?? exchange.status,
      source: position.source ?? exchange.source,
      mode: position.mode ?? exchange.mode,
      instId: position.instId ?? exchange.instId,
      ccxt_symbol: position.ccxt_symbol ?? exchange.ccxt_symbol,
      protective_orders: position.protective_orders ?? exchange.protective_orders,
      orders: position.orders ?? exchange.orders,
      market_context: position.market_context ?? exchange.market_context,
      decision_context: position.decision_context ?? exchange.decision_context,
      open_reason: position.open_reason ?? exchange.open_reason,
    });
  };

  exchangePositions.forEach(putExchange);
  journalPositions.forEach(putJournal);
  return order.map((key) => bySymbol.get(key)).filter((item): item is Position => Boolean(item));
}
