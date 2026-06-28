import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  Send,
  Loader2,
  Square,
  Plus,
  Paperclip,
  X,
  Users,
  Target,
  ChevronDown,
  MessageSquare,
  Trash2,
  ArrowDown,
  Landmark,
} from "lucide-react";
import { toast } from "sonner";
import { useAgentStore } from "@/stores/agent";
import { useSSE } from "@/hooks/useSSE";
import {
  ApiError,
  AUTH_REQUIRED_MESSAGE,
  api,
  isAuthRequiredError,
  type GoalSnapshot,
  type MandateCommitted,
  type LiveAction,
  type SessionItem,
} from "@/lib/api";
import { isReportWorthyRun } from "@/lib/runReports";
import type { AgentMessage } from "@/types/agent";
import { AgentAvatar } from "@/components/chat/AgentAvatar";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { ThinkingTimeline } from "@/components/chat/ThinkingTimeline";
import { ToolProgressIndicator } from "@/components/chat/ToolProgressIndicator";
import { MandateProposalCard } from "@/components/chat/MandateProposalCard";
import { SwarmStatusCard } from "@/components/chat/SwarmStatusCard";
import {
  buildSwarmStatusFromToolResultPreview,
} from "@/lib/swarmStatus";
import { cn } from "@/components/terminal/primitives";

type MsgGroup =
  | { kind: "single"; msg: AgentMessage }
  | { kind: "timeline"; msgs: AgentMessage[] };

function groupMessages(msgs: AgentMessage[]): MsgGroup[] {
  const out: MsgGroup[] = [];
  let buf: AgentMessage[] = [];
  const flush = () => {
    if (buf.length) {
      out.push({ kind: "timeline", msgs: [...buf] });
      buf = [];
    }
  };
  for (const m of msgs) {
    if (["thinking", "tool_call", "tool_result", "compact"].includes(m.type)) {
      buf.push(m);
    } else {
      flush();
      out.push({ kind: "single", msg: m });
    }
  }
  flush();
  return out;
}

const act = () => useAgentStore.getState();

const LIVE_STATUS_POLL_INTERVAL_MS = 15_000;
const CONNECTOR_CHECK_PROMPT =
  "List my trading connector profiles, show which one is selected, then check that selected connector. If it is not ready, tell me exactly what setup step is missing. Do not place or modify orders.";

interface ProposalItem {
  kind: "proposal";
  timestamp: number;
  proposal: any;
}
interface LiveActionItem {
  kind: "live_action";
  timestamp: number;
  action: LiveAction;
}
type LiveItem = ProposalItem | LiveActionItem;

function getGoalProgress(snapshot: GoalSnapshot | null) {
  const total = snapshot?.criteria.length ?? 0;
  const met = snapshot?.criteria.filter((c) => c.status === "complete" || c.status === "satisfied").length ?? 0;
  const evidenceTotal = snapshot?.evidence_count ?? 0;
  return {
    met,
    total,
    label: total > 0 ? `${met}/${total}` : "",
    metLabel: total > 0 ? `${met}/${total} met` : "",
    evidenceTotal,
  };
}

export function AgentChatConsole() {
  const { t } = useTranslation();
  const [input, setInput] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sseSessionRef = useRef<string | null>(null);
  const prevSseStatusRef = useRef<string>("disconnected");
  const genRef = useRef(0);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const lastEventRef = useRef(0);

  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [showSessionDropdown, setShowSessionDropdown] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);

  const [attachment, setAttachment] = useState<{ filename: string; filePath: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [showUploadMenu, setShowUploadMenu] = useState(false);
  const uploadMenuRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [swarmPreset, setSwarmPreset] = useState<{ name: string; title: string } | null>(null);
  const [goalComposerActive, setGoalComposerActive] = useState(false);
  const [goalDetailsOpen, setGoalDetailsOpen] = useState(false);
  const [goalSnapshot, setGoalSnapshot] = useState<GoalSnapshot | null>(null);

  const [liveItems, setLiveItems] = useState<LiveItem[]>([]);
  const [committedMandates] = useState<Record<string, MandateCommitted>>({});
  const [reasoningActive, setReasoningActive] = useState(false);
  const [liveStatusUnavailable, setLiveStatusUnavailable] = useState(false);

  const messages = useAgentStore((s) => s.messages);
  const streamingText = useAgentStore((s) => s.streamingText);
  const status = useAgentStore((s) => s.status);
  const sessionId = useAgentStore((s) => s.sessionId);
  const toolCalls = useAgentStore((s) => s.toolCalls);
  const sessionLoading = useAgentStore((s) => s.sessionLoading);

  const { connect, disconnect, onStatusChange } = useSSE();

  const isNearBottom = useCallback(() => {
    const el = listRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  }, []);

  const rafRef = useRef(0);
  const scrollToBottom = useCallback(() => {
    if (!isNearBottom()) {
      setShowScrollBtn(true);
      return;
    }
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => {
      if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
    });
  }, [isNearBottom]);

  const forceScrollToBottom = useCallback(() => {
    setShowScrollBtn(false);
    requestAnimationFrame(() => {
      if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
    });
  }, []);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const onScroll = () => {
      if (isNearBottom()) setShowScrollBtn(false);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [isNearBottom]);

  useEffect(() => {
    onStatusChange((s) => {
      act().setSseStatus(s);
      if (s === "reconnecting" && prevSseStatusRef.current === "connected") {
        toast.warning("Connection lost. Reconnecting...");
      } else if (s === "connected" && prevSseStatusRef.current === "reconnecting") {
        toast.success("Connection restored");
      }
      prevSseStatusRef.current = s;
    });
  }, [onStatusChange]);

  const loadGoalSnapshot = useCallback(async (sid?: string | null) => {
    const targetSession = sid || act().sessionId;
    if (!targetSession) {
      setGoalSnapshot(null);
      setGoalDetailsOpen(false);
      return;
    }
    try {
      const snap = await api.getGoal(targetSession);
      if (act().sessionId !== targetSession) return;
      setGoalSnapshot(snap);
    } catch (err) {
      if (act().sessionId !== targetSession) return;
      if (err instanceof ApiError && err.status === 404) {
        setGoalSnapshot(null);
        setGoalDetailsOpen(false);
      }
    }
  }, []);

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
          let fetchedMetrics: Record<string, number> | undefined;
          let fetchedCurve: any[] | undefined;
          let showCard = true;
          try {
            const runData = await api.getRun(runId);
            if (isReportWorthyRun(runData)) {
              fetchedMetrics = runData.metrics;
              fetchedCurve = runData.equity_curve?.map((e) => ({ time: e.time, equity: Number(e.equity) }));
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
              metrics: fetchedMetrics || metrics,
              equityCurve: fetchedCurve,
              timestamp: ts + 1,
            });
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
    for (let i = 0; i < 4; i++) {
      try {
        const stored = await api.getSessionMessages(sid);
        const completed = stored.some(
          (m) => m.role === "assistant" && m.linked_attempt_id === attemptId
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
      await new Promise<void>((r) => setTimeout(r, 1000));
    }
    return false;
  }, [refreshSessionMessages]);

  const setupSSE = useCallback((sid: string) => {
    if (sseSessionRef.current === sid) return;
    disconnect();
    sseSessionRef.current = sid;
    const touch = () => {
      lastEventRef.current = Date.now();
    };

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
      thinking_done: () => {
        touch();
      },
      tool_call: (d) => {
        touch();
        setReasoningActive(false);
        const name = String(d.tool || "");
        act().addToolCall({
          id: name,
          tool: name,
          arguments: (d.arguments as Record<string, string>) ?? {},
          status: "running",
          timestamp: Date.now(),
        });
        scrollToBottom();
      },
      tool_result: (d) => {
        touch();
        const name = String(d.tool || "");
        act().updateToolCall(name, {
          status: d.status === "ok" ? "ok" : "error",
          preview: String(d.preview || ""),
          elapsed_ms: Number(d.elapsed_ms || 0),
        });
        if (name === "run_swarm") {
          const fallback = buildSwarmStatusFromToolResultPreview(String(d.preview || ""));
          if (fallback && !act().messages.some((m) => m.type === "swarm_status" && m.swarmRunId === fallback.runId)) {
            act().upsertSwarmStatus(fallback);
          }
        }
        scrollToBottom();
      },
      swarm_event: () => {
        touch();
        scrollToBottom();
      },
      live_action: (d) => {
        touch();
        setLiveItems((prev) => [...prev, { kind: "live_action", timestamp: Date.now(), action: d.action as LiveAction }]);
        scrollToBottom();
      },
      mandate_proposal: (d) => {
        touch();
        setLiveItems((prev) => [...prev, { kind: "proposal", timestamp: Date.now(), proposal: d.proposal }]);
        scrollToBottom();
      },
      run_complete: (d) => {
        touch();
        const runId = String(d.run_id || "");
        const metrics = (d.metrics as Record<string, number>) ?? {};
        act().addMessage({
          id: `run_${runId}_${Date.now()}`,
          type: "run_complete",
          content: "",
          runId,
          metrics,
          timestamp: Date.now(),
        });
        scrollToBottom();
      },
    });
  }, [connect, disconnect, scrollToBottom]);

  const selectSession = useCallback((sid: string) => {
    setShowSessionDropdown(false);
    act().switchSession(sid);
    setupSSE(sid);
    refreshSessionMessages(sid);
    loadGoalSnapshot(sid);
  }, [setupSSE, refreshSessionMessages, loadGoalSnapshot]);

  const loadSessions = useCallback(async () => {
    try {
      const list = await api.listSessions();
      setSessions(Array.isArray(list) ? list : []);
      if (list.length > 0 && !act().sessionId) {
        selectSession(list[0].session_id);
      }
    } catch {
      // ignore
    }
  }, [selectSession]);

  const handleCreateSession = useCallback(async () => {
    if (creatingSession) return;
    setCreatingSession(true);
    try {
      const s = await api.createSession(t("layout.newChat", "New Chat"));
      toast.success("New chat session created");
      await loadSessions();
      selectSession(s.session_id);
    } catch {
      toast.error("Failed to create chat session");
    } finally {
      setCreatingSession(false);
    }
  }, [creatingSession, loadSessions, selectSession, t]);

  const handleDeleteSession = useCallback(async (sid: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await api.deleteSession(sid);
      toast.success("Session deleted");
      const filtered = sessions.filter((s) => s.session_id !== sid);
      setSessions(filtered);
      if (act().sessionId === sid) {
        if (filtered.length > 0) selectSession(filtered[0].session_id);
        else act().reset();
      }
    } catch {
      toast.error("Failed to delete session");
    }
  }, [sessions, selectSession]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const runPrompt = useCallback(async (val: string) => {
    let activeSid = act().sessionId;
    if (!activeSid) {
      try {
        const s = await api.createSession("New Chat");
        activeSid = s.session_id;
        act().setSessionId(activeSid);
        await loadSessions();
      } catch {
        toast.error("Could not initialize session");
        return;
      }
    }
    if (!activeSid || status === "streaming") return;

    let payload = val;
    if (swarmPreset) {
      payload = `Use the ${swarmPreset.name} swarm preset. Objective: ${val}`;
      setSwarmPreset(null);
    } else if (goalComposerActive) {
      try {
        act().setStatus("streaming");
        act().addMessage({ id: "", type: "user", content: `Create research goal: ${val}`, timestamp: Date.now() });
        const res = await api.createGoal(activeSid, { objective: val });
        setGoalSnapshot(res);
        setGoalComposerActive(false);
        act().setStatus("idle");
        await refreshSessionMessages(activeSid);
        return;
      } catch {
        act().setStatus("idle");
        toast.error("Failed to create goal");
        return;
      }
    }

    if (attachment) {
      payload = `[Uploaded file: ${attachment.filename}, path: ${attachment.filePath}]\n\n${payload}`;
      setAttachment(null);
    }

    act().addMessage({ id: "", type: "user", content: payload, timestamp: Date.now() });
    act().setStatus("streaming");
    setInput("");
    setTimeout(() => forceScrollToBottom(), 50);

    try {
      setupSSE(activeSid);
      const sent = await api.sendMessage(activeSid, payload);
      await syncCompletedAttempt(activeSid, sent.attempt_id);
    } catch (err) {
      act().setStatus("error");
      const msg = isAuthRequiredError(err) ? AUTH_REQUIRED_MESSAGE : "Failed to run prompt";
      toast.error(msg);
      act().addMessage({ id: "", type: "error", content: msg, timestamp: Date.now() });
    }
  }, [status, swarmPreset, goalComposerActive, attachment, setupSSE, syncCompletedAttempt, refreshSessionMessages, loadSessions, forceScrollToBottom]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() && !attachment) return;
    runPrompt(input.trim());
  };

  const handleCancel = useCallback(async () => {
    if (!sessionId) return;
    try {
      await api.cancelSession(sessionId);
      act().clearStreaming();
      act().setStatus("idle");
      useAgentStore.setState({ toolCalls: [] });
      setReasoningActive(false);
      toast.info("Generation cancelled");
    } catch {
      act().setStatus("idle");
    }
  }, [sessionId]);

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    if (file.size > 50 * 1024 * 1024) {
      toast.error("File exceeds 50MB limit");
      return;
    }
    setUploading(true);
    setShowUploadMenu(false);
    try {
      const result = await api.uploadFile(file);
      setAttachment({ filename: result.filename, filePath: result.file_path });
      toast.success(`Attached: ${result.filename}`);
    } catch {
      toast.error("File upload failed");
    } finally {
      setUploading(false);
    }
  }, []);

  const refreshLiveStatus = useCallback(async () => {
    if (liveStatusUnavailable) return;
    try {
      await api.getLiveStatus();
    } catch (err) {
      if (err instanceof ApiError && (err.status === 404 || err.status === 501)) {
        setLiveStatusUnavailable(true);
      }
    }
  }, [liveStatusUnavailable]);

  useEffect(() => {
    refreshLiveStatus();
    const t = setInterval(refreshLiveStatus, LIVE_STATUS_POLL_INTERVAL_MS);
    return () => clearInterval(t);
  }, [refreshLiveStatus]);

  const groups = useMemo(() => groupMessages(messages), [messages]);
  const goalProgress = useMemo(() => getGoalProgress(goalSnapshot), [goalSnapshot]);

  const timelineRows = useMemo<any[]>(() => {
    const rows: any[] = groups.map((g, i) => {
      const ts = g.kind === "timeline" ? g.msgs[0].timestamp : g.msg.timestamp;
      const key = g.kind === "timeline" ? `g_${g.msgs[0].id || g.msgs[0].timestamp}` : `g_${g.msg.id || g.msg.timestamp}_${i}`;
      return { sort: ts, render: "group", group: g, key };
    });
    for (const item of liveItems) {
      const key = item.kind === "proposal" ? `lp_${item.proposal.proposal_id}` : `la_${item.action.audit_id || item.timestamp}`;
      rows.push({ sort: item.timestamp, render: "live", item, key });
    }
    return rows.sort((a, b) => a.sort - b.sort);
  }, [groups, liveItems]);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-ttcc-bg text-ttcc-text text-[11px]">
      {/* Session Select Header */}
      <div className="relative flex items-center justify-between border-b border-ttcc-border bg-ttcc-surface px-2.5 py-1 shrink-0">
        <button
          type="button"
          onClick={() => setShowSessionDropdown((d) => !d)}
          className="flex items-center gap-1 font-semibold text-ttcc-text hover:text-ttcc-accent transition-colors"
        >
          <MessageSquare className="h-3 w-3 text-ttcc-blue" />
          <span className="truncate max-w-[140px]">
            {sessions.find((s) => s.session_id === sessionId)?.title || "Select Chat"}
          </span>
          <ChevronDown className="h-3 w-3 opacity-60" />
        </button>

        <button
          type="button"
          onClick={handleCreateSession}
          disabled={creatingSession}
          className="flex h-5 w-5 items-center justify-center rounded border border-ttcc-border bg-ttcc-surface-2 text-ttcc-text-secondary hover:text-ttcc-text disabled:opacity-40"
          title="New Chat"
        >
          {creatingSession ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : <Plus className="h-3 w-3" />}
        </button>

        {showSessionDropdown && (
          <div className="absolute left-2 top-full z-50 mt-1 w-60 rounded border border-ttcc-border bg-ttcc-surface-2 p-1 shadow-2xl">
            <div className="mb-1 border-b border-ttcc-border px-2 py-1 text-[9px] uppercase tracking-wider text-ttcc-text-secondary font-bold">
              Chat History
            </div>
            <div className="max-h-52 overflow-y-auto space-y-0.5">
              {sessions.map((s) => {
                const isActive = s.session_id === sessionId;
                return (
                  <button
                    key={s.session_id}
                    onClick={() => selectSession(s.session_id)}
                    className={cn(
                      "flex w-full items-center justify-between rounded px-2 py-1 text-left text-[11px]",
                      isActive ? "bg-ttcc-accent/15 text-ttcc-accent font-semibold" : "text-ttcc-text-secondary hover:bg-ttcc-surface hover:text-ttcc-text"
                    )}
                  >
                    <span className="truncate pr-4">{s.title || s.session_id.slice(0, 8)}</span>
                    <span
                      onClick={(e) => handleDeleteSession(s.session_id, e)}
                      className="text-ttcc-text-muted hover:text-ttcc-red p-0.5"
                    >
                      <Trash2 className="h-3 w-3" />
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Messages Scroll Area */}
      <div ref={listRef} className="flex-1 overflow-y-auto p-2.5 space-y-3 scroll-smooth relative">
        {sessionLoading && (
          <div className="space-y-3 py-2 animate-pulse">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex gap-2">
                <div className="h-6 w-6 rounded-full bg-ttcc-surface shrink-0" />
                <div className="flex-1 space-y-1.5">
                  <div className="h-3.5 bg-ttcc-surface rounded w-3/4" />
                  <div className="h-3 bg-ttcc-surface/60 rounded w-1/2" />
                </div>
              </div>
            ))}
          </div>
        )}

        {!sessionLoading && messages.length === 0 && (
          <div className="flex flex-col items-center justify-center text-center p-4 h-full text-ttcc-text-secondary">
            <Target className="h-7 w-7 text-ttcc-accent/30 mb-1.5" />
            <p className="font-semibold text-xs text-ttcc-text mb-0.5">AI Copilot</p>
            <p className="text-[10px] leading-relaxed max-w-[200px]">
              Type prompts to start research goals, backtest strategies, check portfolios, or command live order checks.
            </p>
          </div>
        )}

        {/* Timeline rows */}
        {!sessionLoading && timelineRows.map((row, rowIdx) => {
          if (row.render === "live") {
            if (row.item.kind === "proposal") {
              return (
                <MandateProposalCard
                  key={row.key}
                  proposal={row.item.proposal}
                  committed={committedMandates[row.item.proposal.proposal_id] ?? null}
                  onAdjust={runPrompt}
                />
              );
            }
            return (
              <div key={row.key} className="flex items-center gap-1 bg-ttcc-surface rounded p-1 text-[9px] border border-ttcc-border/40">
                <span className="h-1.5 w-1.5 rounded-full bg-ttcc-blue" />
                <span className="font-semibold uppercase tracking-wider text-ttcc-blue mr-1">ACTION</span>
                <span className="truncate text-ttcc-text-secondary">{row.item.action.outcome || row.item.action.kind}</span>
              </div>
            );
          }
          const g = row.group;
          if (g.kind === "timeline") {
            const isLast = rowIdx === timelineRows.length - 1;
            return (
              <ThinkingTimeline
                key={row.key}
                messages={g.msgs}
                isLatest={isLast && status === "streaming"}
              />
            );
          }
          const msgIdx = messages.indexOf(g.msg);
          if (g.msg.type === "swarm_status" && g.msg.swarmStatus) {
            return (
              <div key={row.key} data-msg-idx={msgIdx}>
                <SwarmStatusCard status={g.msg.swarmStatus} />
              </div>
            );
          }
          return (
            <div key={row.key} data-msg-idx={msgIdx}>
              <MessageBubble msg={g.msg} onRetry={g.msg.type === "error" ? () => runPrompt(g.msg.content) : undefined} />
            </div>
          );
        })}

        {/* Pre-stream indicator */}
        {status === "streaming" && !reasoningActive && !streamingText && toolCalls.length === 0 && (
          <div className="flex gap-1.5 text-[9px] text-ttcc-text-secondary items-center px-2 py-1 bg-ttcc-surface border border-ttcc-border/30 rounded">
            <Loader2 className="h-3 w-3 animate-spin text-ttcc-accent shrink-0" />
            <span>AI agent executing tools...</span>
          </div>
        )}

        {/* Active stream area */}
        {(streamingText || reasoningActive || (status === "streaming" && toolCalls.length > 0)) && (
          <div className="flex gap-2 border-t border-ttcc-border/20 pt-2 bg-ttcc-bg">
            <AgentAvatar />
            <div className="flex-1 min-w-0 space-y-1">
              {reasoningActive && !streamingText && (
                <div className="flex items-center gap-1 text-[9px] text-ttcc-text-secondary">
                  <Loader2 className="h-2.5 w-2.5 animate-spin text-ttcc-accent shrink-0" />
                  <span>thinking...</span>
                </div>
              )}
              {streamingText && (
                <div className="prose prose-sm dark:prose-invert max-w-none text-xs leading-normal font-sans">
                  {streamingText}
                  <span className="inline-block w-0.5 h-3 bg-ttcc-accent ml-0.5 animate-pulse" />
                </div>
              )}
              {status === "streaming" && toolCalls.length > 0 && (
                <ToolProgressIndicator toolCalls={toolCalls} />
              )}
            </div>
          </div>
        )}

        {/* Streaming pulse line */}
        {status === "streaming" && (
          <div className="flex items-center gap-1.5 pt-1 bg-ttcc-bg">
            <div className="h-0.5 flex-1 rounded-full bg-ttcc-accent/20 overflow-hidden relative">
              <div className="h-full w-1/3 bg-ttcc-accent rounded-full animate-[pulse-slide_1.8s_ease-in-out_infinite]" />
            </div>
            <span className="text-[8px] text-ttcc-text-secondary uppercase tracking-wider shrink-0 font-bold">running</span>
          </div>
        )}

        {showScrollBtn && (
          <button
            onClick={forceScrollToBottom}
            className="absolute bottom-12 left-1/2 -translate-x-1/2 flex items-center gap-1 px-2.5 py-1 rounded-full bg-ttcc-accent text-white text-[10px] font-semibold shadow-lg hover:opacity-90 transition-opacity z-10 animate-bounce"
          >
            <ArrowDown className="h-3 w-3" /> New Messages
          </button>
        )}
      </div>

      {/* Goal Details Widget */}
      {goalSnapshot && (
        <div className="border-t border-ttcc-border/65 bg-ttcc-surface p-1.5 shrink-0">
          <button
            type="button"
            onClick={() => setGoalDetailsOpen((x) => !x)}
            className="flex w-full items-center justify-between text-[9px] font-semibold uppercase tracking-wider text-ttcc-accent"
          >
            <span className="flex items-center gap-1">
              <Target className="h-3 w-3" />
              Goal: {goalProgress.metLabel}
            </span>
            <ChevronDown className={cn("h-3 w-3 transition-transform", goalDetailsOpen && "rotate-180")} />
          </button>
          {goalDetailsOpen && (
            <div className="mt-1 rounded border border-ttcc-border bg-ttcc-bg p-2 space-y-1 text-[10px]">
              <div className="font-medium text-ttcc-text">{goalSnapshot.goal.objective}</div>
              <div className="flex justify-between font-mono text-[9px] text-ttcc-text-secondary border-b border-ttcc-border/40 pb-0.5">
                <span>Criteria Met: {goalProgress.label}</span>
                <span>Evidence: {goalProgress.evidenceTotal}</span>
              </div>
              <div className="max-h-20 overflow-y-auto space-y-0.5">
                {goalSnapshot.criteria.map((c, i) => (
                  <div key={i} className="flex items-center gap-1 text-[9px]">
                    <span className={cn(
                      "h-1 w-1 rounded-full shrink-0",
                      c.status === "complete" ? "bg-ttcc-green" : "bg-ttcc-text-muted"
                    )} />
                    <span className="truncate text-ttcc-text-secondary">{c.text}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Input Console */}
      <form onSubmit={handleSubmit} className="border-t border-ttcc-border bg-ttcc-surface p-2 shrink-0">
        <div className="flex flex-col gap-1.5">
          {/* Swarm Preset Indicator */}
          {swarmPreset && (
            <div className="flex items-center justify-between rounded bg-ttcc-accent/15 px-2 py-0.5 text-[9px] text-ttcc-accent border border-ttcc-accent/30">
              <span className="flex items-center gap-1 font-semibold">
                <Users className="h-3 w-3" />
                Swarm: {swarmPreset.title}
              </span>
              <button type="button" onClick={() => setSwarmPreset(null)}>
                <X className="h-3 w-3 hover:text-ttcc-red" />
              </button>
            </div>
          )}
          {goalComposerActive && (
            <div className="flex items-center justify-between rounded bg-ttcc-blue/15 px-2 py-0.5 text-[9px] text-ttcc-blue border border-ttcc-blue/30 font-semibold font-sans">
              <span className="flex items-center gap-1">
                <Target className="h-3 w-3" />
                Define Research Goal
              </span>
              <button type="button" onClick={() => setGoalComposerActive(false)}>
                <X className="h-3 w-3 hover:text-ttcc-red" />
              </button>
            </div>
          )}

          {/* Uploading Status */}
          {uploading && (
            <div className="flex items-center gap-1 text-[9px] text-ttcc-text-secondary animate-pulse">
              <Loader2 className="h-3 w-3 animate-spin text-ttcc-accent" />
              <span>Uploading file...</span>
            </div>
          )}

          {/* Prompt box row */}
          <div className="flex items-end gap-1.5 font-sans">
            {/* Attachment "+" Menu */}
            <div className="relative shrink-0" ref={uploadMenuRef}>
              <button
                type="button"
                onClick={() => setShowUploadMenu((x) => !x)}
                className="flex h-7 w-7 items-center justify-center rounded border border-ttcc-border bg-ttcc-surface-2 text-ttcc-text-secondary hover:text-ttcc-text transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>

              {showUploadMenu && (
                <div className="absolute bottom-full left-0 z-50 mb-1 w-44 rounded border border-ttcc-border bg-ttcc-surface-2 py-1 shadow-2xl">
                  <button
                    type="button"
                    onClick={() => {
                      fileInputRef.current?.click();
                      setShowUploadMenu(false);
                    }}
                    className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-[10px] text-ttcc-text-secondary hover:bg-ttcc-surface hover:text-ttcc-text transition-colors font-medium"
                  >
                    <Paperclip className="h-3.5 w-3.5" />
                    Attach PDF file
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setSwarmPreset(null);
                      setGoalComposerActive(true);
                      setShowUploadMenu(false);
                    }}
                    className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-[10px] text-ttcc-text-secondary hover:bg-ttcc-surface hover:text-ttcc-text transition-colors font-medium"
                  >
                    <Target className="h-3.5 w-3.5" />
                    Research Goal
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setGoalComposerActive(false);
                      setSwarmPreset({ name: "auto", title: "Strategy Swarm" });
                      setShowUploadMenu(false);
                    }}
                    className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-[10px] text-ttcc-text-secondary hover:bg-ttcc-surface hover:text-ttcc-text transition-colors font-medium"
                  >
                    <Users className="h-3.5 w-3.5" />
                    Agent Swarm
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setShowUploadMenu(false);
                      runPrompt(CONNECTOR_CHECK_PROMPT);
                    }}
                    className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-[10px] text-ttcc-text-secondary hover:bg-ttcc-surface hover:text-ttcc-text border-t border-ttcc-border/40 mt-1 pt-1 font-semibold"
                  >
                    <Landmark className="h-3.5 w-3.5" />
                    Check Connector
                  </button>
                </div>
              )}
            </div>

            <input
              ref={fileInputRef}
              type="file"
              onChange={handleFileSelect}
              className="hidden"
            />

            <textarea
              ref={inputRef}
              value={input}
              rows={1}
              onChange={(e) => setInput(e.target.value)}
              onInput={(e) => {
                const el = e.target as HTMLTextAreaElement;
                el.style.height = "auto";
                el.style.height = el.scrollHeight + "px";
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  runPrompt(input.trim());
                }
              }}
              placeholder={
                goalComposerActive
                  ? "Describe research goal..."
                  : "Command AI Copilot..."
              }
              className="flex-1 min-w-0 rounded border border-ttcc-border bg-ttcc-bg px-2.5 py-1 text-xs text-ttcc-text outline-none focus:border-ttcc-accent/60 resize-none max-h-20 font-sans"
              disabled={status === "streaming"}
            />

            {status === "streaming" ? (
              <button
                type="button"
                onClick={handleCancel}
                className="flex h-7 w-7 items-center justify-center rounded bg-ttcc-red text-white hover:opacity-90 transition-opacity"
              >
                <Square className="h-3 w-3 fill-white" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim() && !attachment}
                className="flex h-7 w-7 items-center justify-center rounded bg-ttcc-accent text-white hover:opacity-90 disabled:opacity-40 transition-opacity"
              >
                <Send className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
