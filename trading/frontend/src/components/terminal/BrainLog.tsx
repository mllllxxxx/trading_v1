import { useEffect, useRef, useState } from "react";
import { Brain } from "lucide-react";
import { PanelLabel, PillBadge, cn, fmtTime } from "@/components/terminal/primitives";

export type BrainDecision = {
  ts: string;
  type: string;
  [key: string]: unknown;
};

/**
 * BrainLog — scrolling feed of recent LLM decisions.
 *
 * Each row: time · action badge (LONG/SHORT/HOLD/...) · type pill · confidence · reasoning.
 * New rows slide in from below (220ms). Auto-trims to `maxRows`.
 */
export function BrainLog({ decisions, maxRows = 30 }: { decisions: BrainDecision[]; maxRows?: number }) {
  const [seenIds, setSeenIds] = useState<Set<string>>(new Set());
  const initializedRef = useRef(false);

  // Mark every decision we've already rendered so we can highlight only new ones.
  useEffect(() => {
    if (initializedRef.current && decisions.length) {
      const next = new Set<string>();
      decisions.slice(0, maxRows).forEach((d) => next.add(`${d.ts}-${d.type}`));
      setSeenIds(next);
      return;
    }
    initializedRef.current = true;
    const initial = new Set<string>();
    decisions.slice(0, maxRows).forEach((d) => initial.add(`${d.ts}-${d.type}`));
    setSeenIds(initial);
  }, [decisions, maxRows]);

  const rows = decisions.slice(0, maxRows);

  if (!rows.length) {
    return (
      <div className="rounded-lg border border-ttcc-border-subtle bg-ttcc-surface">
        <PanelLabel icon={Brain} tone="info">Brain log</PanelLabel>
        <div className="px-2.5 py-8 text-center text-[12px] text-ttcc-text-muted">
          <div className="flex justify-center mb-2">
            <Brain className="h-8 w-8 text-ttcc-blue/40 tt-glow-accent" />
          </div>
          <div className="font-medium text-ttcc-text-secondary">No LLM activity in last ~1000 events</div>
          <div className="mt-1 text-[11px]">Regime conflict or weak confluence — LLM skipped to save tokens.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-ttcc-border-subtle bg-ttcc-surface">
      <PanelLabel
        icon={Brain}
        tone="info"
        right={<span className="font-mono text-[11px] tabular text-ttcc-text-muted">{rows.length}</span>}
      >
        Brain log
      </PanelLabel>
      <ul className="max-h-[60vh] overflow-y-auto">
        {rows.map((d, i) => {
          const id = `${d.ts}-${d.type}`;
          const isNew = !seenIds.has(id) && i === 0;
          return (
            <li
              key={id}
              className={cn(
                "border-b border-ttcc-border-subtle/40 px-3 py-2 last:border-b-0",
                "hover:bg-ttcc-surface-2/30 transition-colors",
                isNew && "ttcc-row-in"
              )}
            >
              <BrainRow d={d} />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function BrainRow({ d }: { d: BrainDecision }) {
  let action = "—";
  let reasoning = "—";
  let tone: "long" | "short" | "neutral" | "warn" | "info" = "neutral";

  if (d.type === "llm") {
    action = ((d.action as string) || "—").toUpperCase();
    reasoning = ((d.reasoning as string) || "—");
  } else if (d.type === "llm_override_hold") {
    action = "HOLD";
    reasoning = ((d.reasoning_text as string) || "—");
  } else if (d.type === "llm_override_no_trade") {
    action = "NO TRADE";
    reasoning = ((d.reasoning_text as string) || "—");
  } else if (d.type === "llm_decision_used") {
    action = ((d.action as string) || "—").toUpperCase();
    reasoning = `SL=${d.stop_loss} · TP=${d.take_profit}`;
  } else if (d.type === "llm_draft_ticket") {
    action = ((d.action as string) || "TICKET").toUpperCase();
    const symbol = (d.symbol as string) || "";
    const playbook = (d.playbook_id as string) || "";
    const text = ((d.reasoning as string) || (d.thesis as string) || "TradeDecisionTicket drafted");
    reasoning = [symbol, playbook, text].filter(Boolean).join(" · ");
  } else if (d.type === "llm_error") {
    action = "ERROR";
    reasoning = ((d.error as string) || "—");
    tone = "short";
  } else {
    action = d.type;
  }

  if (action.includes("LONG")) tone = "long";
  else if (action.includes("SHORT")) tone = "short";
  else if (action === "HOLD" || action === "NO TRADE") tone = "warn";

  const confidence = typeof d.confidence === "number" ? d.confidence : null;

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1.5 text-[11px]">
        <span className="font-mono tabular text-[11px] text-ttcc-text-muted shrink-0">{fmtTime(d.ts)}</span>
        <PillBadge tone={tone} mono>{action}</PillBadge>
        {confidence !== null ? (
          <span className="font-mono text-[10px] tabular text-ttcc-text-secondary">
            {(confidence * 100).toFixed(0)}%
          </span>
        ) : null}
      </div>
      <div
        className="text-[12px] text-ttcc-text-secondary truncate"
        title={reasoning}
      >
        {reasoning}
      </div>
    </div>
  );
}
