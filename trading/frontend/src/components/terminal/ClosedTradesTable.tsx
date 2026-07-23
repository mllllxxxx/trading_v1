import {
  fmtPx,
  fmtTime,
  fmtUsd,
  colorClass,
  PillBadge,
  cn,
} from "@/components/terminal/primitives";
import {
  ConfluenceBadge,
  SideBadge,
  TeamBadge,
} from "@/components/terminal/PositionCard";
import type { ClosedTrade } from "@/types/api";

export function ClosedTradesTable({
  trades,
  startIndex = 0,
  totalTrades,
}: {
  trades: ClosedTrade[];
  startIndex?: number;
  totalTrades?: number;
}) {
  if (!trades.length) {
    return null;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead className="bg-ttcc-surface-2 text-[10px] uppercase tracking-wider text-ttcc-text-secondary">
          <tr className="border-b border-ttcc-border">
            <th className="px-2.5 py-1.5 text-left font-medium">#</th>
            <th className="px-2.5 py-1.5 text-left font-medium">Closed</th>
            <th className="px-2.5 py-1.5 text-left font-medium">Team</th>
            <th className="px-2.5 py-1.5 text-left font-medium">Symbol</th>
            <th className="px-2.5 py-1.5 text-left font-medium">Side</th>
            <th className="px-2.5 py-1.5 text-right font-medium">Entry</th>
            <th className="px-2.5 py-1.5 text-right font-medium">Exit</th>
            <th className="px-2.5 py-1.5 text-right font-medium">Size</th>
            <th className="px-2.5 py-1.5 text-right font-medium">PnL</th>
            <th className="px-2.5 py-1.5 text-left font-medium">Reason</th>
            <th className="px-2.5 py-1.5 text-right font-medium">Conf.</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => {
            const pnl = parseFloat(String(t.pnl_usd));
            const reason = t.exit_reason || "";
            const tradeNumber = startIndex + i + 1;
            const openReason = t.open_reason || t.decision_context?.thesis || t.decision_context?.reasoning_summary || "";
            const tone = reason.includes("profit") || reason.includes("tp")
              ? "tp"
              : reason.includes("stop") || reason.includes("sl")
              ? "sl"
              : "neutral";
            return (
              <tr key={i} className="border-b border-ttcc-border/40 hover:bg-ttcc-surface-2">
                <td
                  className="px-2.5 py-1 font-mono text-[10px] font-bold tabular text-ttcc-accent"
                  title={`Trade ${tradeNumber}${totalTrades ? ` of ${totalTrades}` : ""}`}
                >
                  #{tradeNumber}
                </td>
                <td className="px-2.5 py-1 font-mono tabular text-ttcc-text-muted">{fmtTime(t.closed_at)}</td>
                <td className="px-2.5 py-1">
                  <TeamBadge teamId={t.team_id} teamName={t.team_name || t.strategy_name} />
                </td>
                <td className="px-2.5 py-1 font-mono font-medium text-ttcc-text">{t.symbol.replace("-USDT", "")}</td>
                <td className="px-2.5 py-1"><SideBadge side={t.side} /></td>
                <td className="px-2.5 py-1 text-right font-mono tabular text-ttcc-text">{fmtPx(t.entry)}</td>
                <td className="px-2.5 py-1 text-right font-mono tabular text-ttcc-text">{fmtPx(t.exit_price)}</td>
                <td className="px-2.5 py-1 text-right font-mono tabular text-ttcc-text">{t.position_size}</td>
                <td className={cn(
                  "px-2.5 py-1 text-right font-mono font-semibold tabular",
                  colorClass(pnl)
                )}>
                  <span className="inline-flex items-center gap-0.5">
                    {pnl >= 0 ? "▲" : "▼"}{fmtUsd(pnl)}
                  </span>
                </td>
                <td className="px-2.5 py-1">
                  <PillBadge tone={tone as "tp" | "sl" | "neutral"}>{reason}</PillBadge>
                  {openReason ? (
                    <div
                      className="mt-1 max-w-[320px] truncate text-[10px] leading-tight text-ttcc-text-secondary"
                      title={openReason}
                    >
                      {openReason}
                    </div>
                  ) : null}
                </td>
                <td className="px-2.5 py-1 text-right"><ConfluenceBadge score={t.confluence_score} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
