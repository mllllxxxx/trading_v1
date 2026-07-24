import type { FormEvent } from "react";
import { BrainCircuit, Loader2, SlidersHorizontal, TriangleAlert } from "lucide-react";
import type { BerkshireLane, BerkshireLaneKey, BerkshireState } from "@/lib/api";
import {
  Field,
  PanelHeader,
  SKILLS,
  StatusPill,
  type FormState,
} from "@/components/berkshire/berkshireHelpers";

export function TicketComposer({
  form,
  lane,
  activeLane,
  state,
  submitting,
  onFormChange,
  onSubmit,
}: {
  form: FormState;
  lane: BerkshireLane;
  activeLane: BerkshireLaneKey;
  state: BerkshireState;
  submitting: boolean;
  onFormChange: (key: keyof FormState, value: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <aside className="rounded-lg border border-ttcc-border bg-ttcc-surface">
      <PanelHeader icon={SlidersHorizontal} title="Run research" right={<StatusPill tone={activeLane === "forex" ? "warning" : "success"}>{lane.status_label}</StatusPill>} />
      <form onSubmit={onSubmit} className="space-y-3 p-3">
        <div className="grid grid-cols-2 gap-2">
          <Field label="symbol">
            <input
              value={form.symbol}
              onChange={(event) => onFormChange("symbol", event.target.value.toUpperCase())}
              className="field-input font-mono"
              placeholder={lane.instruments[0]}
            />
          </Field>
          <Field label="skill">
            <select
              value={form.skill}
              onChange={(event) => onFormChange("skill", event.target.value as FormState["skill"])}
              className="field-input"
            >
              {SKILLS.map((skill) => (
                <option key={skill.value} value={skill.value}>
                  {skill.label}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Field label="catalyst">
          <textarea
            value={form.catalyst}
            onChange={(event) => onFormChange("catalyst", event.target.value)}
            className="field-input min-h-16 resize-y"
            placeholder="ETF inflow, CPI surprise, funding reset..."
          />
        </Field>
        <Field label="thesis">
          <textarea
            value={form.thesis}
            onChange={(event) => onFormChange("thesis", event.target.value)}
            className="field-input min-h-20 resize-y"
            placeholder="What has to be true, and where is invalidation?"
          />
        </Field>

        <div className="grid grid-cols-2 gap-2">
          <Field label="entry">
            <input value={form.entry_price} onChange={(event) => onFormChange("entry_price", event.target.value)} className="field-input font-mono" />
          </Field>
          <Field label="stop">
            <input value={form.stop_loss} onChange={(event) => onFormChange("stop_loss", event.target.value)} className="field-input font-mono" />
          </Field>
          <Field label="target">
            <input value={form.target_price} onChange={(event) => onFormChange("target_price", event.target.value)} className="field-input font-mono" />
          </Field>
          <Field label="capital">
            <input value={form.capital_usd} onChange={(event) => onFormChange("capital_usd", event.target.value)} className="field-input font-mono" />
          </Field>
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-ttcc-accent/60 bg-ttcc-accent/15 px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-ttcc-accent transition-colors hover:bg-ttcc-accent/25 disabled:opacity-50"
        >
          {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BrainCircuit className="h-3.5 w-3.5" />}
          Create research run
        </button>
      </form>

      <div className="border-t border-ttcc-border/70">
        <PanelHeader icon={TriangleAlert} title="Still needed" />
        <div className="divide-y divide-ttcc-border/60">
          {state.requirements.map((item) => (
            <div key={item.label} className="px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold text-ttcc-text">{item.label}</span>
                <StatusPill tone={item.tone}>{item.status}</StatusPill>
              </div>
              <p className="mt-1 text-[11px] leading-5 text-ttcc-text-secondary">{item.detail}</p>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}
