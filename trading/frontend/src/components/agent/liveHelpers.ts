import { Activity, Ban, CheckCircle2, OctagonX } from "lucide-react";
import type { LiveAction, LiveHalted, LiveStatus } from "@/lib/api";

export function normalizeBrokerScope(broker: string | null | undefined): string | null {
  const normalized = broker?.trim().toLowerCase();
  return normalized || null;
}

export function isGlobalLiveHalt(halt: LiveHalted | null): boolean {
  return halt != null && normalizeBrokerScope(halt.broker) == null;
}

export function haltScopeStillActive(halt: LiveHalted, status: LiveStatus): boolean {
  const broker = normalizeBrokerScope(halt.broker);
  if (!broker) return status.global_halted;
  return status.global_halted || status.brokers.some((item) => (
    normalizeBrokerScope(item.auth.broker) === broker && item.halted
  ));
}

export type LiveActionStyle = {
  icon: typeof Activity;
  tone: string;
};

export function liveActionStyle(kind: string): LiveActionStyle {
  switch (kind) {
    case "order_rejected":
    case "breach":
      return { icon: Ban, tone: "border-amber-500/40 bg-amber-500/5 text-amber-600 dark:text-amber-400" };
    case "halt_tripped":
      return { icon: OctagonX, tone: "border-destructive/40 bg-destructive/5 text-destructive" };
    case "mandate_committed":
    case "halt_cleared":
      return { icon: CheckCircle2, tone: "border-emerald-500/40 bg-emerald-500/5 text-emerald-600 dark:text-emerald-400" };
    default:
      return { icon: Activity, tone: "border-sky-500/40 bg-sky-500/5 text-sky-600 dark:text-sky-400" };
  }
}

export function liveActionLabel(action: LiveAction): string {
  return action.kind.replace(/_/g, " ");
}
