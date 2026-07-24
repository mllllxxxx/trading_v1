import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Activity,
  BadgeCheck,
  BrainCircuit,
  ChartCandlestick,
  GitBranch,
  Globe2,
  Landmark,
  ListChecks,
  Loader2,
  Radar,
  RefreshCw,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
  Target,
  TriangleAlert,
  WalletCards,
  Workflow,
} from "lucide-react";
import {
  api,
  type BerkshireAnalystPod,
  type BerkshireLaneKey,
  type BerkshireResearchRequest,
  type BerkshireResearchRun,
  type BerkshireState,
  type BerkshireTone,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  DEFAULT_FORM,
  EmptyRun,
  MiniMetric,
  PanelHeader,
  StatusDot,
  StatusPill,
  TAB_LABELS,
  toneText,
  type DeskTab,
  type FormState,
} from "@/components/berkshire/berkshireHelpers";
import { LaneCard, LaneTabs } from "@/components/berkshire/LaneTabs";
import { SignalsPanel } from "@/components/berkshire/SignalGrid";
import { TicketComposer } from "@/components/berkshire/TicketComposer";

const POD_ICONS = [Landmark, ChartCandlestick, ShieldCheck, ScrollText];

export function BerkshireDesk() {
  const [state, setState] = useState<BerkshireState | null>(null);
  const [activeLane, setActiveLane] = useState<BerkshireLaneKey>("crypto");
  const [activeTab, setActiveTab] = useState<DeskTab>("overview");
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadState = useCallback(async (mode: "initial" | "refresh" = "refresh") => {
    if (mode === "initial") setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const next = await api.getBerkshireState();
      setState(next);
      setActiveLane((current) =>
        next.lanes.some((lane) => lane.key === current) ? current : next.lanes[0]?.key ?? "crypto",
      );
      setForm((prev) => ({ ...prev, symbol: prev.symbol || next.lanes[0]?.instruments[0] || "" }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load Berkshire state");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadState("initial");
  }, [loadState]);

  const lane = useMemo(() => {
    return state?.lanes.find((item) => item.key === activeLane) ?? null;
  }, [activeLane, state?.lanes]);

  const pipeline = state?.pipelines[activeLane] ?? [];
  const activeRun = state?.active_run ?? null;
  const latestScan = state?.latest_crypto_scan ?? null;

  const selectLane = (key: BerkshireLaneKey) => {
    const nextLane = state?.lanes.find((item) => item.key === key);
    setActiveLane(key);
    if (nextLane) {
      setForm((prev) => ({
        ...prev,
        symbol: nextLane.instruments[0] ?? prev.symbol,
      }));
    }
  };

  const updateForm = (key: keyof FormState, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleScanCrypto = async (autoPromoteDemo = false) => {
    setScanning(true);
    setError(null);
    try {
      const result = await api.createBerkshireCryptoScan(
        autoPromoteDemo
          ? { limit: 50, auto_promote_demo: true, max_promotions: 10 }
          : { limit: 50 },
      );
      setState(result.state);
      setActiveLane("crypto");
      setActiveTab("signals");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Crypto scan failed");
    } finally {
      setScanning(false);
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!lane) return;
    setSubmitting(true);
    setError(null);
    const body: BerkshireResearchRequest = {
      lane: activeLane,
      symbol: form.symbol.trim() || lane.instruments[0],
      skill: form.skill,
      catalyst: form.catalyst,
      thesis: form.thesis,
      entry_price: form.entry_price || null,
      stop_loss: form.stop_loss || null,
      target_price: form.target_price || null,
      capital_usd: form.capital_usd || null,
    };
    try {
      const result = await api.createBerkshireResearch(body);
      setState(result.state);
      setActiveTab("report");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Research run failed");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-full bg-ttcc-bg p-4 text-ttcc-text">
        <div className="mx-auto max-w-[1500px] space-y-3">
          <div className="h-28 animate-pulse rounded-lg border border-ttcc-border bg-ttcc-surface" />
          <div className="grid gap-3 xl:grid-cols-[minmax(280px,0.85fr)_minmax(420px,1.35fr)_minmax(300px,0.9fr)]">
            <div className="h-96 animate-pulse rounded-lg border border-ttcc-border bg-ttcc-surface" />
            <div className="h-96 animate-pulse rounded-lg border border-ttcc-border bg-ttcc-surface" />
            <div className="h-96 animate-pulse rounded-lg border border-ttcc-border bg-ttcc-surface" />
          </div>
        </div>
      </div>
    );
  }

  if (!state || !lane) {
    return (
      <div className="min-h-full bg-ttcc-bg p-4 text-ttcc-text">
        <section className="mx-auto max-w-3xl rounded-lg border border-ttcc-red/40 bg-ttcc-red/10 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-ttcc-red">
            <TriangleAlert className="h-4 w-4" />
            Berkshire state unavailable
          </div>
          <p className="mt-2 text-[12px] text-ttcc-text-secondary">{error ?? "No state returned from API."}</p>
          <button
            type="button"
            onClick={() => loadState("refresh")}
            className="mt-3 inline-flex items-center gap-2 rounded-lg border border-ttcc-border bg-ttcc-surface px-3 py-1.5 text-[11px] font-semibold text-ttcc-text-secondary transition-colors hover:text-ttcc-text"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Retry
          </button>
        </section>
      </div>
    );
  }

  return (
    <div className="min-h-full bg-ttcc-bg px-3 py-3 text-[12px] text-ttcc-text md:px-4 md:py-4">
      <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-3">
        <section className="rounded-lg border border-ttcc-border bg-ttcc-surface">
          <div className="flex flex-col gap-3 border-b border-ttcc-border/70 px-3 py-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-lg border border-ttcc-accent/40 bg-ttcc-accent/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-accent">
                  <BrainCircuit className="h-3.5 w-3.5" />
                  AI Berkshire Desk
                </span>
                <StatusPill tone="success">api live</StatusPill>
                <StatusPill tone="warning">research only</StatusPill>
                <span className="font-mono text-[10px] text-ttcc-text-muted">schema {state.schema_version}</span>
              </div>
              <h1 className="mt-2 text-xl font-bold tracking-tight text-ttcc-text md:text-2xl">
                Parallel research command for Crypto and Forex
              </h1>
              <p className="mt-1 max-w-3xl text-[12px] leading-5 text-ttcc-text-secondary">
                Creates persisted AI Berkshire-style research runs with four analyst lenses, checklist gates,
                Decimal risk audit, and execution isolation.
              </p>
            </div>

            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <LaneTabs lanes={state.lanes} activeLane={activeLane} onSelect={selectLane} />
              <button
                type="button"
                onClick={() => loadState("refresh")}
                disabled={refreshing}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-ttcc-border bg-ttcc-bg px-3 text-[11px] font-semibold text-ttcc-text-secondary transition-colors hover:text-ttcc-text disabled:opacity-50"
              >
                {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                Refresh
              </button>
              <button
                type="button"
                onClick={() => handleScanCrypto(false)}
                disabled={scanning}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-ttcc-accent/60 bg-ttcc-accent/15 px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-ttcc-accent transition-colors hover:bg-ttcc-accent/25 disabled:opacity-50"
              >
                {scanning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Radar className="h-3.5 w-3.5" />}
                Scan top 50
              </button>
              <button
                type="button"
                onClick={() => handleScanCrypto(true)}
                disabled={scanning}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-ttcc-green/60 bg-ttcc-green/10 px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-ttcc-green transition-colors hover:bg-ttcc-green/20 disabled:opacity-50"
              >
                {scanning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Target className="h-3.5 w-3.5" />}
                Scan + demo top 10
              </button>
            </div>
          </div>

          <div className="grid gap-px bg-ttcc-border/70 sm:grid-cols-2 xl:grid-cols-4">
            <SummaryTile icon={Globe2} label="market lane" value={lane.label} helper={lane.status_label} tone={lane.key === "crypto" ? "success" : "warning"} />
            <SummaryTile icon={WalletCards} label="execution" value={lane.execution} helper={lane.universe} tone={lane.key === "crypto" ? "success" : "neutral"} />
            <SummaryTile icon={Target} label="readiness" value={`${lane.readiness}%`} helper={lane.risk_policy} tone={lane.readiness >= 70 ? "success" : "warning"} />
            <SummaryTile icon={ShieldAlert} label="active runs" value={String(state.runs.length)} helper="persisted in data/berkshire" tone="accent" />
          </div>
        </section>

        {error ? (
          <section className="rounded-lg border border-ttcc-yellow/40 bg-ttcc-yellow/10 px-3 py-2 text-[12px] text-ttcc-yellow">
            {error}
          </section>
        ) : null}

        <div className="grid gap-3 xl:grid-cols-[minmax(280px,0.85fr)_minmax(420px,1.35fr)_minmax(320px,0.95fr)]">
          <section className="rounded-lg border border-ttcc-border bg-ttcc-surface">
            <PanelHeader icon={GitBranch} title="Market lanes" right={<StatusPill tone="accent">dual stack</StatusPill>} />
            <div className="divide-y divide-ttcc-border/70">
              {state.lanes.map((item) => (
                <LaneCard key={item.key} lane={item} active={item.key === activeLane} onSelect={() => selectLane(item.key)} />
              ))}
            </div>
            <div className="border-t border-ttcc-border/70 p-3">
              <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">
                <Radar className="h-3.5 w-3.5 text-ttcc-blue" />
                Radar instruments
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {lane.instruments.map((symbol) => (
                  <button
                    key={symbol}
                    type="button"
                    onClick={() => updateForm("symbol", symbol)}
                    className="rounded-lg border border-ttcc-border bg-ttcc-bg px-2 py-1 font-mono text-[10px] text-ttcc-text-secondary transition-colors hover:text-ttcc-text"
                  >
                    {symbol}
                  </button>
                ))}
              </div>
            </div>
          </section>

          <section className="rounded-lg border border-ttcc-border bg-ttcc-surface">
            <div className="flex flex-col gap-2 border-b border-ttcc-border/70 px-2 py-2 md:flex-row md:items-center md:justify-between">
              <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">
                <Workflow className="h-3.5 w-3.5 text-ttcc-accent" />
                Research operating system
              </div>
              <div className="flex flex-wrap gap-1">
                {TAB_LABELS.map(({ key, label, icon: Icon }) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setActiveTab(key)}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] transition-colors",
                      activeTab === key
                        ? "border-ttcc-accent/60 bg-ttcc-accent/15 text-ttcc-accent"
                        : "border-ttcc-border bg-ttcc-bg text-ttcc-text-secondary hover:text-ttcc-text",
                    )}
                  >
                    <Icon className="h-3 w-3" />
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {activeTab === "overview" ? (
              <OverviewPanel pods={state.analyst_pods} activeRun={activeRun} />
            ) : null}
            {activeTab === "signals" ? <SignalsPanel scan={latestScan} scanning={scanning} onScan={handleScanCrypto} /> : null}
            {activeTab === "pipeline" ? <PipelinePanel pipeline={pipeline} /> : null}
            {activeTab === "audit" ? <AuditPanel events={state.audit_events} /> : null}
            {activeTab === "report" ? <ReportPanel activeRun={activeRun} /> : null}
          </section>

          <TicketComposer
            form={form}
            lane={lane}
            activeLane={activeLane}
            state={state}
            submitting={submitting}
            onFormChange={updateForm}
            onSubmit={handleSubmit}
          />
        </div>

        <section className="rounded-lg border border-ttcc-border bg-ttcc-surface">
          <PanelHeader icon={BadgeCheck} title="Parallel trading build path" right={<StatusPill tone="accent">crypto plus forex</StatusPill>} />
          <div className="grid gap-px bg-ttcc-border/70 md:grid-cols-4">
            {state.roadmap.map((item) => (
              <article key={item.title} className="bg-ttcc-surface p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-ttcc-text-muted">{item.stage}</span>
                  <StatusPill tone={item.tone}>{item.state}</StatusPill>
                </div>
                <h2 className="mt-3 text-[12px] font-semibold text-ttcc-text">{item.title}</h2>
                <p className="mt-2 text-[11px] leading-5 text-ttcc-text-secondary">{item.detail}</p>
              </article>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function OverviewPanel({ pods, activeRun }: { pods: BerkshireAnalystPod[]; activeRun: BerkshireResearchRun | null }) {
  return (
    <div className="space-y-3 p-3">
      <div className="grid gap-3 lg:grid-cols-2">
        {pods.map((pod, index) => {
          const Icon = POD_ICONS[index] ?? Activity;
          return (
            <article key={pod.label} className="rounded-lg border border-ttcc-border bg-ttcc-bg p-3">
              <div className="flex items-start gap-2">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-ttcc-border bg-ttcc-surface-2 text-ttcc-accent">
                  <Icon className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <h2 className="text-[12px] font-semibold text-ttcc-text">{pod.label}</h2>
                  <p className="mt-0.5 font-mono text-[10px] text-ttcc-blue">{pod.value}</p>
                  <p className="mt-2 text-[11px] leading-5 text-ttcc-text-secondary">{pod.detail}</p>
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {activeRun ? (
        <article className="rounded-lg border border-ttcc-border bg-ttcc-bg p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">active run</div>
              <h2 className="mt-1 font-mono text-lg font-bold text-ttcc-text">{activeRun.symbol}</h2>
            </div>
            <StatusPill tone={activeRun.verdict === "pass_research" ? "success" : "warning"}>{activeRun.verdict}</StatusPill>
          </div>
          <p className="mt-2 text-[11px] leading-5 text-ttcc-text-secondary">{activeRun.summary}</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-4">
            <MiniMetric label="skill" value={activeRun.skill} />
            <MiniMetric label="grade" value={activeRun.info_grade} />
            <MiniMetric label="conviction" value={`${activeRun.conviction}/100`} />
            <MiniMetric label="mode" value={activeRun.mode} />
          </div>
        </article>
      ) : (
        <EmptyRun />
      )}
    </div>
  );
}

function PipelinePanel({ pipeline }: { pipeline: BerkshireState["pipelines"][BerkshireLaneKey] }) {
  return (
    <div className="p-3">
      <div className="grid gap-2">
        {pipeline.map((step, index) => (
          <article key={step.title} className="grid gap-3 rounded-lg border border-ttcc-border bg-ttcc-bg p-3 md:grid-cols-[52px_1fr_auto] md:items-center">
            <div className="font-mono text-lg font-bold text-ttcc-text-muted tabular">
              {String(index + 1).padStart(2, "0")}
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold text-ttcc-text">{step.title}</h2>
                <StatusPill tone={step.tone}>{step.status}</StatusPill>
              </div>
              <p className="mt-1 text-[11px] text-ttcc-text-secondary">{step.owner}</p>
              <p className="mt-2 text-[11px] leading-5 text-ttcc-text-secondary">{step.description}</p>
            </div>
            <ListChecks className="hidden h-5 w-5 text-ttcc-text-muted md:block" />
          </article>
        ))}
      </div>
    </div>
  );
}

function AuditPanel({ events }: { events: BerkshireState["audit_events"] }) {
  return (
    <div className="p-3">
      <div className="rounded-lg border border-ttcc-border bg-ttcc-bg">
        <div className="grid grid-cols-[64px_1fr_1fr] border-b border-ttcc-border px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">
          <span>time</span>
          <span>event</span>
          <span>result</span>
        </div>
        {events.map((event) => (
          <div key={`${event.time}-${event.label}-${event.value}`} className="grid grid-cols-[64px_1fr_1fr] items-center border-b border-ttcc-border/60 px-3 py-2 last:border-b-0">
            <span className="font-mono text-[11px] text-ttcc-text-muted tabular">{event.time}</span>
            <span className="text-[11px] font-medium text-ttcc-text">{event.label}</span>
            <span className="flex items-center justify-between gap-2 text-[11px] text-ttcc-text-secondary">
              {event.value}
              <StatusDot tone={event.tone} />
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReportPanel({ activeRun }: { activeRun: BerkshireResearchRun | null }) {
  if (!activeRun) return <EmptyRun />;
  return (
    <div className="space-y-3 p-3">
      <div className="grid gap-2 lg:grid-cols-2">
        {activeRun.analysts.map((analyst) => (
          <article key={analyst.key} className="rounded-lg border border-ttcc-border bg-ttcc-bg p-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-[12px] font-semibold text-ttcc-text">{analyst.name}</h2>
              <span className="font-mono text-[11px] text-ttcc-accent">{analyst.score.toFixed(1)}/5</span>
            </div>
            <p className="mt-1 text-[10px] uppercase tracking-[0.08em] text-ttcc-text-muted">{analyst.focus}</p>
            <p className="mt-2 text-[11px] leading-5 text-ttcc-text-secondary">{analyst.finding}</p>
            <p className="mt-2 text-[11px] leading-5 text-ttcc-yellow">{analyst.concern}</p>
          </article>
        ))}
      </div>

      <article className="rounded-lg border border-ttcc-border bg-ttcc-bg p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-[12px] font-semibold text-ttcc-text">Checklist and financial rigor</h2>
          <StatusPill tone={activeRun.financial_checks.tone}>{activeRun.financial_checks.status}</StatusPill>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {activeRun.checklist.map((item) => (
            <div key={item.label} className="rounded-lg border border-ttcc-border bg-ttcc-surface px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold text-ttcc-text">{item.label}</span>
                <StatusPill tone={item.tone}>{item.status}</StatusPill>
              </div>
              <p className="mt-1 text-[11px] leading-5 text-ttcc-text-secondary">{item.detail}</p>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[11px] leading-5 text-ttcc-text-secondary">{activeRun.financial_checks.summary}</p>
      </article>

      <pre className="max-h-72 overflow-auto rounded-lg border border-ttcc-border bg-ttcc-bg p-3 text-[11px] leading-5 text-ttcc-text-secondary">
        {activeRun.report_markdown}
      </pre>
    </div>
  );
}

function SummaryTile({
  icon: Icon,
  label,
  value,
  helper,
  tone,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
  helper: string;
  tone: BerkshireTone;
}) {
  return (
    <article className="bg-ttcc-surface px-3 py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">{label}</span>
        <Icon className={cn("h-4 w-4", toneText(tone))} />
      </div>
      <div className="mt-2 truncate text-lg font-bold text-ttcc-text">{value}</div>
      <div className="mt-1 min-h-8 text-[11px] leading-4 text-ttcc-text-secondary">{helper}</div>
    </article>
  );
}
