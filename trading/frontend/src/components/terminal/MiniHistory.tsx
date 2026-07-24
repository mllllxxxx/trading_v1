import { PillBadge, fmtTime, fmtUsd } from "@/components/terminal/primitives";

export type MiniTrade = {
  closed_at: string;
  symbol: string;
  side: string;
  pnl_usd: number;
  exit_reason?: string;
};

/**
 * MiniHistory — compact 3-row recent trades strip for the bottom bar.
 * Renders newest first with side badge + signed PnL.
 */
export function MiniHistory({ trades }: { trades: MiniTrade[] }) {
  const rows = trades.slice(0, 3);
  if (!rows.length) {
    return (
      <div className="font-mono text-[11px] text-ttcc-text-muted px-3 py-1.5">
        no closed trades yet
      </div>
    );
  }
  return (
    <div className="flex items-center gap-4 px-2 overflow-hidden">
      {rows.map((t, i) => {
        const isLong = t.side === "buy";
        const up = t.pnl_usd >= 0;
        return (
          <div key={i} className="flex items-center gap-1.5 text-[11px] whitespace-nowrap">
            <span className="font-mono tabular text-[11px] text-ttcc-text-muted">
              {fmtTime(t.closed_at).substring(11, 16)}
            </span>
            <span className="font-mono font-semibold text-ttcc-text text-[12px]">
              {t.symbol.replace("-USDT", "")}
            </span>
            <PillBadge tone={isLong ? "long" : "short"}>{isLong ? "L" : "S"}</PillBadge>
            <span
              className={
                up
                  ? "font-mono tabular text-ttcc-green font-semibold text-[12px]"
                  : "font-mono tabular text-ttcc-red font-semibold text-[12px]"
              }
            >
              {fmtUsd(t.pnl_usd)}
            </span>
            {i < rows.length - 1 ? (
              <span className="text-ttcc-text-muted/20 mx-1">·</span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
