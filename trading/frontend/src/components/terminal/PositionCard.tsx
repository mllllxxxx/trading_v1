import { useState } from "react";
import { Activity, ChevronDown, ChevronUp, Info, X } from "lucide-react";
import { cn, fmtPx, fmtTime, useFlashClass } from "@/components/terminal/primitives";

const CONFLUENCE_MAX = 8;

export type PositionMarketContext = {
  candidate_direction?: string;
  confluence_score?: number;
  regime?: string;
  data_quality?: string;
  data_source?: string;
  data_age_s?: number;
  spread_state?: string | null;
  funding_state?: string | null;
  timeframe?: string;
  tf?: string;
  interval?: string;
  model?: string;
  [key: string]: unknown;
};

export type PositionDecisionContext = {
  thesis?: string;
  reasoning_summary?: string;
  confidence?: number | string;
  playbook_id?: string;
  rule_citations?: string[];
  profile_compliance_score?: number | string | null;
  profile_compliance_summary?: string | null;
  profile_compliance_flags?: string[];
  model?: string;
  [key: string]: unknown;
};

export type PositionProtectiveOrder = {
  algoId?: string | number | null;
  ordType?: string | null;
  side?: string | null;
  posSide?: string | null;
  sz?: string | number | null;
  tpTriggerPx?: string | number | null;
  slTriggerPx?: string | number | null;
  state?: string | null;
  [key: string]: unknown;
};

export type PositionOrderInfo = {
  status?: string;
  broker_order_id?: string | null;
  source?: string;
  protective_order_count?: number;
  raw?: Record<string, unknown>;
  [key: string]: unknown;
};

export type PositionRoutingExperiment = {
  experiment_id?: string;
  approval_id?: string;
  candidate_fingerprint?: string;
  v1_score?: number;
  v1_zone?: string;
  v2_score?: number;
  v2_zone?: string;
  allocation_bucket?: number;
  allocation_rate?: number;
  risk_multiplier?: number;
  [key: string]: unknown;
};

export type Position = {
  symbol: string;
  side: string;
  entry: number;
  stop_loss: number;
  take_profit: number;
  position_size: number;
  rr_ratio: number;
  confluence_score: number;
  regime: string;
  opened_at: string;
  timeframe?: string;
  entry_type?: string;
  position_id?: string;
  team_id?: string | null;
  team_name?: string | null;
  strategy_id?: string | null;
  strategy_name?: string | null;
  team_capital_usd?: number | string | null;
  target_risk_pct_equity?: number | string | null;
  preferred_playbook_ids?: string[] | null;
  required_soft_policy_ids?: string[] | null;
  entry_style?: string | null;
  avoid_conditions?: string[] | null;
  llm_guidance?: string | null;
  risk_personality?: string | null;
  profile_compliance_score?: number | string | null;
  profile_compliance_summary?: string | null;
  profile_compliance_flags?: string[];
  source_signal_id?: string;
  decision_id?: string;
  open_reason?: string;
  market_context?: PositionMarketContext;
  decision_context?: PositionDecisionContext;
  source?: string;
  status?: string;
  sync_status?: string;
  broker_sync_at?: string;
  mode?: string;
  instId?: string;
  ccxt_symbol?: string;
  mark_price?: number;
  unrealized_pnl?: number;
  notional?: number;
  leverage?: number;
  margin_mode?: string;
  contracts?: number;
  contract_size?: number;
  orders?: PositionOrderInfo;
  protective_orders?: PositionProtectiveOrder[];
  routing_experiment?: PositionRoutingExperiment | null;
};

type ConfidenceMetric = {
  score: number;
  source: "confidence" | "confluence";
};

export function PositionCard({
  p,
  mark,
  sequenceNumber,
  sequenceTotal,
}: {
  p: Position;
  mark: number | null;
  sequenceNumber?: number;
  sequenceTotal?: number;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const isLong = p.side === "buy";
  const exchangeMark = numericValue(p.mark_price);
  const px = mark ?? exchangeMark ?? p.entry;
  const hasMark = mark !== null || exchangeMark !== null;
  const markSource = mark !== null ? "live" : exchangeMark !== null ? "exchange" : "no tick";
  const computedPnlUsd = (isLong ? px - p.entry : p.entry - px) * p.position_size;
  const exchangePnl = numericValue(p.unrealized_pnl);
  const pnlUsd = exchangePnl ?? computedPnlUsd;
  const pnlPct = isLong
    ? ((px - p.entry) / p.entry) * 100
    : ((p.entry - px) / p.entry) * 100;
  const positive = pnlUsd >= 0;
  const flashCls = useFlashClass(pnlUsd);
  const timeframe = positionTimeframe(p);
  const confidence = confidenceMetric(p);
  const duration = formatOpenDuration(p.opened_at);
  const sizeText = formatPositionSize(p);
  const leverage = formatLeverage(p.leverage);
  const statusLabel = p.status || p.sync_status || (positive ? "gain" : "loss");
  const modelLabel = stringValue(p.decision_context?.model || p.market_context?.model || p.source);

  return (
    <div className={cn(
      "group relative flex flex-col overflow-hidden rounded-lg border border-ttcc-border-subtle bg-ttcc-surface tt-card-hover transition-colors hover:border-ttcc-border hover:shadow-tt-md",
      isLong ? "tt-hero-gradient-green" : "tt-hero-gradient-red"
    )}>
      <div className="flex items-start justify-between gap-2 border-b border-ttcc-border-subtle/60 bg-ttcc-surface-2/50 px-4 py-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            {sequenceNumber ? (
              <span
                className="inline-flex shrink-0 rounded-md border border-ttcc-border-subtle bg-ttcc-bg px-1.5 py-0.5 font-mono text-[10px] font-bold leading-none text-ttcc-accent tabular"
                title={`Position ${sequenceNumber}${sequenceTotal ? ` of ${sequenceTotal}` : ""}`}
              >
                #{sequenceNumber}{sequenceTotal ? `/${sequenceTotal}` : ""}
              </span>
            ) : null}
            <span className="truncate font-mono text-[14px] font-bold leading-none tracking-tight text-ttcc-text">
              {p.symbol.replace("-USDT", "")}
            </span>
            <SideBadge side={p.side} />
            <TeamBadge teamId={p.team_id} teamName={p.team_name} />
          </div>
          <div className={cn(
            "mt-1 font-mono text-[11px] font-bold uppercase tracking-wider",
            isLong ? "text-ttcc-green" : "text-ttcc-red"
          )}>
            {isLong ? "buy" : "sell"}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <span className={cn(
            "hidden rounded-md border px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider sm:inline-flex",
            positive
              ? "border-ttcc-green/40 bg-ttcc-green/10 text-ttcc-green"
              : "border-ttcc-red/40 bg-ttcc-red/10 text-ttcc-red"
          )}>
            {statusLabel}
          </span>
          <button
            type="button"
            onClick={() => setDetailsOpen((open) => !open)}
            className="inline-flex items-center gap-1 rounded-lg border border-ttcc-border-subtle bg-ttcc-surface px-1.5 py-1 text-[10px] font-bold uppercase tracking-wider text-ttcc-text-secondary transition-colors hover:border-ttcc-accent/50 hover:text-ttcc-text tt-focus"
            aria-expanded={detailsOpen}
          >
            <Info className="h-3 w-3" />
            <span>Details</span>
            {detailsOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
          <button
            type="button"
            aria-label="Close position"
            title="Close position"
            className="rounded-lg border border-ttcc-border-subtle bg-ttcc-surface p-1 text-ttcc-text-secondary opacity-70 transition-colors hover:border-ttcc-red/50 hover:bg-ttcc-red/15 hover:text-ttcc-red hover:opacity-100 tt-glow-red"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      </div>

      <div className={cn("px-3 py-2", flashCls)}>
        <div className="grid gap-2">
          <div className="grid gap-2 md:grid-cols-[minmax(0,1.05fr)_minmax(180px,0.95fr)]">
            <ProfitMetric
              pnlUsd={pnlUsd}
              pnlPct={pnlPct}
              positive={positive}
            />
            <ConfidenceBar confidence={confidence} />
          </div>

          <div className="grid grid-cols-3 gap-1.5">
            <PriceMetric label="Entry" value={fmtPx(p.entry)} />
            <PriceMetric label="TP" value={formatOptionalPx(p.take_profit)} tone="bull" />
            <PriceMetric label="SL" value={formatOptionalPx(p.stop_loss)} tone="bear" />
          </div>

          <div className="grid grid-cols-2 gap-1.5">
            <MiniMetric label="Time" value={duration} />
            <MiniMetric label="Timeframe" value={timeframe} />
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1 border-t border-ttcc-border-subtle/60 px-4 py-2 text-[10px]">
        <MetaChip label="size" value={sizeText} />
        <MetaChip label="lev" value={leverage} />
        <MetaChip label="R/R" value={formatRr(p.rr_ratio)} />
        <MetaChip label="mark" value={hasMark ? `${fmtPx(px)} ${markSource}` : markSource} />
        <MetaChip label="team" value={p.team_name || p.strategy_name} />
        <MetaChip label="AI" value={modelLabel} />
        <span className="ml-auto font-mono text-[9px] text-ttcc-text-muted tabular">
          {fmtTime(p.opened_at)}
        </span>
      </div>

      {detailsOpen ? (
        <div className="border-t border-ttcc-border-subtle/60 bg-ttcc-surface/40 tt-glass">
          <div className="flex flex-wrap items-center gap-1 px-4 py-2 text-[10px]">
            <MetaChip label="mark_source" value={markSource} />
            <MetaChip label="mark_price" value={hasMark ? fmtPx(px) : ""} />
            <MetaChip label="notional" value={formatUsdNumber(p.notional)} />
            <MetaChip label="opened" value={fmtTime(p.opened_at)} />
          </div>
          <RationaleSection p={p} />
          <ExchangeSection p={p} />
        </div>
      ) : null}
    </div>
  );
}

function ProfitMetric({
  pnlUsd,
  pnlPct,
  positive,
}: {
  pnlUsd: number;
  pnlPct: number;
  positive: boolean;
}) {
  const toneClass = positive ? "text-ttcc-green" : "text-ttcc-red";
  return (
    <div className="min-w-0 rounded-md border border-ttcc-border-subtle/70 bg-ttcc-surface-2/30 px-2.5 py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-muted">P&L</div>
        <div className={cn("rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-bold leading-none tabular", positive ? "border-ttcc-green/40 bg-ttcc-green/10 text-ttcc-green" : "border-ttcc-red/40 bg-ttcc-red/10 text-ttcc-red")}>
          {formatSignedPct(pnlPct)}
        </div>
      </div>
      <div className={cn("mt-1 truncate font-mono text-[22px] font-bold leading-tight tabular", toneClass)} title={formatSignedUsd(pnlUsd)}>
        {formatSignedUsd(pnlUsd)}
      </div>
    </div>
  );
}

function PriceMetric({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "bull" | "bear";
}) {
  const toneClass =
    tone === "bull" ? "text-ttcc-green"
    : tone === "bear" ? "text-ttcc-red"
    : "text-ttcc-text";
  return (
    <div className="min-w-0 rounded-md border border-ttcc-border-subtle/70 bg-ttcc-surface-2/30 px-2 py-1.5">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-ttcc-text-muted">{label}</div>
      <div className={cn("mt-0.5 truncate font-mono text-[12px] font-semibold tabular", toneClass)} title={value}>
        {value}
      </div>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md border border-ttcc-border-subtle/50 bg-ttcc-surface-2/30 px-2 py-1">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-ttcc-text-muted">{label}</div>
      <div className="mt-0.5 truncate font-mono text-[10px] font-semibold text-ttcc-text-secondary tabular" title={value}>
        {value}
      </div>
    </div>
  );
}

function ConfidenceBar({ confidence }: { confidence: ConfidenceMetric }) {
  const tone = confidenceTone(confidence.score);
  return (
    <div
      role="meter"
      aria-label={`Confidence ${confidence.score} of 100`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={confidence.score}
      className={cn("min-w-0 rounded-md border bg-ttcc-surface-2/30 px-2.5 py-2", tone.border)}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-muted">Conf.</div>
        <div className={cn("font-mono text-[13px] font-bold leading-none tabular", tone.text)}>
          {confidence.score}<span className="text-[9px] text-ttcc-text-muted">/100</span>
        </div>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded bg-ttcc-bg">
        <div
          className={cn("h-full rounded transition-[width] duration-300", tone.bar)}
          style={{ width: `${confidence.score}%` }}
        />
      </div>
    </div>
  );
}

function ExchangeSection({ p }: { p: Position }) {
  const protectiveOrders = Array.isArray(p.protective_orders) ? p.protective_orders : [];
  const orders = p.orders && typeof p.orders === "object" ? p.orders : undefined;
  const orderIds = compactOrderIds(orders, protectiveOrders);
  const hasContent = Boolean(
    p.source ||
    p.status ||
    p.sync_status ||
    p.broker_sync_at ||
    p.mode ||
    p.instId ||
    p.ccxt_symbol ||
    numericValue(p.mark_price) !== null ||
    numericValue(p.unrealized_pnl) !== null ||
    numericValue(p.leverage) !== null ||
    p.margin_mode ||
    numericValue(p.contracts) !== null ||
    protectiveOrders.length ||
    orderIds.length ||
    orders?.status
  );

  if (!hasContent) {
    return null;
  }

  return (
    <div className="border-t border-ttcc-border-subtle/60 px-2.5 py-2 text-[10px]">
      <div className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-muted">
        Exchange sync
      </div>
      <div className="flex flex-wrap gap-1">
        <MetaChip label="status" value={p.status || p.sync_status} />
        <MetaChip label="source" value={p.source} />
        <MetaChip label="mode" value={p.mode} />
        <MetaChip label="inst" value={p.instId || p.ccxt_symbol} />
        <MetaChip label="sync" value={p.broker_sync_at ? fmtTime(p.broker_sync_at) : ""} />
        <MetaChip label="mark" value={formatNumber(p.mark_price)} />
        <MetaChip label="upl" value={formatSignedNumber(p.unrealized_pnl)} />
        <MetaChip label="lev" value={formatLeverage(p.leverage)} />
        <MetaChip label="margin" value={p.margin_mode} />
        <MetaChip label="contracts" value={formatNumber(p.contracts)} />
        <MetaChip label="orders" value={orderIds.length ? orderIds.join(", ") : orders?.status} />
        <MetaChip label="protect" value={protectiveOrders.length ? String(protectiveOrders.length) : orders?.protective_order_count} />
      </div>
    </div>
  );
}

function RationaleSection({ p }: { p: Position }) {
  const reason = stringValue(p.open_reason);
  const decision = p.decision_context;
  const market = p.market_context;
  const thesis = stringValue(decision?.thesis || decision?.reasoning_summary);
  const ruleCitations = Array.isArray(decision?.rule_citations)
    ? decision.rule_citations.filter(Boolean).slice(0, 3)
    : [];
  const confidence = formatConfidence(p);
  const routing = p.routing_experiment;
  const hasContent = Boolean(
    reason ||
    thesis ||
    confidence ||
    decision?.playbook_id ||
    p.source_signal_id ||
    p.decision_id ||
    market?.data_quality ||
    market?.data_source ||
    market?.data_age_s ||
    market?.candidate_direction ||
    market?.spread_state ||
    market?.funding_state ||
    p.team_id ||
    p.team_name ||
    p.strategy_id ||
    p.strategy_name ||
    p.entry_style ||
    p.llm_guidance ||
    routing?.approval_id ||
    ruleCitations.length
  );

  if (!hasContent) {
    return null;
  }

  return (
    <div className="border-t border-ttcc-border-subtle/60 px-2.5 py-2 text-[10px]">
      <div className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-ttcc-text-muted">
        Open rationale
      </div>
      {reason ? (
        <p className="line-clamp-2 break-words font-medium leading-snug text-ttcc-text" title={reason}>
          {reason}
        </p>
      ) : null}
      {thesis && thesis !== reason ? (
        <p className="mt-1 line-clamp-2 break-words leading-snug text-ttcc-text-secondary" title={thesis}>
          {thesis}
        </p>
      ) : null}
      <div className="mt-1.5 flex flex-wrap gap-1">
        <MetaChip label="data" value={market?.data_quality} />
        <MetaChip label="age" value={fmtAgeSeconds(market?.data_age_s)} />
        <MetaChip label="src" value={market?.data_source} />
        <MetaChip label="dir" value={market?.candidate_direction} />
        <MetaChip label="spread" value={market?.spread_state} />
        <MetaChip label="funding" value={market?.funding_state} />
        <MetaChip label="conf" value={confidence} />
        <MetaChip
          label="profile"
          value={formatComplianceScore(
            decision?.profile_compliance_score ?? p.profile_compliance_score,
          )}
        />
        <MetaChip label="playbook" value={decision?.playbook_id} />
        <MetaChip label="signal" value={compactId(p.source_signal_id)} />
        <MetaChip label="decision" value={compactId(p.decision_id)} />
        <MetaChip label="team" value={p.team_name || p.team_id} />
        <MetaChip label="strategy" value={p.strategy_name || p.strategy_id} />
        <MetaChip label="skill" value={p.preferred_playbook_ids?.[0]} />
        <MetaChip label="entry" value={p.entry_style} />
        <MetaChip label="avoid" value={p.avoid_conditions?.join(", ")} />
        <MetaChip label="team_cap" value={formatUsdNumber(p.team_capital_usd)} />
        <MetaChip label="target_risk" value={formatRiskPct(p.target_risk_pct_equity)} />
        <MetaChip
          label="route"
          value={routing?.experiment_id ? "V2 canary" : undefined}
        />
        <MetaChip
          label="v1"
          value={routing?.v1_zone ? `${routing.v1_zone} ${formatNumber(routing.v1_score)}` : undefined}
        />
        <MetaChip
          label="v2"
          value={routing?.v2_zone ? `${routing.v2_zone} ${formatNumber(routing.v2_score)}` : undefined}
        />
        <MetaChip label="bucket" value={formatNumber(routing?.allocation_bucket)} />
        <MetaChip
          label="canary_risk"
          value={routing?.risk_multiplier !== undefined ? `x${routing.risk_multiplier}` : undefined}
        />
        <MetaChip label="approval" value={compactId(routing?.approval_id)} />
        {ruleCitations.map((rule) => (
          <MetaChip key={rule} label="rule" value={compactId(rule)} />
        ))}
      </div>
    </div>
  );
}

function MetaChip({ label, value }: { label: string; value: unknown }) {
  const text = stringValue(value);
  if (!text) {
    return null;
  }
  return (
    <span className="inline-flex max-w-full items-center gap-1 rounded-md border border-ttcc-border-subtle/50 bg-ttcc-surface-2/40 px-1.5 py-0.5 leading-none text-ttcc-text-secondary">
      <span className="shrink-0 font-semibold uppercase text-ttcc-text-muted">{label}</span>
      <span className="min-w-0 truncate font-mono text-ttcc-text" title={text}>{text}</span>
    </span>
  );
}

function stringValue(value: unknown): string {
  if (value == null) {
    return "";
  }
  const text = String(value).trim();
  return text === "null" || text === "undefined" ? "" : text;
}

function compactId(value: unknown): string {
  const text = stringValue(value);
  if (text.length <= 18) {
    return text;
  }
  return `${text.slice(0, 8)}...${text.slice(-6)}`;
}

function fmtAgeSeconds(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) {
    return "";
  }
  if (n < 60) {
    return `${Math.round(n)}s`;
  }
  if (n < 3600) {
    return `${Math.round(n / 60)}m`;
  }
  return `${(n / 3600).toFixed(1)}h`;
}

function numericValue(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function positionTimeframe(p: Position): string {
  return stringValue(
    p.timeframe ||
    p.market_context?.timeframe ||
    p.market_context?.tf ||
    p.market_context?.interval
  ) || "--";
}

function confidenceMetric(p: Position): ConfidenceMetric {
  const parsed = parseConfidenceScore(p.decision_context?.confidence);
  if (parsed !== null) {
    return { score: parsed, source: "confidence" };
  }

  const confluence = Math.max(0, Math.min(CONFLUENCE_MAX, Number(p.confluence_score) || 0));
  return {
    score: clampConfidence((confluence / CONFLUENCE_MAX) * 100),
    source: "confluence",
  };
}

function parseConfidenceScore(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return clampConfidence(value <= 1 ? value * 100 : value);
  }

  const text = stringValue(value).replace("%", "").trim();
  if (!text) {
    return null;
  }

  const ratio = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*\/\s*([0-9]+(?:\.[0-9]+)?)$/);
  if (ratio) {
    const numerator = Number(ratio[1]);
    const denominator = Number(ratio[2]);
    if (Number.isFinite(numerator) && Number.isFinite(denominator) && denominator > 0) {
      return clampConfidence((numerator / denominator) * 100);
    }
  }

  const n = Number(text);
  if (!Number.isFinite(n)) {
    return null;
  }
  return clampConfidence(n <= 1 ? n * 100 : n);
}

function clampConfidence(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function confidenceTone(score: number): { border: string; text: string; bar: string } {
  if (score >= 70) {
    return {
      border: "border-ttcc-green/40",
      text: "text-ttcc-green",
      bar: "bg-ttcc-green",
    };
  }
  if (score >= 45) {
    return {
      border: "border-ttcc-yellow/40",
      text: "text-ttcc-yellow",
      bar: "bg-ttcc-yellow",
    };
  }
  return {
    border: "border-ttcc-red/40",
    text: "text-ttcc-red",
    bar: "bg-ttcc-red",
  };
}

function formatConfidence(p: Position): string {
  return `${confidenceMetric(p).score}/100`;
}

function formatOpenDuration(openedAt: string): string {
  const ts = Date.parse(openedAt);
  if (!Number.isFinite(ts)) {
    return "--";
  }
  const minutes = Math.max(0, Math.floor((Date.now() - ts) / 60_000));
  if (minutes < 1) {
    return "<1M";
  }
  if (minutes < 60) {
    return `${minutes}M`;
  }
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  if (hours < 24) {
    return `${hours}H ${remMinutes}M`;
  }
  const days = Math.floor(hours / 24);
  return `${days}D ${hours % 24}H`;
}

function formatPositionSize(p: Position): string {
  const contracts = numericValue(p.contracts);
  if (contracts !== null && contracts > 0) {
    return `${formatNumber(contracts)} ctr`;
  }
  return formatNumber(p.position_size) || "--";
}

function formatNumber(value: unknown): string {
  const n = numericValue(value);
  if (n === null) {
    return "";
  }
  if (Math.abs(n) >= 1000) {
    return n.toFixed(2);
  }
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function formatSignedNumber(value: unknown): string {
  const n = numericValue(value);
  if (n === null) {
    return "";
  }
  return `${n >= 0 ? "+" : ""}${formatNumber(n)}`;
}

function formatSignedUsd(value: unknown): string {
  const n = numericValue(value);
  if (n === null) {
    return "--";
  }
  return n >= 0 ? `+$${n.toFixed(2)}` : `$-${Math.abs(n).toFixed(2)}`;
}

function formatUsdNumber(value: unknown): string {
  const n = numericValue(value);
  if (n === null) {
    return "";
  }
  return `$${n.toFixed(2)}`;
}

function formatSignedPct(value: unknown): string {
  const n = numericValue(value);
  if (n === null) {
    return "--";
  }
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function formatOptionalPx(value: unknown): string {
  const n = numericValue(value);
  if (n === null || n <= 0) {
    return "--";
  }
  return fmtPx(n);
}

function formatLeverage(value: unknown): string {
  const n = numericValue(value);
  if (n === null || n <= 0) {
    return "";
  }
  return `${formatNumber(n)}x`;
}

function formatRr(value: unknown): string {
  const n = numericValue(value);
  if (n === null || n <= 0) {
    return "";
  }
  return `1:${n.toFixed(2)}`;
}

function formatRiskPct(value: unknown): string {
  const n = numericValue(value);
  if (n === null || n <= 0) {
    return "";
  }
  return `${(n * 100).toFixed(1)}%`;
}

function formatComplianceScore(value: unknown): string {
  const n = numericValue(value);
  if (n === null) {
    return "";
  }
  return n.toFixed(2);
}

function compactOrderIds(
  orders: PositionOrderInfo | undefined,
  protectiveOrders: PositionProtectiveOrder[],
): string[] {
  const ids: string[] = [];
  const add = (value: unknown) => {
    const text = stringValue(value);
    if (text && !ids.includes(text)) {
      ids.push(compactId(text));
    }
  };
  add(orders?.broker_order_id);
  add(orders?.entry_id);
  add(orders?.tp_id);
  add(orders?.sl_id);
  const raw = orders?.raw;
  if (raw && typeof raw === "object") {
    const response = raw.response as Record<string, unknown> | undefined;
    add(response?.algo_order_id);
    add(response?.algoId);
    add(response?.ordId);
  }
  for (const order of protectiveOrders.slice(0, 3)) {
    add(order.algoId);
  }
  return ids.slice(0, 4);
}

export function SideBadge({ side }: { side: string }) {
  const isLong = side === "buy";
  return (
    <span className={cn(
      "inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase leading-none tracking-wider",
      isLong
        ? "text-ttcc-green bg-ttcc-green/10 border-ttcc-green/40"
        : "text-ttcc-red bg-ttcc-red/10 border-ttcc-red/40"
    )}>
      {isLong ? "LONG" : "SHORT"}
    </span>
  );
}

export function TeamBadge({
  teamId,
  teamName,
}: {
  teamId?: string | null;
  teamName?: string | null;
}) {
  const label = stringValue(teamName || teamId);
  if (!label) {
    return null;
  }
  return (
    <span className={cn(
      "inline-flex max-w-[112px] items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase leading-none tracking-wider",
      teamToneClass(teamId)
    )}>
      <span className="truncate" title={label}>{label}</span>
    </span>
  );
}

function teamToneClass(teamId: unknown): string {
  const id = stringValue(teamId);
  if (id === "momentum") {
    return "border-blue-400/40 bg-blue-400/10 text-blue-300";
  }
  if (id === "mean_reversion") {
    return "border-ttcc-yellow/40 bg-ttcc-yellow/10 text-ttcc-yellow";
  }
  if (id === "volatility_breakout") {
    return "border-ttcc-red/40 bg-ttcc-red/10 text-ttcc-red";
  }
  return "border-ttcc-green/40 bg-ttcc-green/10 text-ttcc-green";
}

export function ConfluenceBadge({ score, max = CONFLUENCE_MAX }: { score: number; max?: number }) {
  const s = Math.max(0, Math.min(max, Math.round(score)));
  const tone =
    s >= 6 ? "text-ttcc-green bg-ttcc-green/10 border-ttcc-green/40"
    : s >= 4 ? "text-ttcc-yellow bg-ttcc-yellow/10 border-ttcc-yellow/40"
    : "text-ttcc-red bg-ttcc-red/10 border-ttcc-red/40";
  return (
    <span className={cn(
      "inline-flex items-center gap-0.5 rounded border px-1.5 py-0.5 font-mono text-[11px] font-medium leading-none tabular",
      tone
    )}>
      <span>+{s}</span>
      <span className="text-ttcc-text-muted opacity-60">/{max}</span>
    </span>
  );
}

export function RrBadge({ rr }: { rr: number }) {
  const good = rr >= 2;
  return (
    <span className={cn(
      "inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[11px] font-medium leading-none tabular",
      good
        ? "text-ttcc-green bg-ttcc-green/10 border-ttcc-green/40"
        : "text-ttcc-text-secondary bg-ttcc-surface-2 border-ttcc-border"
    )}>
      1:{rr?.toFixed(2)}
    </span>
  );
}

export function EmptyPositions() {
  return (
    <div className="tt-hero-gradient flex flex-col items-center justify-center rounded-lg border border-ttcc-border-subtle bg-ttcc-surface/30 py-12">
      <Activity className="mb-1 h-10 w-10 text-ttcc-text-muted/40 transition-all duration-150 hover:tt-glow-accent" />
      <span className="text-ttcc-text-secondary text-[13px] font-medium">No open positions</span>
      <span className="text-ttcc-text-muted text-[11px]">scanner running - waiting for signal</span>
    </div>
  );
}
