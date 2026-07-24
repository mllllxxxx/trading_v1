import type { BerkshireLane, BerkshireLaneKey } from "@/lib/api";
import { cn } from "@/lib/utils";
import { StatusPill } from "@/components/berkshire/berkshireHelpers";

export function LaneTabs({
  lanes,
  activeLane,
  onSelect,
}: {
  lanes: BerkshireLane[];
  activeLane: BerkshireLaneKey;
  onSelect: (key: BerkshireLaneKey) => void;
}) {
  return (
    <div className="grid min-w-[280px] grid-cols-2 rounded-lg border border-ttcc-border bg-ttcc-bg p-1">
      {lanes.map((item) => (
        <button
          key={item.key}
          type="button"
          onClick={() => onSelect(item.key)}
          className={cn(
            "flex min-h-12 flex-col items-start rounded-lg px-2.5 py-1.5 text-left transition-colors",
            item.key === activeLane
              ? "bg-ttcc-accent/15 text-ttcc-accent ring-1 ring-ttcc-accent/40"
              : "text-ttcc-text-secondary hover:bg-ttcc-surface-2 hover:text-ttcc-text",
          )}
          aria-pressed={item.key === activeLane}
        >
          <span className="text-[11px] font-bold">{item.label}</span>
          <span className="mt-0.5 text-[10px] text-current opacity-75">{item.status_label}</span>
        </button>
      ))}
    </div>
  );
}

export function LaneCard({
  lane,
  active,
  onSelect,
}: {
  lane: BerkshireLane;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn("w-full px-3 py-3 text-left transition-colors", active ? "bg-ttcc-accent/10" : "hover:bg-ttcc-surface-2/80")}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[13px] font-semibold text-ttcc-text">{lane.label}</div>
          <div className="mt-1 text-[11px] text-ttcc-text-secondary">{lane.execution}</div>
        </div>
        <StatusPill tone={lane.key === "crypto" ? "success" : "warning"}>{lane.status_label}</StatusPill>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-lg bg-ttcc-bg">
        <div className={cn("h-full rounded-lg", lane.readiness >= 70 ? "bg-ttcc-green" : "bg-ttcc-yellow")} style={{ width: `${lane.readiness}%` }} />
      </div>
      <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-ttcc-text-muted tabular">
        <span>{lane.universe}</span>
        <span>{lane.readiness}%</span>
      </div>
      {lane.blockers.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {lane.blockers.map((blocker) => (
            <span
              key={blocker}
              className="rounded-lg border border-ttcc-yellow/30 bg-ttcc-yellow/10 px-1.5 py-0.5 text-[10px] font-medium text-ttcc-yellow"
            >
              {blocker}
            </span>
          ))}
        </div>
      ) : null}
    </button>
  );
}
