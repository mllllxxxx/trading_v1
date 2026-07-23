/**
 * Canonical backend-facing API types.
 *
 * These mirror backend response shapes (currently `GET /api/trader/status`,
 * closed trades list, account state). They are gathered here so pages and
 * layout stop re-declaring near-identical copies.
 *
 * When the backend OpenAPI/schema is available, this file can be regenerated
 * with `openapi-typescript` or similar — the import surface stays the same.
 */
import type {
  Position,
  PositionDecisionContext,
  PositionMarketContext,
} from "@/components/terminal/PositionCard";
import type { BrainDecision } from "@/components/terminal/BrainLog";
import type { MiniTrade } from "@/components/terminal/MiniHistory";

export type { BrainDecision, MiniTrade };
export type { Position, PositionDecisionContext, PositionMarketContext };

// ============= Trader stats =============

export type Stats = {
  total_trades?: number;
  wins?: number;
  losses?: number;
  total_pnl_usd?: number;
  open_count?: number;
  max_drawdown_usd?: number;
  starting_capital?: number;
  current_capital?: number;
  winrate?: number;
  consecutive_losses?: number;
  daily_llm_cost?: {
    date: string;
    cost_usd: number;
    calls: number;
    cap_usd: number;
    remaining_usd: number;
    pct_of_cap: number;
    cap_reached: boolean;
    cap_reason?: string;
    call_cap?: number;
    remaining_calls?: number | null;
    hourly_calls?: number;
    hourly_call_cap?: number;
    remaining_hourly_calls?: number | null;
    budget_skips?: number;
    last_budget_skip?: {
      ts?: string;
      source?: string;
      reason?: string;
      behavior?: string;
      calls?: number;
      call_cap?: number;
      hourly_calls?: number;
      hourly_call_cap?: number;
    } | null;
    monthly_cost_usd: number;
    monthly_date: string;
  };
};

// ============= Account state =============

export type AccountState = {
  source?: string;
  mode?: string;
  risk_profile?: string;
  synced_at?: string;
  starting_capital_usd?: number;
  current_capital_usd?: number;
  total_pnl_usd?: number;
  unrealized_pnl_usd?: number;
  journal_realized_pnl_usd?: number;
  available_balance_usd?: number | null;
  margin_used_usd?: number | null;
  simulation_equity_cap_usd?: number | null;
  equity_cap_pnl_baseline_usd?: number | null;
  pre_cap_total_pnl_usd?: number | null;
  actual_current_capital_usd?: number | null;
  actual_available_balance_usd?: number | null;
  actual_total_pnl_usd?: number | null;
  errors?: string[];
};

// ============= Closed trade =============

export type ClosedTrade = {
  closed_at: string;
  symbol: string;
  side: string;
  entry: number;
  exit_price: number;
  position_size: number;
  pnl_usd: number;
  exit_reason: string;
  confluence_score: number;
  team_id?: string | null;
  team_name?: string | null;
  strategy_id?: string | null;
  strategy_name?: string | null;
  source_signal_id?: string;
  decision_id?: string;
  open_reason?: string;
  market_context?: PositionMarketContext;
  decision_context?: PositionDecisionContext;
};

// ============= Adaptive policy controller =============

export type AdaptivePolicyControllerStatus = {
  status?: string;
  mode?: string;
  revision?: number;
  active_zones?: {
    strong_min_score?: number;
    gray_min_score?: number;
  };
  effective_source?: string;
  last_action?: string | null;
  last_reason?: string | null;
  state_error?: string | null;
  strategy_coverage_failures?: Array<{
    strategy_id?: string;
    eligible_records?: number;
    minimum_records?: number;
  }>;
};

// ============= Shadow scoring =============

export type ShadowScoreReviewControllerStatus = {
  status?: string;
  revision?: number;
  operator_approved?: boolean;
  active_for_routing?: boolean;
  canary_enabled?: boolean;
  candidate?: {
    strong_min_score?: number | null;
    gray_min_score?: number | null;
    confirmations?: number;
    required_confirmations?: number;
  } | null;
  last_reason?: string | null;
};

export type ShadowScoreCanaryStatus = {
  status?: string;
  routing_enabled?: boolean;
  approval_id?: string | null;
  candidate_fingerprint?: string | null;
  candidate_thresholds?: {
    strong_min_score?: number;
    gray_min_score?: number;
  } | null;
  allocation_rate?: number;
  risk_multiplier?: number;
  last_reason?: string | null;
  rollback_metrics?: {
    closed_trades?: number;
    average_r_lower_bound?: number | null;
    profit_factor?: number | null;
    cumulative_r?: number;
  };
};

export type ShadowScoringExperimentStatus = {
  mode?: string;
  active_for_routing?: boolean;
  eligible_records?: number;
  score_coverage?: {
    valid?: number;
    total?: number;
    ratio?: number;
    exclusion_reasons?: Record<string, number>;
  };
  score_delta_v2_minus_v1?: {
    average?: number | null;
    average_absolute?: number | null;
  };
  zone_transitions?: Record<string, number>;
  threshold_calibration?: {
    status?: string;
    sample_reasons?: string[];
    candidate_thresholds?: {
      strong_min_score?: number;
      gray_min_score?: number;
      active_for_routing?: boolean;
    } | null;
    objective_comparison_vs_active_v1?: {
      validation_delta_v2_minus_v1?: number | null;
    } | null;
  };
  review_eligibility?: {
    status?: string;
    eligible?: boolean;
    blocking_reasons?: string[];
  };
  auto_apply?: boolean;
};

// ============= Sync status =============

export type SyncStatus = {
  status?: string;
  positions_on_exchange?: number;
  positions_in_journal?: number;
  missing_in_journal?: string[];
  missing_on_exchange?: string[];
  errors?: string[];
};

// ============= Trader status payload (GET /api/trader/status) =============

export type TraderStatusPayload = {
  error?: string;
  timestamp?: string;
  running?: boolean;
  started_at?: string | null;
  symbols?: string[];
  stats?: Stats;
  account_state?: AccountState;
  positions?: Position[];
  exchange_positions?: Position[];
  sync_status?: SyncStatus;
  closed_trades?: ClosedTrade[];
  decisions?: BrainDecision[];
  llm_decisions?: BrainDecision[];
  kill_switch_active?: boolean;
  trading_blocked?: boolean;
  trading_block_reason?: string;
  startup_sync_guard_active?: boolean;
  startup_sync_guard?: Record<string, unknown> | null;
  adaptive_policy_controller?: AdaptivePolicyControllerStatus;
  shadow_score_review_controller?: ShadowScoreReviewControllerStatus;
  shadow_score_canary?: ShadowScoreCanaryStatus;
  adaptive_evaluation?: {
    shadow_scoring_experiment_evaluation?: {
      continuous_conflict_v2?: ShadowScoringExperimentStatus;
    };
  };
};
