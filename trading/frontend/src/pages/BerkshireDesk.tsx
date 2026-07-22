import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
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
  SlidersHorizontal,
  Target,
  TriangleAlert,
  WalletCards,
  Workflow,
} from "lucide-react";
import {
  api,
  type BerkshireAnalystPod,
  type BerkshireCryptoScan,
  type BerkshireLane,
  type BerkshireLaneKey,
  type BerkshireResearchRequest,
  type BerkshireResearchRun,
  type BerkshireSignal,
  type BerkshireSkill,
  type BerkshireState,
  type BerkshireTone,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type DeskTab = "overview" | "signals" | "pipeline" | "audit" | "report";

const TAB_LABELS: Array<{ key: DeskTab; label: string; icon: typeof Activity }> = [
  { key: "overview", label: "Overview", icon: Activity },
  { key: "signals", label: "Signals", icon: Radar },
  { key: "pipeline", label: "Pipeline", icon: Workflow },
  { key: "audit", label: "Audit", icon: ScrollText },
  { key: "report", label: "Report", icon: BadgeCheck },
];

const SKILLS: Array<{ value: BerkshireSkill; label: string }> = [
  { value: "investment-team", label: "Investment team" },
  { value: "investment-research", label: "Investment research" },
  { value: "investment-checklist", label: "Checklist" },
  { value: "quality-screen", label: "Quality screen" },
  { value: "news-pulse", label: "News pulse" },
  { value: "thesis-tracker", label: "Thesis tracker" },
  { value: "portfolio-review", label: "Portfolio review" },
];

const POD_ICONS = [Landmark, ChartCandlestick, ShieldCheck, ScrollText];

interface FormState {
  symbol: string;
  skill: BerkshireSkill;
  catalyst: string;
  thesis: string;
  entry_price: string;
  stop_loss: string;
  target_price: string;
  capital_usd: string;
}

const DEFAULT_FORM: FormState = {
  symbol: "BTC-USDT",
  skill: "investment-team",
  catalyst: "",
  thesis: "",
  entry_price: "",
  stop_loss: "",
  target_price: "",
  capital_usd: "200",
};

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
          <div className="h-28 animate-pulse rounded-md border border-ttcc-border bg-ttcc-surface" />
          <div className="grid gap-3 xl:grid-cols-[minmax(280px,0.85fr)_minmax(420px,1.35fr)_minmax(300px,0.9fr)]">
            <div className="h-96 animate-pulse rounded-md border border-ttcc-border bg-ttcc-surface" />
            <div className="h-96 animate-pulse rounded-md border border-ttcc-border bg-ttcc-surface" />
            <div className="h-96 animate-pulse rounded-md border border-ttcc-border bg-ttcc-surface" />
          </div>
        </div>
      </div>
    );
  }

  if (!state || !lane) {
    return (
      <div className="min-h-full bg-ttcc-bg p-4 text-ttcc-text">
        <section className="mx-auto max-w-3xl rounded-md border border-ttcc-red/40 bg-ttcc-red/10 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-ttcc-red">
            <TriangleAlert className="h-4 w-4" />
            Berkshire state unavailable
          </div>
          <p className="mt-2 text-[12px] text-ttcc-text-secondary">{error ?? "No state returned from API."}</p>
          <button
            type="button"
            onClick={() => loadState("refresh")}
            className="mt-3 inline-flex items-center gap-2 rounded border border-ttcc-border bg-ttcc-surface px-3 py-1.5 text-[11px] font-semibold text-ttcc-text-secondary hover:text-ttcc-text"
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
        <section className="rounded-md border border-ttcc-border bg-ttcc-surface">
          <div className="flex flex-col gap-3 border-b border-ttcc-border/70 px-3 py-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1.5 rounded border border-ttcc-accent/40 bg-ttcc-accent/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-accent">
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
              <div className="grid min-w-[280px] grid-cols-2 rounded-md border border-ttcc-border bg-ttcc-bg p-1">
                {state.lanes.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => selectLane(item.key)}
                    className={cn(
                      "flex min-h-12 flex-col items-start rounded px-2.5 py-1.5 text-left transition-colors",
                      item.key === activeLane
                        ? "bg-ttcc-accent/15 text-ttcc-accent ring-1 ring-ttcc-accent/40"
                        : "text-ttcc-text-secondary hover:bg-ttcc-surface-2 hover:text-ttcc-text",
                    )}
                    aria-pressed={item.key === activeLane}
                  >
                    <span className="text-[11px] font-bold">{item.label}</span>
                    <span className="mt-0.5 text-[10px] text-current opacity-75">{item.status_label}</span>
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => loadState("refresh")}
                disabled={refreshing}
                className="inline-flex h-9 items-center justify-center gap-2 rounded border border-ttcc-border bg-ttcc-bg px-3 text-[11px] font-semibold text-ttcc-text-secondary transition-colors hover:text-ttcc-text disabled:opacity-50"
              >
                {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                Refresh
              </button>
              <button
                type="button"
                onClick={() => handleScanCrypto(false)}
                disabled={scanning}
                className="inline-flex h-9 items-center justify-center gap-2 rounded border border-ttcc-accent/60 bg-ttcc-accent/15 px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-ttcc-accent transition-colors hover:bg-ttcc-accent/25 disabled:opacity-50"
              >
                {scanning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Radar className="h-3.5 w-3.5" />}
                Scan top 50
              </button>
              <button
                type="button"
                onClick={() => handleScanCrypto(true)}
                disabled={scanning}
                className="inline-flex h-9 items-center justify-center gap-2 rounded border border-ttcc-green/60 bg-ttcc-green/10 px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-ttcc-green transition-colors hover:bg-ttcc-green/20 disabled:opacity-50"
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
          <section className="rounded-md border border-ttcc-yellow/40 bg-ttcc-yellow/10 px-3 py-2 text-[12px] text-ttcc-yellow">
            {error}
          </section>
        ) : null}

        <div className="grid gap-3 xl:grid-cols-[minmax(280px,0.85fr)_minmax(420px,1.35fr)_minmax(320px,0.95fr)]">
          <section className="rounded-md border border-ttcc-border bg-ttcc-surface">
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
                    className="rounded border border-ttcc-border bg-ttcc-bg px-2 py-1 font-mono text-[10px] text-ttcc-text-secondary hover:text-ttcc-text"
                  >
                    {symbol}
                  </button>
                ))}
              </div>
            </div>
          </section>

          <section className="rounded-md border border-ttcc-border bg-ttcc-surface">
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
                      "inline-flex items-center gap-1.5 rounded border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] transition-colors",
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

          <aside className="rounded-md border border-ttcc-border bg-ttcc-surface">
            <PanelHeader icon={SlidersHorizontal} title="Run research" right={<StatusPill tone={activeLane === "forex" ? "warning" : "success"}>{lane.status_label}</StatusPill>} />
            <form onSubmit={handleSubmit} className="space-y-3 p-3">
              <div className="grid grid-cols-2 gap-2">
                <Field label="symbol">
                  <input
                    value={form.symbol}
                    onChange={(event) => updateForm("symbol", event.target.value.toUpperCase())}
                    className="field-input font-mono"
                    placeholder={lane.instruments[0]}
                  />
                </Field>
                <Field label="skill">
                  <select
                    value={form.skill}
                    onChange={(event) => updateForm("skill", event.target.value as BerkshireSkill)}
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
                  onChange={(event) => updateForm("catalyst", event.target.value)}
                  className="field-input min-h-16 resize-y"
                  placeholder="ETF inflow, CPI surprise, funding reset..."
                />
              </Field>
              <Field label="thesis">
                <textarea
                  value={form.thesis}
                  onChange={(event) => updateForm("thesis", event.target.value)}
                  className="field-input min-h-20 resize-y"
                  placeholder="What has to be true, and where is invalidation?"
                />
              </Field>

              <div className="grid grid-cols-2 gap-2">
                <Field label="entry">
                  <input value={form.entry_price} onChange={(event) => updateForm("entry_price", event.target.value)} className="field-input font-mono" />
                </Field>
                <Field label="stop">
                  <input value={form.stop_loss} onChange={(event) => updateForm("stop_loss", event.target.value)} className="field-input font-mono" />
                </Field>
                <Field label="target">
                  <input value={form.target_price} onChange={(event) => updateForm("target_price", event.target.value)} className="field-input font-mono" />
                </Field>
                <Field label="capital">
                  <input value={form.capital_usd} onChange={(event) => updateForm("capital_usd", event.target.value)} className="field-input font-mono" />
                </Field>
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="inline-flex h-9 w-full items-center justify-center gap-2 rounded border border-ttcc-accent/60 bg-ttcc-accent/15 px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-ttcc-accent transition-colors hover:bg-ttcc-accent/25 disabled:opacity-50"
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
        </div>

        <section className="rounded-md border border-ttcc-border bg-ttcc-surface">
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
            <article key={pod.label} className="rounded-md border border-ttcc-border bg-ttcc-bg p-3">
              <div className="flex items-start gap-2">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-ttcc-border bg-ttcc-surface-2 text-ttcc-accent">
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
        <article className="rounded-md border border-ttcc-border bg-ttcc-bg p-3">
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

function SignalsPanel({
  scan,
  scanning,
  onScan,
}: {
  scan: BerkshireCryptoScan | null;
  scanning: boolean;
  onScan: (autoPromoteDemo?: boolean) => void;
}) {
  if (!scan) {
    return (
      <div className="m-3 flex min-h-56 items-center justify-center rounded-md border border-dashed border-ttcc-border bg-ttcc-bg p-5 text-center">
        <div>
          <Radar className="mx-auto h-7 w-7 text-ttcc-text-muted" />
          <h2 className="mt-3 text-sm font-semibold text-ttcc-text">No crypto signal scan yet</h2>
          <p className="mt-1 max-w-sm text-[11px] leading-5 text-ttcc-text-secondary">
            Scan the crypto lane to create Berkshire signal-only context before the LLM drafts any ticket.
          </p>
          <button
            type="button"
            onClick={() => onScan(false)}
            disabled={scanning}
            className="mt-4 inline-flex h-9 items-center justify-center gap-2 rounded border border-ttcc-accent/60 bg-ttcc-accent/15 px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-ttcc-accent transition-colors hover:bg-ttcc-accent/25 disabled:opacity-50"
          >
            {scanning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Radar className="h-3.5 w-3.5" />}
            Scan top 50
          </button>
          <button
            type="button"
            onClick={() => onScan(true)}
            disabled={scanning}
            className="ml-2 mt-4 inline-flex h-9 items-center justify-center gap-2 rounded border border-ttcc-green/60 bg-ttcc-green/10 px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-ttcc-green transition-colors hover:bg-ttcc-green/20 disabled:opacity-50"
          >
            {scanning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Target className="h-3.5 w-3.5" />}
            Scan + demo top 10
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3 p-3">
      <article className="rounded-md border border-ttcc-border bg-ttcc-bg p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">
              latest crypto scan
            </div>
            <h2 className="mt-1 font-mono text-lg font-bold text-ttcc-text">{scan.top_symbol ?? "No top signal"}</h2>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <StatusPill tone="accent">{scan.mode}</StatusPill>
            <StatusPill tone={scan.provider_error ? "warning" : "success"}>{scan.source}</StatusPill>
          </div>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-4">
          <MiniMetric label="signals" value={String(scan.signal_count)} />
          <MiniMetric label="universe" value={String(scan.universe_count)} />
          <MiniMetric label="top state" value={scan.top_signal ?? "none"} />
          <MiniMetric label="demo runs" value={String(scan.demo_promotions?.length ?? 0)} />
        </div>
        {scan.demo_promotions?.length ? (
          <div className="mt-3 grid gap-2">
            {scan.demo_promotions.map((promotion) => (
              <div
                key={promotion.decision_id}
                className="rounded border border-ttcc-green/30 bg-ttcc-green/10 px-2.5 py-2 text-[11px] leading-5 text-ttcc-green"
              >
                {promotion.executed ? promotion.reason : promotion.stage}: {promotion.reason}
              </div>
            ))}
          </div>
        ) : null}
        {scan.provider_error ? (
          <p className="mt-3 rounded border border-ttcc-yellow/30 bg-ttcc-yellow/10 px-2.5 py-2 text-[11px] leading-5 text-ttcc-yellow">
            {scan.provider_error}
          </p>
        ) : null}
      </article>

      <div className="grid gap-2">
        {scan.signals.map((signal) => (
          <SignalCard key={signal.signal_id || signal.symbol} signal={signal} />
        ))}
      </div>
    </div>
  );
}

function SignalCard({ signal }: { signal: BerkshireSignal }) {
  const status = signal.status || signal.signal;
  const reasons = signal.reasons?.length ? signal.reasons : signal.why;
  const tone = status === "blocked" ? "danger" : status === "watchlist" ? "warning" : "success";
  const confidence = `${Math.round((signal.confidence ?? 0) * 100)}%`;
  return (
    <article className="rounded-md border border-ttcc-border bg-ttcc-bg p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-mono text-base font-bold text-ttcc-text">{signal.symbol}</h2>
            <StatusPill tone={tone}>{status}</StatusPill>
            <StatusPill tone="neutral">{signal.direction}</StatusPill>
            <StatusPill tone="info">{signal.action_hint}</StatusPill>
          </div>
          <p className="mt-1 text-[11px] leading-5 text-ttcc-text-secondary">{signal.llm_context.instruction}</p>
        </div>
        <div className="text-right">
          <div className="font-mono text-lg font-bold text-ttcc-accent">{signal.score}</div>
          <div className="text-[10px] uppercase tracking-[0.08em] text-ttcc-text-muted">
            grade {signal.grade} · conf {confidence}
          </div>
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-4">
        <MiniMetric label="last" value={signal.last_price ?? "n/a"} />
        <MiniMetric label="24h" value={signal.change_pct_24h ? `${signal.change_pct_24h}%` : "n/a"} />
        <MiniMetric label="conf" value={confidence} />
        <MiniMetric label="entry" value={signal.entry_zone} />
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">why</div>
          <ul className="mt-1 space-y-1">
            {reasons.map((item) => (
              <li key={item} className="text-[11px] leading-5 text-ttcc-text-secondary">
                {item}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">blockers</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {signal.blockers.length ? (
              signal.blockers.map((item) => (
                <span key={item} className="rounded border border-ttcc-yellow/30 bg-ttcc-yellow/10 px-1.5 py-0.5 text-[10px] text-ttcc-yellow">
                  {item}
                </span>
              ))
            ) : (
              <span className="rounded border border-ttcc-green/30 bg-ttcc-green/10 px-1.5 py-0.5 text-[10px] text-ttcc-green">
                no blocker
              </span>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

function PipelinePanel({ pipeline }: { pipeline: BerkshireState["pipelines"][BerkshireLaneKey] }) {
  return (
    <div className="p-3">
      <div className="grid gap-2">
        {pipeline.map((step, index) => (
          <article key={step.title} className="grid gap-3 rounded-md border border-ttcc-border bg-ttcc-bg p-3 md:grid-cols-[52px_1fr_auto] md:items-center">
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
      <div className="rounded-md border border-ttcc-border bg-ttcc-bg">
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
          <article key={analyst.key} className="rounded-md border border-ttcc-border bg-ttcc-bg p-3">
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

      <article className="rounded-md border border-ttcc-border bg-ttcc-bg p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-[12px] font-semibold text-ttcc-text">Checklist and financial rigor</h2>
          <StatusPill tone={activeRun.financial_checks.tone}>{activeRun.financial_checks.status}</StatusPill>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {activeRun.checklist.map((item) => (
            <div key={item.label} className="rounded border border-ttcc-border bg-ttcc-surface px-2.5 py-2">
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

      <pre className="max-h-72 overflow-auto rounded-md border border-ttcc-border bg-ttcc-bg p-3 text-[11px] leading-5 text-ttcc-text-secondary">
        {activeRun.report_markdown}
      </pre>
    </div>
  );
}

function EmptyRun() {
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

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">{label}</span>
      {children}
    </label>
  );
}

function PanelHeader({
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

function LaneCard({ lane, active, onSelect }: { lane: BerkshireLane; active: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn("w-full px-3 py-3 text-left transition-colors", active ? "bg-ttcc-accent/10" : "hover:bg-ttcc-surface-2/80")}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[13px] font-semibold text-ttcc-text">{lane.label}</div>
          <div className="mt-1 text-[11px] text-ttcc-text-secondary">{lane.execution}</div>
        </div>
        <StatusPill tone={lane.key === "crypto" ? "success" : "warning"}>{lane.status_label}</StatusPill>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded bg-ttcc-bg">
        <div className={cn("h-full rounded", lane.readiness >= 70 ? "bg-ttcc-green" : "bg-ttcc-yellow")} style={{ width: `${lane.readiness}%` }} />
      </div>
      <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-ttcc-text-muted tabular">
        <span>{lane.universe}</span>
        <span>{lane.readiness}%</span>
      </div>
      {lane.blockers.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {lane.blockers.map((blocker) => (
            <span
              key={blocker}
              className="rounded border border-ttcc-yellow/30 bg-ttcc-yellow/10 px-1.5 py-0.5 text-[10px] font-medium text-ttcc-yellow"
            >
              {blocker}
            </span>
          ))}
        </div>
      ) : null}
    </button>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-ttcc-border bg-ttcc-surface px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-[0.08em] text-ttcc-text-muted">{label}</div>
      <div className="mt-1 truncate font-mono text-[11px] text-ttcc-text">{value}</div>
    </div>
  );
}

function StatusPill({ tone, children }: { tone: BerkshireTone; children: ReactNode }) {
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

function StatusDot({ tone }: { tone: BerkshireTone }) {
  return <span className={cn("h-2 w-2 shrink-0 rounded-full", toneBg(tone))} aria-hidden />;
}

function toneText(tone: BerkshireTone): string {
  if (tone === "success") return "text-ttcc-green";
  if (tone === "warning") return "text-ttcc-yellow";
  if (tone === "danger") return "text-ttcc-red";
  if (tone === "info") return "text-ttcc-blue";
  if (tone === "accent") return "text-ttcc-accent";
  return "text-ttcc-text-secondary";
}

function toneBg(tone: BerkshireTone): string {
  if (tone === "success") return "bg-ttcc-green";
  if (tone === "warning") return "bg-ttcc-yellow";
  if (tone === "danger") return "bg-ttcc-red";
  if (tone === "info") return "bg-ttcc-blue";
  if (tone === "accent") return "bg-ttcc-accent";
  return "bg-ttcc-text-muted";
}
