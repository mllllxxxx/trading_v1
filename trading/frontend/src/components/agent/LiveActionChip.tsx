import type { LiveAction } from "@/lib/api";
import { AgentAvatar } from "@/components/chat/AgentAvatar";
import { liveActionLabel, liveActionStyle } from "./liveHelpers";

export function LiveActionChip({ action }: { action: LiveAction }) {
  const { icon: Icon, tone } = liveActionStyle(action.kind);
  return (
    <div className="flex gap-3">
      <AgentAvatar />
      <div className="flex-1 min-w-0">
        <div
          className={[
            "inline-flex max-w-full flex-wrap items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs",
            tone,
          ].join(" ")}
        >
          <Icon className="h-3 w-3 shrink-0" />
          <span className="shrink-0 font-medium uppercase tracking-wide text-[10px]">RUNTIME</span>
          <span className="shrink-0 font-medium">{liveActionLabel(action)}</span>
          {action.intent_normalized && (
            <span className="truncate text-ttcc-text/80">· {action.intent_normalized}</span>
          )}
          {action.outcome && (
            <span className="shrink-0 font-mono text-[10px] text-ttcc-text-secondary">
              · {action.outcome}
            </span>
          )}
          {action.remote_tool && (
            <span className="shrink-0 font-mono text-[10px] text-ttcc-text-secondary">
              · {action.remote_tool}
            </span>
          )}
          {action.error && <span className="truncate text-ttcc-red">· {action.error}</span>}
        </div>
      </div>
    </div>
  );
}
