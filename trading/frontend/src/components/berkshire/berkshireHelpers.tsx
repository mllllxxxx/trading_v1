import type { ReactNode } from "react";
import { Activity, BrainCircuit } from "lucide-react";
import type { BerkshireLaneKey, BerkshireSkill, BerkshireTone } from "@/lib/api";
import { cn } from "@/lib/utils";

export type DeskTab = "overview" | "signals" | "pipeline" | "audit" | "report";

export const TAB_LABELS: Array<{ key: DeskTab; label: string; icon: typeof Activity }> = [
  { key: "overview", label: "Overview", icon: Activity },
  { key: "signals", label: "Signals", icon: Activity },
  { key: "pipeline", label: "Pipeline", icon: Activity },
  { key: "audit", label: "Audit", icon: Activity },
  { key: "report", label: "Report", icon: Activity },
];

export const SKILLS: Array<{ value: BerkshireSkill; label: string }> = [
  { value: "investment-team", label: "Investment team" },
  { value: "investment-research", label: "Investment research" },
  { value: "investment-checklist", label: "Checklist" },
  { value: "quality-screen", label: "Quality screen" },
  { value: "news-pulse", label: "News pulse" },
  { value: "thesis-tracker", label: "Thesis tracker" },
  { value: "portfolio-review", label: "Portfolio review" },
];

export interface FormState {
  symbol: string;
  skill: BerkshireSkill;
  catalyst: string;
  thesis: string;
  entry_price: string;
  stop_loss: string;
  target_price: string;
  capital_usd: string;
}

export const DEFAULT_FORM: FormState = {
  symbol: "BTC-USDT",
  skill: "investment-team",
  catalyst: "",
  thesis: "",
  entry_price: "",
  stop_loss: "",
  target_price: "",
  capital_usd: "200",
};

export function toneText(tone: BerkshireTone): string {
  if (tone === "success") return "text-ttcc-green";
  if (tone === "warning") return "text-ttcc-yellow";
  if (tone === "danger") return "text-ttcc-red";
  if (tone === "info") return "text-ttcc-blue";
  if (tone === "accent") return "text-ttcc-accent";
  return "text-ttcc-text-secondary";
}

export function toneBg(tone: BerkshireTone): string {
  if (tone === "success") return "bg-ttcc-green";
  if (tone === "warning") return "bg-ttcc-yellow";
  if (tone === "danger") return "bg-ttcc-red";
  if (tone === "info") return "bg-ttcc-blue";
  if (tone === "accent") return "bg-ttcc-accent";
  return "bg-ttcc-text-muted";
}

export function StatusPill({ tone, children }: { tone: BerkshireTone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]",
        tone === "success" && "border-ttcc-green/40 bg-ttcc-green/10 text-ttcc-green",
        tone === "warning" && "border-ttcc-yellow/40 bg-ttcc-yellow/10 text-ttcc-yellow",
        tone === "danger" && "border-ttcc-red/40 bg-ttcc-red/10 text-ttcc-red",
        tone === "info" && "border-ttcc-blue/40 bg-ttcc-blue/10 text-ttcc-blue",
        tone === "accent" && "border-ttcc-accent/40 bg-ttcc-accent/10 text-ttcc-accent",
        tone === "neutral" && "border-ttcc-border bg-ttcc-surface-2 text-ttcc-text-secondary",
      )}
    >
      {children}
    </span>
  );
}

export function StatusDot({ tone }: { tone: BerkshireTone }) {
  return <span className={cn("h-2 w-2 shrink-0 rounded-full", toneBg(tone))} aria-hidden />;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">{label}</span>
      {children}
    </label>
  );
}

export function PanelHeader({
  icon: Icon,
  title,
  right,
}: {
  icon: typeof Activity;
  title: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-ttcc-border/70 px-3 py-2">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">
        <Icon className="h-3.5 w-3.5 text-ttcc-accent" />
        {title}
      </div>
      {right ? <div className="shrink-0">{right}</div> : null}
    </div>
  );
}

export function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-ttcc-border bg-ttcc-surface px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-[0.08em] text-ttcc-text-muted">{label}</div>
      <div className="mt-1 truncate font-mono text-[11px] text-ttcc-text">{value}</div>
    </div>
  );
}

export function EmptyRun() {
  return (
    <div className="m-3 flex min-h-36 items-center justify-center rounded-md border border-dashed border-ttcc-border bg-ttcc-bg p-5 text-center">
      <div>
        <BrainCircuit className="mx-auto h-7 w-7 text-ttcc-text-muted" />
        <h2 className="mt-3 text-sm font-semibold text-ttcc-text">No Berkshire run yet</h2>
        <p className="mt-1 text-[11px] text-ttcc-text-secondary">Create a research run to populate the report and audit trail.</p>
      </div>
    </div>
  );
}

export type { BerkshireLaneKey };
