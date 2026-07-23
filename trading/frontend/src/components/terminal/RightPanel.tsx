import { Suspense, lazy, useState } from "react";
import {
  Brain,
  ChevronLeft,
  ChevronRight,
  MessageSquare,
  ListChecks,
  Layers,
} from "lucide-react";
import { cn } from "@/components/terminal/primitives";
import { BrainLog, type BrainDecision } from "@/components/terminal/BrainLog";
import { AlphaZooMini } from "@/components/terminal/AlphaZooMini";
import { FeaturePipeline } from "@/components/terminal/FeaturePipeline";
import type { AlphaBenchTopRow } from "@/lib/api";

const AgentChatConsole = lazy(() =>
  import("@/components/terminal/AgentChatConsole").then((module) => ({
    default: module.AgentChatConsole,
  })),
);

type Tab = "chat" | "brain" | "alpha" | "pipeline";

/**
 * RightPanel — Collapsible right sidebar with tabbed interface for:
 *   - Co-pilot Chat (interactive AI Agent console)
 *   - Brain Log (real-time LLM trading decisions logs)
 *   - Alpha Zoo (top formulaic alpha strategies list)
 *   - Feature Pipeline (project development status tracker)
 */
export function RightPanel({
  decisions,
  topAlphas,
  defaultCollapsed = false,
}: {
  decisions: BrainDecision[];
  topAlphas?: AlphaBenchTopRow[];
  defaultCollapsed?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const [activeTab, setActiveTab] = useState<Tab>("chat");

  if (collapsed) {
    return (
      <aside
        className={cn(
          "relative flex w-9 shrink-0 flex-col items-center gap-2 bg-ttcc-bg py-2",
          "before:absolute before:left-0 before:top-0 before:h-full before:w-px",
          "before:bg-gradient-to-b before:from-transparent before:via-ttcc-border/50 before:to-transparent",
          "before:pointer-events-none before:content-['']"
        )}
      >
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          className="flex h-7 w-7 items-center justify-center rounded-lg border border-ttcc-border-subtle bg-ttcc-surface text-ttcc-text-secondary hover:text-ttcc-text hover:tt-glow-accent transition-all"
          title="Expand right panel"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <span className="font-mono text-[9px] uppercase tracking-wider text-ttcc-text-muted [writing-mode:vertical-rl] rotate-180">
          chat · brain · alpha · pipeline
        </span>
      </aside>
    );
  }

  const tabs = [
    { id: "chat" as Tab, icon: MessageSquare, label: "Chat" },
    { id: "brain" as Tab, icon: Brain, label: "Brain Log" },
    { id: "alpha" as Tab, icon: Layers, label: "Alpha" },
    { id: "pipeline" as Tab, icon: ListChecks, label: "Pipeline" },
  ];

  return (
    <aside
      className={cn(
        "relative flex w-[380px] shrink-0 flex-col overflow-hidden bg-ttcc-bg",
        "before:absolute before:left-0 before:top-0 before:h-full before:w-px",
        "before:bg-gradient-to-b before:from-transparent before:via-ttcc-border/50 before:to-transparent",
        "before:pointer-events-none before:content-['']"
      )}
    >
      {/* Sidebar Header & Collapser */}
      <div className="tt-glass flex items-center justify-between px-2.5 py-1.5 shrink-0">
        <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-ttcc-text-secondary">
          AI Co-pilot Console
        </span>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className="flex h-5 w-5 items-center justify-center rounded-lg text-ttcc-text-secondary hover:text-ttcc-text hover:tt-glow-accent transition-all"
          title="Collapse panel"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Tab Selectors */}
      <div className="flex bg-ttcc-surface/40 shrink-0 p-1 gap-0.5">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex-1 flex items-center justify-center gap-1.5 py-1 px-1 rounded-lg transition-all text-[10px] font-bold uppercase tracking-wider",
                active
                  ? "bg-ttcc-accent/10 text-ttcc-accent tt-glow-accent"
                  : "text-ttcc-text-secondary hover:text-ttcc-text hover:bg-ttcc-surface/30"
              )}
            >
              <Icon className="h-3 w-3" />
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Tab Panels */}
      <div className="relative flex-1 min-h-0 overflow-y-auto before:absolute before:inset-x-0 before:top-0 before:h-8 before:bg-gradient-to-b before:from-ttcc-surface/40 before:to-transparent before:pointer-events-none before:content-['']">
        {activeTab === "chat" && (
          <Suspense
            fallback={(
              <div className="flex h-full items-center justify-center text-[11px] text-ttcc-text-muted">
                Loading chat console…
              </div>
            )}
          >
            <AgentChatConsole />
          </Suspense>
        )}

        {activeTab === "brain" && (
          <div className="p-2 h-full overflow-y-auto">
            <div className="mb-2 text-[10px] uppercase font-bold text-ttcc-text-secondary tracking-wider px-1">
              Live LLM Decision Streams
            </div>
            <BrainLog decisions={decisions} />
          </div>
        )}

        {activeTab === "alpha" && (
          <div className="p-2 h-full overflow-y-auto">
            <div className="mb-2 text-[10px] uppercase font-bold text-ttcc-text-secondary tracking-wider px-1">
              Top Alpha Formulas
            </div>
            <AlphaZooMini topRows={topAlphas} />
          </div>
        )}

        {activeTab === "pipeline" && (
          <div className="p-2 h-full overflow-y-auto">
            <div className="mb-2 text-[10px] uppercase font-bold text-ttcc-text-secondary tracking-wider px-1">
              Project Feature Designs
            </div>
            <FeaturePipeline />
          </div>
        )}
      </div>
    </aside>
  );
}
