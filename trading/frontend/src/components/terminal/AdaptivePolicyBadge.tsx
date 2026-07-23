import { SlidersHorizontal } from "lucide-react";
import { cn } from "@/components/terminal/primitives";
import type {
  AdaptivePolicyControllerStatus,
  ShadowScoreCanaryStatus,
  ShadowScoreReviewControllerStatus,
  ShadowScoringExperimentStatus,
} from "@/types/api";

export function AdaptivePolicyBadge({
  controller,
  experiment,
  reviewController,
  canary,
}: {
  controller?: AdaptivePolicyControllerStatus;
  experiment?: ShadowScoringExperimentStatus;
  reviewController?: ShadowScoreReviewControllerStatus;
  canary?: ShadowScoreCanaryStatus;
}) {
  const strong = controller?.active_zones?.strong_min_score;
  const gray = controller?.active_zones?.gray_min_score;
  if (strong === undefined || gray === undefined) return null;
  const status = controller?.status || "baseline";
  const revision = controller?.revision ?? 0;
  const experimentRoutingError = experiment?.active_for_routing === true;
  const tone = controller?.state_error || status === "error" || experimentRoutingError
    ? "border-ttcc-red/50 text-ttcc-red"
    : status === "staged"
      ? "border-ttcc-yellow/50 text-ttcc-yellow"
      : status === "active" || revision > 0
        ? "border-ttcc-green/40 text-ttcc-green"
        : "border-ttcc-border text-ttcc-text-secondary";
  const coverageFailures = controller?.strategy_coverage_failures?.length ?? 0;
  const experimentValid = experiment?.score_coverage?.valid;
  const experimentTotal = experiment?.score_coverage?.total;
  const hasExperimentCoverage = experimentValid !== undefined && experimentTotal !== undefined;
  const scoreDelta = experiment?.score_delta_v2_minus_v1?.average;
  const readinessStatus = experiment?.review_eligibility?.status;
  const readinessBlockers = experiment?.review_eligibility?.blocking_reasons ?? [];
  const calibration = experiment?.threshold_calibration;
  const calibrationCandidate = calibration?.candidate_thresholds;
  const calibrationStrong = calibrationCandidate?.strong_min_score;
  const calibrationGray = calibrationCandidate?.gray_min_score;
  const hasCalibrationCandidate = calibrationStrong !== undefined
    && calibrationGray !== undefined;
  const calibrationValidationDelta = calibration
    ?.objective_comparison_vs_active_v1?.validation_delta_v2_minus_v1;
  const transitions = Object.entries(experiment?.zone_transitions ?? {})
    .map(([transition, count]) => `${transition}:${count}`)
    .join(", ");
  const title = [
    `Adaptive policy ${status}`,
    `effective ${strong}/${gray}, revision ${revision}`,
    controller?.effective_source ? `source ${controller.effective_source}` : "",
    controller?.last_action ? `action ${controller.last_action}` : "",
    controller?.last_reason ? `reason ${controller.last_reason}` : "",
    coverageFailures ? `${coverageFailures} strategy coverage gate(s) pending` : "",
    hasExperimentCoverage ? `V2 shadow coverage ${experimentValid}/${experimentTotal}` : "",
    calibration?.status ? `V2 calibration ${calibration.status}` : "",
    hasCalibrationCandidate ? `V2 candidate ${calibrationStrong}/${calibrationGray}` : "",
    calibrationValidationDelta !== undefined && calibrationValidationDelta !== null
      ? `V2 holdout objective delta ${calibrationValidationDelta}`
      : "",
    calibration?.sample_reasons?.length
      ? `V2 calibration blockers ${calibration.sample_reasons.join(",")}`
      : "",
    reviewController?.status
      ? `V2 review ${reviewController.status}`
      : "",
    reviewController?.candidate
      ? `V2 review confirmations ${reviewController.candidate.confirmations ?? 0}/${reviewController.candidate.required_confirmations ?? 0}`
      : "",
    reviewController?.operator_approved === false
      ? "V2 operator approved false"
      : "",
    reviewController?.active_for_routing === false
      ? "V2 active for routing false"
      : "",
    canary?.status ? `V2 canary ${canary.status}` : "",
    canary?.routing_enabled
      ? `V2 canary allocation ${(canary.allocation_rate ?? 0) * 100}%, risk x${canary.risk_multiplier ?? 0}`
      : "",
    canary?.candidate_thresholds
      ? `V2 canary zones ${canary.candidate_thresholds.strong_min_score ?? "--"}/${canary.candidate_thresholds.gray_min_score ?? "--"}`
      : "",
    canary?.candidate_fingerprint
      ? `V2 candidate fingerprint ${canary.candidate_fingerprint.slice(0, 12)}`
      : "",
    canary?.approval_id ? `V2 approval ${canary.approval_id.slice(0, 12)}` : "",
    canary?.rollback_metrics?.closed_trades !== undefined
      ? `V2 canary closes ${canary.rollback_metrics.closed_trades}, LCB ${canary.rollback_metrics.average_r_lower_bound ?? "--"}, PF ${canary.rollback_metrics.profit_factor ?? "--"}, cumulative R ${canary.rollback_metrics.cumulative_r ?? 0}`
      : "",
    canary?.last_reason ? `V2 canary reason ${canary.last_reason}` : "",
    readinessStatus ? `V2 readiness ${readinessStatus}` : "",
    readinessBlockers.length ? `V2 blockers ${readinessBlockers.join(",")}` : "",
    scoreDelta !== undefined && scoreDelta !== null ? `V2 score delta ${scoreDelta}` : "",
    transitions ? `V2 zone transitions ${transitions}` : "",
    experimentRoutingError ? "error V2 unexpectedly marked active for routing" : "",
    controller?.state_error ? `error ${controller.state_error}` : "",
  ].filter(Boolean).join(" | ");
  const ariaLabel = [
    `Adaptive policy strong ${strong}, gray ${gray}, revision ${revision}`,
    hasExperimentCoverage ? `V2 coverage ${experimentValid} of ${experimentTotal}` : "",
  ].filter(Boolean).join(", ");
  return (
    <span
      className={cn(
        "hidden h-5 shrink-0 items-center gap-1 rounded border px-1.5 font-mono text-[9px] font-semibold uppercase tabular md:inline-flex",
        tone
      )}
      title={title}
      aria-label={ariaLabel}
    >
      <SlidersHorizontal className="h-2.5 w-2.5" />
      <span>ADP {strong}/{gray} R{revision}</span>
      {canary?.routing_enabled ? (
        <span className="border-l border-current/30 pl-1 text-ttcc-yellow">V2 CANARY</span>
      ) : null}
      {hasExperimentCoverage ? (
        <span className="border-l border-current/30 pl-1">V2 {experimentValid}/{experimentTotal}</span>
      ) : null}
    </span>
  );
}
