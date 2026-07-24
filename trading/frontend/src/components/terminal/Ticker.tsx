import { useMemo } from "react";
import { cn, fmtPx, fmtPctSigned } from "@/components/terminal/primitives";

export type TickerEntry = {
  symbol: string;
  price?: number;
  change_24h_pct?: number;
  high_24h?: number;
  low_24h?: number;
  error?: string;
};

/**
 * Ticker — auto-scrolling market data strip.
 * Renders the entries twice back-to-back and translates -50% over 60s
 * for a seamless infinite loop. Pause-on-hover.
 */
export function Ticker({ tickers, symbols }: { tickers: TickerEntry[]; symbols: string[] }) {
  const loop = useMemo(() => {
    return [...symbols, ...symbols].map((sym) => {
      const t = tickers.find((x) => x.symbol === sym);
      return { sym, t };
    });
  }, [tickers, symbols]);

  return (
    <div className="relative flex-1 overflow-hidden">
      {/* Soft gradient edge masks so the marquee doesn't slap the wall. */}
      <div className="pointer-events-none absolute inset-y-0 left-0 w-10 bg-gradient-to-r from-ttcc-bg to-transparent z-10" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-ttcc-bg to-transparent z-10" />
      <div className="tt-ticker-track py-1.5">
        {loop.map((it, i) => {
          const price = it.t?.price;
          const ch = it.t?.change_24h_pct;
          const hi = it.t?.high_24h;
          const lo = it.t?.low_24h;
          const up = ch !== null && ch !== undefined && ch >= 0;
          const tone = up ? "text-ttcc-green" : "text-ttcc-red";
          const arrow = up ? "▲" : "▼";
          const hasErr = !!it.t?.error;
          const bigMove = ch !== null && ch !== undefined && Math.abs(ch) > 3;
          return (
            <div key={`${it.sym}-${i}`} className="flex shrink-0 items-center gap-4 px-4 text-[12px] leading-none">
              <span className="font-semibold text-[12px] text-ttcc-text">{it.sym.replace("-USDT", "")}</span>
              <span className={cn("font-mono font-medium text-[12px] tabular", hasErr ? "text-ttcc-red" : "text-ttcc-text")}>
                {hasErr ? "ERR" : fmtPx(price)}
              </span>
              <span
                className={cn(
                  "font-mono tabular",
                  tone,
                  bigMove && (up ? "tt-glow-green" : "tt-glow-red")
                )}
              >
                {ch === null || ch === undefined ? "—" : `${arrow}${fmtPctSigned(ch)}`}
              </span>
              {hi !== undefined && lo !== undefined ? (
                <span className="hidden md:inline font-mono tabular text-[10px] text-ttcc-text-muted">
                  H {fmtPx(hi)} · L {fmtPx(lo)}
                </span>
              ) : null}
              <span className="text-ttcc-text-muted/20">·</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
