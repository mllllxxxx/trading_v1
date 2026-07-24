import { Loader2, Radar, Target } from "lucide-react";
import type { BerkshireCryptoScan, BerkshireSignal } from "@/lib/api";
import { MiniMetric, StatusPill } from "@/components/berkshire/berkshireHelpers";

export function SignalsPanel({
  scan,
  scanning,
  onScan,
}: {
  scan: BerkshireCryptoScan | null;
  scanning: boolean;
  onScan: (autoPromoteDemo?: boolean) => void;
}) {
  if (!scan) {
    return (
      <div className="m-3 flex min-h-56 items-center justify-center rounded-lg border border-dashed border-ttcc-border bg-ttcc-bg p-5 text-center">
        <div>
          <Radar className="mx-auto h-7 w-7 text-ttcc-text-muted" />
          <h2 className="mt-3 text-sm font-semibold text-ttcc-text">No crypto signal scan yet</h2>
          <p className="mt-1 max-w-sm text-[11px] leading-5 text-ttcc-text-secondary">
            Scan the crypto lane to create Berkshire signal-only context before the LLM drafts any ticket.
          </p>
          <button
            type="button"
            onClick={() => onScan(false)}
            disabled={scanning}
            className="mt-4 inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-ttcc-accent/60 bg-ttcc-accent/15 px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-ttcc-accent transition-colors hover:bg-ttcc-accent/25 disabled:opacity-50"
          >
            {scanning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Radar className="h-3.5 w-3.5" />}
            Scan top 50
          </button>
          <button
            type="button"
            onClick={() => onScan(true)}
            disabled={scanning}
            className="ml-2 mt-4 inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-ttcc-green/60 bg-ttcc-green/10 px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-ttcc-green transition-colors hover:bg-ttcc-green/20 disabled:opacity-50"
          >
            {scanning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Target className="h-3.5 w-3.5" />}
            Scan + demo top 10
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3 p-3">
      <article className="rounded-lg border border-ttcc-border bg-ttcc-bg p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">
              latest crypto scan
            </div>
            <h2 className="mt-1 font-mono text-lg font-bold text-ttcc-text">{scan.top_symbol ?? "No top signal"}</h2>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <StatusPill tone="accent">{scan.mode}</StatusPill>
            <StatusPill tone={scan.provider_error ? "warning" : "success"}>{scan.source}</StatusPill>
          </div>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-4">
          <MiniMetric label="signals" value={String(scan.signal_count)} />
          <MiniMetric label="universe" value={String(scan.universe_count)} />
          <MiniMetric label="top state" value={scan.top_signal ?? "none"} />
          <MiniMetric label="demo runs" value={String(scan.demo_promotions?.length ?? 0)} />
        </div>
        {scan.demo_promotions?.length ? (
          <div className="mt-3 grid gap-2">
            {scan.demo_promotions.map((promotion) => (
              <div
                key={promotion.decision_id}
                className="rounded-lg border border-ttcc-green/30 bg-ttcc-green/10 px-2.5 py-2 text-[11px] leading-5 text-ttcc-green"
              >
                {promotion.executed ? promotion.reason : promotion.stage}: {promotion.reason}
              </div>
            ))}
          </div>
        ) : null}
        {scan.provider_error ? (
          <p className="mt-3 rounded-lg border border-ttcc-yellow/30 bg-ttcc-yellow/10 px-2.5 py-2 text-[11px] leading-5 text-ttcc-yellow">
            {scan.provider_error}
          </p>
        ) : null}
      </article>

      <div className="grid gap-2">
        {scan.signals.map((signal) => (
          <SignalCard key={signal.signal_id || signal.symbol} signal={signal} />
        ))}
      </div>
    </div>
  );
}

export function SignalCard({ signal }: { signal: BerkshireSignal }) {
  const status = signal.status || signal.signal;
  const reasons = signal.reasons?.length ? signal.reasons : signal.why;
  const tone = status === "blocked" ? "danger" : status === "watchlist" ? "warning" : "success";
  const confidence = `${Math.round((signal.confidence ?? 0) * 100)}%`;
  return (
    <article className="rounded-lg border border-ttcc-border bg-ttcc-bg p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-mono text-base font-bold text-ttcc-text">{signal.symbol}</h2>
            <StatusPill tone={tone}>{status}</StatusPill>
            <StatusPill tone="neutral">{signal.direction}</StatusPill>
            <StatusPill tone="info">{signal.action_hint}</StatusPill>
          </div>
          <p className="mt-1 text-[11px] leading-5 text-ttcc-text-secondary">{signal.llm_context.instruction}</p>
        </div>
        <div className="text-right">
          <div className="font-mono text-lg font-bold text-ttcc-accent">{signal.score}</div>
          <div className="text-[10px] uppercase tracking-[0.08em] text-ttcc-text-muted">
            grade {signal.grade} · conf {confidence}
          </div>
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-4">
        <MiniMetric label="last" value={signal.last_price ?? "n/a"} />
        <MiniMetric label="24h" value={signal.change_pct_24h ? `${signal.change_pct_24h}%` : "n/a"} />
        <MiniMetric label="conf" value={confidence} />
        <MiniMetric label="entry" value={signal.entry_zone} />
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">why</div>
          <ul className="mt-1 space-y-1">
            {reasons.map((item) => (
              <li key={item} className="text-[11px] leading-5 text-ttcc-text-secondary">
                {item}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">blockers</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {signal.blockers.length ? (
              signal.blockers.map((item) => (
                <span key={item} className="rounded-lg border border-ttcc-yellow/30 bg-ttcc-yellow/10 px-1.5 py-0.5 text-[10px] text-ttcc-yellow">
                  {item}
                </span>
              ))
            ) : (
              <span className="rounded-lg border border-ttcc-green/30 bg-ttcc-green/10 px-1.5 py-0.5 text-[10px] text-ttcc-green">
                no blocker
              </span>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}
