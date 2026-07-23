import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useAgentStore } from "@/stores/agent";
import { useSSE } from "@/hooks/useSSE";
import {
  ApiError,
  api,
  type GoalSnapshot,
  type MandateProposal,
  type MandateCommitted,
  type LiveAction,
  type LiveHalted,
  type LiveStatus,
} from "@/lib/api";
import { isReportWorthyRun } from "@/lib/runReports";
import {
  applySwarmEvent,
  buildSwarmStatusFromStarted,
  buildSwarmStatusFromToolResultPreview,
} from "@/lib/swarmStatus";
import type { AgentMessage, ToolCallEntry } from "@/types/agent";
import { isTerminalGoalStatus } from "@/components/agent/goalHelpers";
import { haltScopeStillActive } from "@/components/agent/liveHelpers";

const act = () => useAgentStore.getState();

const LIVE_STATUS_POLL_INTERVAL_MS = 15_000;

interface ProposalItem {
  kind: "proposal";
  timestamp: number;
  proposal: MandateProposal;
}
interface LiveActionItem {
  kind: "live_action";
  timestamp: number;
  action: LiveAction;
}
type LiveItem = ProposalItem | LiveActionItem;

export interface UseAgentSessionParams {
  forceScrollToBottom: () => void;
  scrollToBottom: () => void;
  setReasoningActive: (v: boolean) => void;
  setGoalSnapshot: (snapshot: GoalSnapshot | null) => void;
  setGoalDetailsOpen: (v: boolean) => void;
  setGoalEditActive: (v: boolean) => void;
  setLiveItems: React.Dispatch<React.SetStateAction<LiveItem[]>>;
  setCommittedMandates: React.Dispatch<React.SetStateAction<Record<string, MandateCommitted>>>;
  setLiveHalted: React.Dispatch<React.SetStateAction<LiveHalted | null>>;
  setLiveStatus: React.Dispatch<React.SetStateAction<LiveStatus | null>>;
  setLiveStatusUnavailable: (v: boolean) => void;
  setLiveStatusRefresh: React.Dispatch<React.SetStateAction<number>>;
}

export function useAgentSession({
  forceScrollToBottom,
  scrollToBottom,
  setReasoningActive,
  setGoalSnapshot,
  setGoalDetailsOpen,
  setGoalEditActive,
  setLiveItems,
  setCommittedMandates,
  setLiveHalted,
  setLiveStatus,
  setLiveStatusUnavailable,
  setLiveStatusRefresh,
}: UseAgentSessionParams) {
  const { t } = useTranslation();
  const { connect, disconnect, onStatusChange } = useSSE();

  const status = useAgentStore(s => s.status);

  const genRef = useRef(0);
  const sseSessionRef = useRef<string | null>(null);
  const prevSseStatusRef = useRef<string>("disconnected");
  const lastEventRef = useRef(0);
  const sseTimeoutMsRef = useRef(90_000);
  const pendingProgressRef = useRef<Map<string, NonNullable<ToolCallEntry["progress"]>>>(new Map());
  const progressRafRef = useRef(0);

  useEffect(() => {
    onStatusChange((s) => {
      act().setSseStatus(s);
      if (s === "reconnecting" && prevSseStatusRef.current === "connected") toast.warning(t('agent.connectionLostReconnect'));
      else if (s === "connected" && prevSseStatusRef.current === "reconnecting") toast.success(t('agent.connectionRestored'));
      prevSseStatusRef.current = s;
    });
  }, [onStatusChange, t]);

  const doDisconnect = useCallback(() => {
    disconnect();
    sseSessionRef.current = null;
  }, [disconnect]);

  const loadGoalSnapshot = useCallback(async (sid?: string | null) => {
    const targetSession = sid || act().sessionId;
    if (!targetSession) {
      setGoalSnapshot(null);
      setGoalDetailsOpen(false);
      setGoalEditActive(false);
      return;
    }
    try {
      const snapshot = await api.getGoal(targetSession);
      if (act().sessionId !== targetSession) return;
      setGoalSnapshot(snapshot);
    } catch (error) {
      if (act().sessionId !== targetSession) return;
      if (error instanceof ApiError && error.status === 404) {
        setGoalSnapshot(null);
        setGoalDetailsOpen(false);
        setGoalEditActive(false);
      } else {
        toast.error(error instanceof Error ? error.message : t('agent.failedToLoadGoal'));
      }
    }
  }, [setGoalDetailsOpen, setGoalEditActive, setGoalSnapshot, t]);

  const loadSessionMessages = useCallback(async (sid: string, gen: number) => {
    try {
      const msgs = await api.getSessionMessages(sid);
      if (genRef.current !== gen) return;
      const agentMsgs: AgentMessage[] = [];
      for (const m of msgs) {
        const meta = m.metadata as Record<string, unknown> | undefined;
        const runId = meta?.run_id as string | undefined;
        const metrics = meta?.metrics as Record<string, number> | undefined;
        const ts = new Date(m.created_at).getTime();
        if (m.role === "user") {
          agentMsgs.push({ id: m.message_id, type: "user", content: m.content, timestamp: ts });
        } else if (runId) {
          if (m.content && m.content !== "Strategy execution completed.") {
            agentMsgs.push({ id: m.message_id + "_ans", type: "answer", content: m.content, timestamp: ts });
          }
          if (metrics && Object.keys(metrics).length > 0) {
            agentMsgs.push({ id: m.message_id, type: "run_complete", content: "", runId, metrics, timestamp: ts + 1 });
          } else {
            let fetchedMetrics: Record<string, number> | undefined;
            let fetchedCurve: Array<{ time: string; equity: number }> | undefined;
            let showCard = false;
            try {
              const runData = await api.getRun(runId);
              if (isReportWorthyRun(runData)) {
                fetchedMetrics = runData.metrics;
                fetchedCurve = runData.equity_curve?.map((e) => ({ time: e.time, equity: Number(e.equity) }));
                showCard = true;
              }
            } catch {
              showCard = true;
            }
            if (showCard) {
              agentMsgs.push({
                id: m.message_id,
                type: "run_complete",
                content: "",
                runId,
                metrics: fetchedMetrics,
                equityCurve: fetchedCurve,
                timestamp: ts + 1,
              });
            }
          }
        } else {
          agentMsgs.push({ id: m.message_id, type: "answer", content: m.content, timestamp: ts });
        }
      }
      if (genRef.current !== gen) return;
      act().loadHistory(agentMsgs);
      act().setSessionLoading(false);
      act().cacheSession(sid, agentMsgs);
      setTimeout(() => forceScrollToBottom(), 50);
    } catch {
      act().setSessionLoading(false);
    }
  }, [forceScrollToBottom]);

  const refreshSessionMessages = useCallback(async (sid: string) => {
    const gen = genRef.current + 1;
    genRef.current = gen;
    await loadSessionMessages(sid, gen);
  }, [loadSessionMessages]);

  const syncCompletedAttempt = useCallback(async (sid: string, attemptId?: string) => {
    if (!attemptId) return false;
    for (let i = 0; i < 3; i += 1) {
      try {
        const storedMessages = await api.getSessionMessages(sid);
        const completed = storedMessages.some(
          (message) => message.role === "assistant" && message.linked_attempt_id === attemptId,
        );
        if (completed) {
          if (act().sessionId !== sid) return true;
          setReasoningActive(false);
          act().clearStreaming();
          act().setStatus("idle");
          useAgentStore.setState({ toolCalls: [] });
          await refreshSessionMessages(sid);
          return true;
        }
      } catch {
        return false;
      }
      await new Promise<void>((resolve) => window.setTimeout(resolve, 800));
    }
    return false;
  }, [refreshSessionMessages, setReasoningActive]);

  const setupSSE = useCallback((sid: string) => {
    if (sseSessionRef.current === sid) return;
    disconnect();
    sseSessionRef.current = sid;

    const touch = () => { lastEventRef.current = Date.now(); };

    connect(api.sseUrl(sid, { replay: "active" }), {
      text_delta: (d) => {
        touch();
        setReasoningActive(false);
        act().appendDelta(String(d.delta || ""));
        scrollToBottom();
      },
      reasoning_delta: () => {
        touch();
        setReasoningActive(true);
        if (act().status !== "streaming") act().setStatus("streaming");
        scrollToBottom();
      },
      stream_reset: () => {
        touch();
        setReasoningActive(false);
        act().clearStreaming();
        if (act().status !== "streaming") act().setStatus("streaming");
        scrollToBottom();
      },
      thinking_done: () => { touch(); },

      tool_call: (d) => {
        touch();
        setReasoningActive(false);
        const toolName = String(d.tool || "");
        act().addToolCall({
          id: toolName, tool: toolName,
          arguments: (d.arguments as Record<string, string>) ?? {},
          status: "running", timestamp: Date.now(),
        });
        scrollToBottom();
      },

      tool_result: (d) => {
        touch();
        const toolName = String(d.tool || "");
        pendingProgressRef.current.delete(toolName);
        act().updateToolCall(toolName, {
          status: d.status === "ok" ? "ok" : "error",
          preview: String(d.preview || ""),
          elapsed_ms: Number(d.elapsed_ms || 0),
          elapsed_s: undefined,
          progress: undefined,
        });
        if (toolName === "run_swarm") {
          const fallback = buildSwarmStatusFromToolResultPreview(String(d.preview || ""));
          if (fallback && !act().messages.some((m) => m.type === "swarm_status" && m.swarmRunId === fallback.runId)) {
            act().upsertSwarmStatus(fallback);
          }
        }
      },

      tool_heartbeat: (d) => {
        touch();
        if (act().status !== "streaming") act().setStatus("streaming");
        const toolName = String(d.tool || "");
        if (!toolName) return;
        act().updateToolCall(toolName, {
          elapsed_s: Number(d.elapsed_s || 0),
        });
      },

      tool_progress: (d) => {
        touch();
        const toolName = String(d.tool || "");
        if (!toolName) return;
        const payload: NonNullable<ToolCallEntry["progress"]> = {};
        if (typeof d.stage === "string" && d.stage) payload.stage = d.stage;
        if (typeof d.message === "string" && d.message) payload.message = d.message;
        if (typeof d.current === "number") payload.current = d.current;
        if (typeof d.total === "number") payload.total = d.total;
        pendingProgressRef.current.set(toolName, payload);
        if (progressRafRef.current) return;
        progressRafRef.current = requestAnimationFrame(() => {
          progressRafRef.current = 0;
          const pending = pendingProgressRef.current;
          if (pending.size === 0) return;
          const store = act();
          for (const [tool, progress] of pending) {
            store.updateToolCall(tool, { progress });
          }
          pending.clear();
        });
      },

      compact: () => { touch(); },

      "attempt.created": () => {
        touch();
        if (act().status !== "streaming") act().setStatus("streaming");
      },

      "attempt.started": () => {
        touch();
        if (act().status !== "streaming") act().setStatus("streaming");
      },

      "attempt.completed": async (d) => {
        touch();
        setReasoningActive(false);
        const s = act();
        const completedTools = s.toolCalls;
        if (completedTools.length > 0) {
          for (const tc of completedTools) {
            s.addMessage({ id: tc.id + "_call", type: "tool_call", content: "", tool: tc.tool, args: tc.arguments, status: tc.status || "ok", timestamp: tc.timestamp });
            if (tc.elapsed_ms != null) {
              s.addMessage({ id: "", type: "tool_result", content: tc.preview || "", tool: tc.tool, status: tc.status || "ok", elapsed_ms: tc.elapsed_ms, timestamp: tc.timestamp + 1 });
            }
          }
        }

        s.clearStreaming();

        const runDir = String(d.run_dir || "");
        const runId = runDir ? runDir.split(/[/\\]/).pop() : undefined;
        const summary = String(d.summary || "");
        if (summary) s.addMessage({ id: "", type: "answer", content: summary, timestamp: Date.now() });

        const shadowCall = completedTools.find(
          (tc) => tc.tool === "render_shadow_report" && (tc.status || "ok") === "ok",
        );
        const shadowMatch = shadowCall?.preview?.match(/"shadow_id"\s*:\s*"(shadow_[A-Za-z0-9_]+)"/);
        const shadowId = shadowMatch?.[1];

        if (runId) {
          let runMetrics: Record<string, number> | undefined;
          let runCurve: Array<{ time: string; equity: number }> | undefined;
          let showCard = false;
          try {
            const runData = await api.getRun(runId);
            if (isReportWorthyRun(runData)) {
              runMetrics = runData.metrics;
              runCurve = runData.equity_curve?.map(e => ({ time: e.time, equity: Number(e.equity) }));
              showCard = true;
            }
          } catch {
            showCard = true;
          }
          if (showCard || shadowId) {
            s.addMessage({
              id: "", type: "run_complete", content: "", runId,
              metrics: showCard ? runMetrics : undefined,
              equityCurve: showCard ? runCurve : undefined,
              shadowId,
              timestamp: Date.now(),
            });
          }
        } else if (shadowId) {
          s.addMessage({ id: "", type: "run_complete", content: "", shadowId, timestamp: Date.now() });
        }

        s.setStatus("idle");
        useAgentStore.setState({ toolCalls: [] });
        scrollToBottom();
      },

      "attempt.failed": (d) => {
        touch();
        setReasoningActive(false);
        act().clearStreaming();
        act().addMessage({ id: "", type: "error", content: String(d.error || "Execution failed"), timestamp: Date.now() });
        act().setStatus("idle");
        useAgentStore.setState({ toolCalls: [] });
        scrollToBottom();
      },

      "goal.created": () => {
        touch();
        loadGoalSnapshot(sid);
      },

      "swarm.started": (d) => {
        touch();
        const status = buildSwarmStatusFromStarted(d);
        if (!status) return;
        act().upsertSwarmStatus(status);
        scrollToBottom();
      },

      "swarm.event": (d) => {
        touch();
        if (act().status !== "streaming") act().setStatus("streaming");
        const runId = String(d.run_id || "");
        const event = d.event;
        if (!runId || !event) return;
        act().updateSwarmStatus(runId, (current) => applySwarmEvent(current, event));
        scrollToBottom();
      },

      "goal.evidence": () => {
        touch();
        loadGoalSnapshot(sid);
      },

      "goal.updated": (d) => {
        touch();
        const snapshot = d.snapshot as GoalSnapshot | undefined;
        const goal = (d.goal as GoalSnapshot["goal"] | undefined) ?? snapshot?.goal;
        if (goal && isTerminalGoalStatus(goal.status)) {
          setGoalSnapshot(null);
          setGoalDetailsOpen(false);
          setGoalEditActive(false);
          return;
        }
        if (snapshot) {
          setGoalSnapshot(snapshot);
          return;
        }
        loadGoalSnapshot(sid);
      },

      "mandate.proposal": (d) => {
        touch();
        const proposal = d as unknown as MandateProposal;
        if (!proposal.proposal_id || !Array.isArray(proposal.profiles)) return;
        setLiveItems((items) => [...items, { kind: "proposal", timestamp: Date.now(), proposal }]);
        scrollToBottom();
      },

      "mandate.committed": (d) => {
        touch();
        const committed = d as unknown as MandateCommitted;
        if (!committed.proposal_id) return;
        setCommittedMandates((prev) => ({ ...prev, [committed.proposal_id as string]: committed }));
        setLiveStatusRefresh((n) => n + 1);
        scrollToBottom();
      },

      "live.halted": (d) => {
        touch();
        const halted = d as unknown as LiveHalted;
        setLiveHalted(halted);
        setLiveStatusRefresh((n) => n + 1);
        toast.warning(t('agent.connectorHalted'));
      },

      "live.resumed": (d) => {
        touch();
        void d;
        setLiveHalted(null);
        setLiveStatusRefresh((n) => n + 1);
        toast.success(t('agent.connectionRestored'));
      },

      "live.action": (d) => {
        touch();
        const action = d as unknown as LiveAction;
        if (!action.kind) return;
        setLiveItems((items) => [...items, { kind: "live_action", timestamp: Date.now(), action }]);
        if (action.kind === "halt_tripped") setLiveHalted({ broker: action.broker, reason: action.intent_normalized });
        if (action.kind === "halt_cleared") setLiveHalted(null);
        if (["mandate_committed", "halt_tripped", "halt_cleared"].includes(action.kind)) {
          setLiveStatusRefresh((n) => n + 1);
        }
        scrollToBottom();
      },

      heartbeat: () => {},
      reconnect: (d) => { act().setSseStatus("reconnecting", Number(d.attempt ?? 0)); },
    });
  }, [connect, disconnect, loadGoalSnapshot, scrollToBottom, setCommittedMandates, setGoalDetailsOpen, setGoalEditActive, setGoalSnapshot, setLiveHalted, setLiveItems, setLiveStatusRefresh, setReasoningActive, t]);

  const refreshLiveStatus = useCallback(async () => {
    try {
      const next = await api.getLiveStatus();
      setLiveStatus(next);
      setLiveHalted((current) => (
        current && !haltScopeStillActive(current, next) ? null : current
      ));
      setLiveStatusUnavailable(false);
    } catch (error) {
      if (error instanceof ApiError && (error.status === 404 || error.status === 501)) {
        setLiveStatus(null);
        setLiveStatusUnavailable(true);
      }
    }
  }, [setLiveHalted, setLiveStatus, setLiveStatusUnavailable]);

  useEffect(() => {
    refreshLiveStatus();
    const timer = setInterval(refreshLiveStatus, LIVE_STATUS_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [refreshLiveStatus]);

  useEffect(() => {
    api.getLLMSettings().then((s) => {
      sseTimeoutMsRef.current = s.sse_timeout_seconds * 1000;
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (status !== "streaming") return;
    lastEventRef.current = Date.now();
    const timer = setInterval(() => {
      if (lastEventRef.current && Date.now() - lastEventRef.current > sseTimeoutMsRef.current && act().status === "streaming") {
        setReasoningActive(false);
        act().setStatus("idle");
        toast.warning(t('agent.executionTimedOut'));
      }
    }, 10_000);
    return () => clearInterval(timer);
  }, [status, setReasoningActive, t]);

  return {
    setupSSE,
    loadSessionMessages,
    refreshSessionMessages,
    syncCompletedAttempt,
    doDisconnect,
    refreshLiveStatus,
  };
}
