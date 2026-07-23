import type { GoalSnapshot } from "@/lib/api";

export function isCriterionStatusMet(status: string): boolean {
  return !["", "pending", "open", "unsatisfied"].includes(status.toLowerCase());
}

export function statusLabel(status: string): string {
  return status.replace(/_/g, " ");
}

export function isTerminalGoalStatus(status: string): boolean {
  return ["complete", "cancelled", "blocked", "superseded", "usage_limited"].includes(status);
}

export function criterionIndexLabel(index: number): string {
  return String(index + 1);
}

export function criterionEvidenceCount(snapshot: GoalSnapshot, criterionId: string): number {
  return snapshot.evidence.filter((item) => item.criterion_id === criterionId).length;
}

export function criterionCovered(
  snapshot: GoalSnapshot,
  criterion: GoalSnapshot["criteria"][number],
): boolean {
  return (
    isCriterionStatusMet(criterion.status) ||
    criterionEvidenceCount(snapshot, criterion.criterion_id) > 0
  );
}

export function latestGoalEvidence(snapshot: GoalSnapshot) {
  return [...snapshot.evidence]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 2);
}

export type GoalProgress = {
  met: number;
  total: number;
  label: string;
  metLabel: string;
  evidenceTotal: number;
};

export function getGoalProgress(snapshot: GoalSnapshot | null): GoalProgress {
  const total = snapshot?.criteria.length ?? 0;
  const met = snapshot?.criteria.filter((item) => criterionCovered(snapshot, item)).length ?? 0;
  const evidenceTotal = snapshot?.evidence_count ?? 0;
  return {
    met,
    total,
    label: total > 0 ? `${met}/${total}` : "",
    metLabel: total > 0 ? `${met}/${total} met` : "",
    evidenceTotal,
  };
}

export function goalKickoffPrompt(objective: string): string {
  return [
    "Start working on this research goal now.",
    "Keep it research-only, use available tools when evidence is needed, add concrete evidence to the goal ledger, and keep going until the goal is complete, blocked, waiting for user input, or budget-limited.",
    "",
    `Goal: ${objective}`,
  ].join("\n");
}

export function goalContinuePrompt(snapshot: GoalSnapshot): string {
  const openCriteria = snapshot.criteria
    .filter((item) => item.required && !criterionCovered(snapshot, item))
    .map((item) => `- ${item.text}`)
    .join("\n");
  return [
    "Continue the active research goal.",
    "Use real available tools as needed, add evidence to the goal ledger, and only stop when the goal is complete, blocked, waiting for user input, or budget-limited.",
    "",
    `Goal: ${snapshot.goal.objective}`,
    openCriteria
      ? `Open criteria:\n${openCriteria}`
      : "All criteria appear covered; audit the ledger and update the goal status if completion is justified.",
  ].join("\n");
}
