import { Activity, X } from "lucide-react";
import { cn, fmtPx, fmtTime, useFlashClass } from "@/components/terminal/primitives";

const CONFLUENCE_MAX = 8;

export type Position = {
  symbol: string;
  side: string;
  entry: number;
  stop_loss: number;
  take_profit: number;
  position_size: number;
  rr_ratio: number;
  confluence_score: number;
  regime: string;
  opened_at: string;
  entry_type?: string;
};

/**
 * PositionCard — single open-position card.
 * Includes SL/TP progress bar, R:R ratio badge, confluence badge.
 */
export function PositionCard({ p, mark }: { p: Position; mark: number | null }) {
  const isLong = p.side === "buy";
  const px = mark ?? p.entry;
  const pnlUsd = (isLong ? px - p.entry : p.entry - px) * p.position_size;
  const pnlPct = isLong
    ? ((px - p.entry) / p.entry) * 100
    : ((p.entry - px) / p.entry) * 100;
  const positive = pnlUsd >= 0;
  const range = Math.max(0.0001, Math.abs(p.take_profit - p.stop_loss));
  const fromEntry = isLong ? px - p.entry : p.entry - px;
  const progress = Math.max(0, Math.min(100, 50 + (fromEntry / range) * 50));
  const flashCls = useFlashClass(pnlUsd);
  const slDist = isLong ? ((p.stop_loss - px) / px) * 100 : ((px - p.stop_loss) / px) * 100;
  const tpDist = isLong ? ((p.take_profit - px) / px) * 100 : ((px - p.take_profit) / px) * 100;

  return (
    <div className={cn(
      "group relative flex flex-col rounded border bg-ttcc-surface overflow-hidden tt-card-hover",
      positive ? "border-ttcc-green/30" : "border-ttcc-red/30"
    )}>
      {/* Header strip */}
      <div className="flex items-center justify-between gap-1 border-b border-ttcc-border bg-ttcc-surface-2 px-2.5 py-1.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="font-mono text-[13px] font-bold tracking-tight text-ttcc-text truncate">
            {p.symbol.replace("-USDT", "")}
          </span>
          <SideBadge side={p.side} />
          {p.entry_type ? (
            <span className="hidden sm:inline rounded border border-ttcc-border bg-ttcc-surface px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-secondary">
              {p.entry_type}
            </span>
          ) : null}
        </div>
        <button
          type="button"
          aria-label="Close position"
          title="Close position"
          className="rounded p-0.5 text-ttcc-text-secondary opacity-60 transition-opacity hover:bg-ttcc-red/15 hover:text-ttcc-red hover:opacity-100"
        >
          <X className="h-3 w-3" />
        </button>
      </div>

      {/* PnL — the big number */}
      <div className={cn("px-2.5 pt-2 pb-1.5", flashCls)}>
        <div className="flex items-baseline justify-between gap-2">
          <div className={cn(
            "font-mono text-[22px] font-bold leading-none tabular",
            positive ? "text-ttcc-green" : "text-ttcc-red"
          )}>
            {positive ? "+" : ""}{pnlUsd.toFixed(2)}
            <span className="ml-1 text-[10px] font-medium text-ttcc-text-secondary">USD</span>
          </div>
          <div className={cn(
            "font-mono text-[12px] font-semibold leading-none tabular",
            positive ? "text-ttcc-green" : "text-ttcc-red"
          )}>
            {positive ? "+" : ""}{pnlPct.toFixed(2)}%
          </div>
        </div>
        <div className="mt-1 flex items-center gap-1 text-[10px] text-ttcc-text-secondary tabular">
          <span>mark</span>
          <span className="text-ttcc-text">{mark !== null ? fmtPx(px) : "—"}</span>
          {mark !== null ? (
            <span className="text-ttcc-text-muted">·live</span>
          ) : (
            <span className="text-ttcc-text-muted">·no tick</span>
          )}
        </div>
      </div>

      {/* SL/TP bar */}
      <div className="px-2.5 pb-2">
        <div className="relative h-1.5 rounded-full bg-ttcc-surface-2">
          <div className="absolute top-0 left-1/2 h-full w-px bg-ttcc-border" aria-hidden />
          <div
            className={cn("absolute top-0 h-full rounded-full transition-all duration-300", positive ? "bg-ttcc-green" : "bg-ttcc-red")}
            style={{
              left: progress >= 50 ? "50%" : `${progress}%`,
              width: `${Math.abs(progress - 50)}%`,
            }}
          />
        </div>
        <div className="mt-1 flex items-center justify-between text-[10px] tabular">
          <span className="flex items-center gap-1 text-ttcc-red">
            <span className="opacity-70">SL</span>
            <span className="font-mono">{fmtPx(p.stop_loss)}</span>
            <span className="text-ttcc-text-muted">({slDist.toFixed(2)}%)</span>
          </span>
          <span className="flex items-center gap-1 text-ttcc-green">
            <span className="text-ttcc-text-muted">({tpDist.toFixed(2)}%)</span>
            <span className="opacity-70">TP</span>
            <span className="font-mono">{fmtPx(p.take_profit)}</span>
          </span>
        </div>
      </div>

      {/* Footer grid — dense meta */}
      <div className="grid grid-cols-3 gap-x-2 gap-y-1.5 border-t border-ttcc-border/60 bg-ttcc-surface-2 px-2.5 py-1.5 text-[10px]">
        <div className="min-w-0">
          <div className="text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-muted">Entry</div>
          <div className="font-mono font-medium tabular truncate text-ttcc-text">{fmtPx(p.entry)}</div>
        </div>
        <div className="min-w-0">
          <div className="text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-muted">Size</div>
          <div className="font-mono font-medium tabular truncate text-ttcc-text">{p.position_size}</div>
        </div>
        <div className="min-w-0">
          <div className="text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-muted">R:R</div>
          <div><RrBadge rr={p.rr_ratio} /></div>
        </div>
        <div className="min-w-0">
          <div className="text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-muted">Conf.</div>
          <div><ConfluenceBadge score={p.confluence_score} /></div>
        </div>
        <div className="min-w-0">
          <div className="text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-muted">Regime</div>
          <div className="font-mono text-ttcc-text-secondary uppercase truncate">{p.regime}</div>
        </div>
        <div className="min-w-0">
          <div className="text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-muted">Opened</div>
          <div className="font-mono text-ttcc-text-secondary tabular truncate">{fmtTime(p.opened_at)}</div>
        </div>
      </div>
    </div>
  );
}

export function SideBadge({ side }: { side: string }) {
  const isLong = side === "buy";
  return (
    <span className={cn(
      "inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase leading-none tracking-wider",
      isLong
        ? "text-ttcc-green bg-ttcc-green/10 border-ttcc-green/40"
        : "text-ttcc-red bg-ttcc-red/10 border-ttcc-red/40"
    )}>
      {isLong ? "LONG" : "SHORT"}
    </span>
  );
}

export function ConfluenceBadge({ score, max = CONFLUENCE_MAX }: { score: number; max?: number }) {
  const s = Math.max(0, Math.min(max, Math.round(score)));
  const tone =
    s >= 6 ? "text-ttcc-green bg-ttcc-green/10 border-ttcc-green/40"
    : s >= 4 ? "text-ttcc-yellow bg-ttcc-yellow/10 border-ttcc-yellow/40"
    : "text-ttcc-red bg-ttcc-red/10 border-ttcc-red/40";
  return (
    <span className={cn(
      "inline-flex items-center gap-0.5 rounded border px-1.5 py-0.5 font-mono text-[11px] font-medium leading-none tabular",
      tone
    )}>
      <span>+{s}</span>
      <span className="text-ttcc-text-muted opacity-60">/{max}</span>
    </span>
  );
}

export function RrBadge({ rr }: { rr: number }) {
  const good = rr >= 2;
  return (
    <span className={cn(
      "inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[11px] font-medium leading-none tabular",
      good
        ? "text-ttcc-green bg-ttcc-green/10 border-ttcc-green/40"
        : "text-ttcc-text-secondary bg-ttcc-surface-2 border-ttcc-border"
    )}>
      1:{rr?.toFixed(2)}
    </span>
  );
}

export function EmptyPositions() {
  return (
    <div className="flex h-32 flex-col items-center justify-center rounded border border-dashed border-ttcc-border bg-ttcc-surface/40 text-[11px] text-ttcc-text-secondary">
      <Activity className="mb-1 h-4 w-4 opacity-40" />
      <span>No open positions</span>
      <span className="text-[10px] opacity-60">scanner running · waiting for signal</span>
    </div>
  );
}
