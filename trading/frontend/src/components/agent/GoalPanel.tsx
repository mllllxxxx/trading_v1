import { useTranslation } from "react-i18next";
import {
  Target,
  ChevronDown,
  Pencil,
  Check,
  Play,
  X,
} from "lucide-react";
import type { GoalSnapshot } from "@/lib/api";
import {
  getGoalProgress,
  criterionEvidenceCount,
  criterionCovered,
  isCriterionStatusMet,
  statusLabel,
  criterionIndexLabel,
  latestGoalEvidence,
} from "./goalHelpers";

interface GoalPanelProps {
  goalSnapshot: GoalSnapshot;
  goalDetailsOpen: boolean;
  goalEditActive: boolean;
  goalEditValue: string;
  onToggleDetails: () => void;
  onStartGoalEdit: () => void;
  onSaveGoalEdit: () => void;
  onCancelGoalEdit: () => void;
  onContinueGoal: () => void;
  onCancelGoal: () => void;
  onEditValueChange: (value: string) => void;
  disabled: boolean;
}

export function GoalPanel({
  goalSnapshot,
  goalDetailsOpen,
  goalEditActive,
  goalEditValue,
  onToggleDetails,
  onStartGoalEdit,
  onSaveGoalEdit,
  onCancelGoalEdit,
  onContinueGoal,
  onCancelGoal,
  onEditValueChange,
  disabled,
}: GoalPanelProps) {
  const { t } = useTranslation();
  const goalProgress = getGoalProgress(goalSnapshot);

  return (
    <div className="grid gap-2">
      <button
        type="button"
        onClick={onToggleDetails}
        className="inline-flex max-w-full items-center gap-1.5 justify-self-start rounded-lg bg-primary/10 px-2.5 py-1 text-left text-xs font-medium text-primary transition-colors hover:bg-primary/15"
        title={goalSnapshot.goal.objective}
        aria-label="Active research goal"
        aria-expanded={goalDetailsOpen}
      >
        <Target className="h-3 w-3 shrink-0" />
        <span className="shrink-0">{t("agent.goal")}</span>
        <span className="truncate text-muted-foreground">
          {goalSnapshot.goal.ui_summary || goalSnapshot.goal.objective}
        </span>
        {goalProgress.metLabel && (
          <span className="shrink-0 font-mono text-[11px] text-emerald-600 dark:text-emerald-400">
            {goalProgress.metLabel}
          </span>
        )}
        {goalProgress.evidenceTotal > 0 && (
          <span
            className="shrink-0 rounded bg-background px-1 font-mono text-[10px] text-primary"
            title="Evidence collected toward this research goal"
          >
            {goalProgress.evidenceTotal} evidence
          </span>
        )}
        <ChevronDown
          className={[
            "h-3 w-3 shrink-0 transition-transform",
            goalDetailsOpen ? "rotate-180" : "",
          ].join(" ")}
          aria-hidden="true"
        />
      </button>
      {goalDetailsOpen && (
        <div className="grid gap-3 rounded-xl border border-primary/20 bg-background/95 p-3 text-xs shadow-sm">
          {goalEditActive ? (
            <div className="grid gap-2">
              <textarea
                value={goalEditValue}
                onChange={(event) => onEditValueChange(event.target.value)}
                rows={3}
                className="w-full rounded-lg border bg-background px-3 py-2 text-xs leading-relaxed text-foreground outline-none focus:ring-2 focus:ring-primary/30"
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={onCancelGoalEdit}
                  className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
                >
                  <X className="h-3 w-3" />
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={onSaveGoalEdit}
                  disabled={!goalEditValue.trim()}
                  className="inline-flex items-center gap-1 rounded-lg bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground transition-opacity disabled:opacity-40"
                >
                  <Check className="h-3 w-3" />
                  Save
                </button>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border bg-muted/20 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
              {goalSnapshot.goal.objective}
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border bg-muted/20 p-2.5">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Criteria
              </div>
              <div className="mt-1 font-mono text-base font-semibold text-foreground">
                {goalProgress.label || "0/0"}
              </div>
            </div>
            <div className="rounded-lg border bg-muted/20 p-2.5">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Evidence
              </div>
              <div className="mt-1 font-mono text-base font-semibold text-foreground">
                {goalProgress.evidenceTotal}
              </div>
            </div>
          </div>
          <div className="grid gap-1.5">
            {goalSnapshot.criteria.map((criterion, index) => {
              const evidenceCount = criterionEvidenceCount(goalSnapshot, criterion.criterion_id);
              const displayStatus =
                criterionCovered(goalSnapshot, criterion) && !isCriterionStatusMet(criterion.status)
                  ? "covered"
                  : statusLabel(criterion.status);
              return (
                <div
                  key={criterion.criterion_id}
                  className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] items-start gap-2 rounded-lg border bg-muted/20 p-2"
                >
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-[10px] text-muted-foreground">
                    {criterionIndexLabel(index)}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-foreground">
                      {criterion.text}
                    </span>
                    <span className="block text-[11px] text-muted-foreground">{displayStatus}</span>
                  </span>
                  <span className="rounded-full border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {evidenceCount} ev
                  </span>
                </div>
              );
            })}
          </div>
          {goalSnapshot.evidence.length > 0 && (
            <div className="grid gap-1.5 border-t pt-2">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Recent Evidence
              </div>
              {latestGoalEvidence(goalSnapshot).map((item) => (
                <div key={item.evidence_id} className="rounded-lg bg-muted/20 px-2 py-1.5">
                  <div className="mb-0.5 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                    <span className="truncate">{item.source_provider || "evidence"}</span>
                    <span>{statusLabel(item.verification_status)}</span>
                  </div>
                  <div className="line-clamp-2 text-[11px] leading-relaxed text-foreground">
                    {item.text}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div className="flex flex-wrap justify-end gap-2 border-t pt-2">
            <button
              type="button"
              onClick={onContinueGoal}
              disabled={disabled}
              className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
            >
              <Play className="h-3 w-3" />
              Continue
            </button>
            <button
              type="button"
              onClick={onStartGoalEdit}
              disabled={goalEditActive}
              className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
            >
              <Pencil className="h-3 w-3" />
              Edit
            </button>
            <button
              type="button"
              onClick={onCancelGoal}
              className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-destructive/40 hover:text-destructive"
            >
              <X className="h-3 w-3" />
              Cancel Goal
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
