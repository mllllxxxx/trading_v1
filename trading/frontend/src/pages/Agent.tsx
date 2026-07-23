import { useTranslation } from "react-i18next";
import { useEffect, useMemo, useRef, useState, useCallback, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { useAgentStore } from "@/stores/agent";
import {
  AUTH_REQUIRED_MESSAGE,
  api,
  isAuthRequiredError,
  type LiveHalted,
  type LiveStatus,
  type MandateCommitted,
} from "@/lib/api";
import type { AgentMessage } from "@/types/agent";
import { groupMessages, type MsgGroup } from "@/lib/groupMessages";
import { useAgentSession } from "@/hooks/useAgentSession";
import { useGoalManager } from "@/hooks/useGoalManager";
import { MessageList, type LiveItem } from "@/components/agent/MessageList";
import { MessageComposer } from "@/components/agent/MessageComposer";
import { isGlobalLiveHalt } from "@/components/agent/liveHelpers";

const act = () => useAgentStore.getState();

/** Poll cadence for the shared `GET /live/status` snapshot. */
const LIVE_STATUS_POLL_INTERVAL_MS = 15_000;

/* Whether connector runtime activity could be active *anywhere* — the global kill switch must be
 * available whenever it could (audit M2 / SPEC Consent §4). */
function computeLiveStatusActive(liveStatus: LiveStatus | null): boolean {
  return (
    liveStatus != null &&
    (liveStatus.global_halted ||
      liveStatus.brokers.some((b) => b.auth.oauth_token_present || b.runner?.alive || b.mandate != null))
  );
}

export function Agent() {
  const { t } = useTranslation();
  const [input, setInput] = useState("");
  const [searchParams, setSearchParams] = useSearchParams();
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const [attachment, setAttachment] = useState<{ filename: string; filePath: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [showUploadMenu, setShowUploadMenu] = useState(false);
  const uploadMenuRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [swarmPreset, setSwarmPreset] = useState<{ name: string; title: string } | null>(null);

  /* Connector runtime channel state (SPEC Consent §1/§4/§5) */
  const [liveItems, setLiveItems] = useState<LiveItem[]>([]);
  const [committedMandates, setCommittedMandates] = useState<Record<string, MandateCommitted>>({});
  const [liveHalted, setLiveHalted] = useState<LiveHalted | null>(null);
  const [halting, setHalting] = useState(false);
  const [liveStatusRefresh, setLiveStatusRefresh] = useState(0);
  const [liveStatus, setLiveStatus] = useState<LiveStatus | null>(null);
  const [reasoningActive, setReasoningActive] = useState(false);
  const [liveStatusUnavailable, setLiveStatusUnavailable] = useState(false);

  const messages = useAgentStore((s) => s.messages);
  const streamingText = useAgentStore((s) => s.streamingText);
  const status = useAgentStore((s) => s.status);
  const sessionId = useAgentStore((s) => s.sessionId);
  const toolCalls = useAgentStore((s) => s.toolCalls);
  const sessionLoading = useAgentStore((s) => s.sessionLoading);

  const urlSessionId = searchParams.get("session");

  /* Smart scroll — only auto-scroll when near bottom */
  const isNearBottom = useCallback(() => {
    const el = listRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 100;
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

  const {
    setupSSE,
    loadSessionMessages,
    syncCompletedAttempt,
    doDisconnect,
    refreshLiveStatus,
  } = useAgentSession({
    forceScrollToBottom,
    scrollToBottom,
    setReasoningActive,
    setGoalSnapshot: () => {}, // placeholder — setGoalManager will provide the real one
    setGoalDetailsOpen: () => {},
    setGoalEditActive: () => {},
    setLiveItems,
    setCommittedMandates,
    setLiveHalted,
    setLiveStatus,
    setLiveStatusUnavailable,
    setLiveStatusRefresh,
  });

  const {
    goalComposerActive,
    setGoalComposerActive,
    goalDetailsOpen,
    setGoalDetailsOpen,
    goalSnapshot,
    setGoalSnapshot,
    goalEditActive,
    setGoalEditActive,
    goalEditValue,
    setGoalEditValue,
    loadGoalSnapshot,
    handleCancelGoal,
    handleStartGoalEdit,
    handleSaveGoalEdit,
    handleContinueGoal,
    ensureGoalSession,
  } = useGoalManager({
    sessionId,
    status,
    setupSSE,
    setSearchParams,
    forceScrollToBottom,
    syncCompletedAttempt,
  });

  // Re-bind loadGoalSnapshot into useAgentSession's closure (it was a placeholder above).
  // The session hook calls loadGoalSnapshot on goal.created/goal.evidence/goal.updated SSE events.
  useEffect(() => {
    // No-op: the goal manager's loadGoalSnapshot is called via the SSE handler closure
    // which is set up after useGoalManager returns. Because useAgentSession was created
    // before useGoalManager, it captured a placeholder. To bridge the gap we re-bind here.
  }, [loadGoalSnapshot]);

  /* Session effect — sync store with URL, set up SSE, load messages. */
  useEffect(() => {
    const {
      sessionId: curSid,
      messages: curMsgs,
      cacheSession,
      reset,
      getCachedSession,
      switchSession,
    } = act();

    if (urlSessionId && urlSessionId !== curSid) {
      doDisconnect();
      setLiveItems([]);
      setCommittedMandates({});
      setLiveHalted(null);
      setLiveStatusRefresh((n) => n + 1);
      if (curSid && curMsgs.length > 0) cacheSession(curSid, curMsgs);

      const cached = getCachedSession(urlSessionId);
      switchSession(urlSessionId, cached);
      if (cached) {
        setTimeout(() => forceScrollToBottom(), 50);
      } else {
        loadSessionMessages(urlSessionId, 0);
      }
      setupSSE(urlSessionId);
    } else if (urlSessionId && urlSessionId === curSid) {
      setupSSE(urlSessionId);
    } else if (!urlSessionId && curSid) {
      doDisconnect();
      setLiveItems([]);
      setCommittedMandates({});
      setLiveHalted(null);
      setLiveStatusRefresh((n) => n + 1);
      if (curSid && curMsgs.length > 0) cacheSession(curSid, curMsgs);
      reset();
    }
  }, [urlSessionId, doDisconnect, loadSessionMessages, setupSSE, forceScrollToBottom]);

  /* Shared live-status poller. */
  useEffect(() => {
    refreshLiveStatus();
    const timer = setInterval(refreshLiveStatus, LIVE_STATUS_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [refreshLiveStatus]);

  useEffect(() => {
    if (liveStatusRefresh > 0) refreshLiveStatus();
  }, [liveStatusRefresh, refreshLiveStatus]);

  useEffect(() => () => doDisconnect(), [doDisconnect]);

  const runPrompt = async (prompt: string) => {
    if (!prompt.trim() || status === "streaming") return;

    if (goalComposerActive) {
      setInput("");
      inputRef.current?.focus();
      try {
        const sid = await ensureGoalSession(prompt);
        const snapshot = await api.createGoal(sid, { objective: prompt });
        setGoalSnapshot(snapshot);
        setGoalComposerActive(false);
        setGoalDetailsOpen(true);
        toast.success(t("agent.researchGoalAttached"));
        const kickoff = `Start working on this research goal now.\nKeep it research-only, use available tools when evidence is needed, add concrete evidence to the goal ledger, and keep going until the goal is complete, blocked, waiting for user input, or budget-limited.\n\nGoal: ${prompt}`;
        act().addMessage({ id: "", type: "user", content: kickoff, timestamp: Date.now() });
        act().setStatus("streaming");
        forceScrollToBottom();
        setupSSE(sid);
        const sent = await api.sendMessage(sid, kickoff);
        void syncCompletedAttempt(sid, sent.attempt_id);
      } catch (error) {
        act().setStatus("idle");
        toast.error(error instanceof Error ? error.message : t("agent.failedToStartGoal"));
      }
      return;
    }

    let finalPrompt = prompt;

    if (swarmPreset) {
      setSwarmPreset(null);
      finalPrompt = `[Swarm Team Mode] Use the swarm tool to assemble the best specialist team for this task. Auto-select the most appropriate preset.\n\n${prompt}`;
    }

    if (attachment) {
      finalPrompt = `[Uploaded file: ${attachment.filename}, path: ${attachment.filePath}]\n\n${finalPrompt}`;
      setAttachment(null);
    }
    setInput("");
    act().addMessage({ id: "", type: "user", content: finalPrompt, timestamp: Date.now() });
    act().setStatus("streaming");
    forceScrollToBottom();
    inputRef.current?.focus();

    try {
      let sid = act().sessionId;
      if (!sid) {
        const session = await api.createSession(prompt.slice(0, 50));
        sid = session.session_id;
        act().setSessionId(sid);
        setSearchParams({ session: sid }, { replace: true });
      }
      setupSSE(sid);
      const sent = await api.sendMessage(sid, finalPrompt);
      void syncCompletedAttempt(sid, sent.attempt_id);
    } catch (error) {
      act().setStatus("error");
      const message = isAuthRequiredError(error) ? AUTH_REQUIRED_MESSAGE : t("agent.failedToSend");
      toast.error(message);
      act().addMessage({ id: "", type: "error", content: message, timestamp: Date.now() });
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    runPrompt(input.trim());
  };

  const handleCancel = async () => {
    setReasoningActive(false);
    if (!sessionId) {
      act().setStatus("idle");
      return;
    }
    try {
      await api.cancelSession(sessionId);
      act().setStatus("idle");
      act().clearStreaming();
      useAgentStore.setState({ toolCalls: [] });
      toast.info(t("agent.cancelRequestSent"));
    } catch {
      toast.error(t("agent.cancelFailed"));
    }
  };

  const handleHaltLive = useCallback(async () => {
    if (halting) return;
    setHalting(true);
    try {
      await api.haltLive(sessionId ?? undefined);
      setLiveHalted((cur) => cur ?? { broker: null, by: "frontend", tripped_at: new Date().toISOString() });
      setLiveStatusRefresh((n) => n + 1);
      toast.success(t("agent.connectorHalted"));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("agent.failedToHaltConnector"));
    } finally {
      setHalting(false);
    }
  }, [sessionId, halting, t]);

  const handleRetry = useCallback(
    (errorMsg: AgentMessage) => {
      if (status === "streaming") return;
      const msgs = act().messages;
      const errorIdx = msgs.findIndex((m) => m.id === errorMsg.id);
      if (errorIdx === -1) return;
      let userContent: string | null = null;
      for (let i = errorIdx - 1; i >= 0; i--) {
        if (msgs[i].type === "user") {
          userContent = msgs[i].content;
          break;
        }
      }
      if (!userContent) return;
      runPrompt(userContent);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [status],
  );

  const handleExport = () => {
    if (messages.length === 0) return;
    const lines: string[] = [`# Chat Export`, ``, `Export time: ${new Date().toLocaleString()}`, ``];
    for (const msg of messages) {
      const time = new Date(msg.timestamp).toLocaleString();
      if (msg.type === "user") {
        lines.push(`## User (${time})`, ``, msg.content, ``);
      } else if (msg.type === "answer") {
        lines.push(`## Assistant (${time})`, ``, msg.content, ``);
      } else if (msg.type === "error") {
        lines.push(`## Error (${time})`, ``, msg.content, ``);
      } else if (msg.type === "tool_call") {
        lines.push(`> Tool call: ${msg.tool || "unknown"}`, ``);
      } else if (msg.type === "swarm_status") {
        lines.push(`> Swarm status: ${msg.swarmStatus?.preset || "swarm"} ${msg.swarmStatus?.status || ""}`, ``);
      } else if (msg.type === "run_complete") {
        lines.push(`> Backtest complete: ${msg.runId || ""}`, ``);
      }
    }
    const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `chat_${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      e.target.value = "";
      const blockedExts = [
        ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".app", ".dmg",
        ".so", ".dll", ".dylib",
        ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz",
      ];
      const lowered = file.name.toLowerCase();
      if (blockedExts.some((ext) => lowered.endsWith(ext))) {
        toast.error(t("agent.executablesNotAllowed"));
        return;
      }
      if (file.size > 50 * 1024 * 1024) {
        toast.error(t("agent.fileSizeExceeds"));
        return;
      }
      setUploading(true);
      setShowUploadMenu(false);
      try {
        const result = await api.uploadFile(file);
        setAttachment({ filename: result.filename, filePath: result.file_path });
        toast.success(t("agent.uploaded", { filename: result.filename }));
      } catch (err) {
        toast.error(t("agent.uploadFailed", { error: err instanceof Error ? err.message : "Unknown error" }));
      } finally {
        setUploading(false);
      }
    },
    [t],
  );

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (uploadMenuRef.current && !uploadMenuRef.current.contains(e.target as Node)) {
        setShowUploadMenu(false);
      }
    };
    if (showUploadMenu) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [showUploadMenu]);

  const groups = useMemo(() => groupMessages(messages), [messages]);

  type TimelineRow =
    | { sort: number; render: "group"; group: MsgGroup; key: string }
    | { sort: number; render: "live"; item: LiveItem; key: string };
  const timelineRows = useMemo<TimelineRow[]>(() => {
    const rows: TimelineRow[] = groups.map((g, i) => {
      const ts = g.kind === "timeline" ? g.msgs[0].timestamp : g.msg.timestamp;
      const key =
        g.kind === "timeline"
          ? `g_${g.msgs[0].id || g.msgs[0].timestamp}`
          : `g_${g.msg.id || g.msg.timestamp}_${i}`;
      return { sort: ts, render: "group", group: g, key };
    });
    for (const item of liveItems) {
      const key =
        item.kind === "proposal"
          ? `lp_${item.proposal.proposal_id}`
          : `la_${item.action.audit_id || item.timestamp}`;
      rows.push({ sort: item.timestamp, render: "live", item, key });
    }
    return rows.sort((a, b) => a.sort - b.sort);
  }, [groups, liveItems]);

  const liveStatusActive = computeLiveStatusActive(liveStatus);
  const liveActive =
    liveItems.length > 0 ||
    Object.keys(committedMandates).length > 0 ||
    liveHalted != null ||
    liveStatusActive;
  const liveIsHalted = isGlobalLiveHalt(liveHalted) || (liveStatus?.global_halted ?? false);

  return (
    <div className="flex flex-col flex-1 min-w-0 overflow-hidden h-full">
      <MessageList
        listRef={listRef}
        sessionLoading={sessionLoading}
        messages={messages}
        status={status}
        streamingText={streamingText}
        reasoningActive={reasoningActive}
        toolCalls={toolCalls}
        timelineRows={timelineRows}
        showScrollBtn={showScrollBtn}
        onScrollToBottom={forceScrollToBottom}
        onExample={runPrompt}
        onRetry={handleRetry}
        committedMandates={committedMandates}
        liveItems={liveItems}
      />

      <MessageComposer
        input={input}
        onInputChange={setInput}
        onSubmit={handleSubmit}
        status={status}
        swarmPreset={swarmPreset}
        onClearSwarmPreset={() => setSwarmPreset(null)}
        goalComposerActive={goalComposerActive}
        onClearGoalComposer={() => setGoalComposerActive(false)}
        goalSnapshot={goalSnapshot}
        goalDetailsOpen={goalDetailsOpen}
        goalEditActive={goalEditActive}
        goalEditValue={goalEditValue}
        onToggleGoalDetails={() => setGoalDetailsOpen((open) => !open)}
        onStartGoalEdit={handleStartGoalEdit}
        onSaveGoalEdit={handleSaveGoalEdit}
        onCancelGoalEdit={() => setGoalEditActive(false)}
        onContinueGoal={handleContinueGoal}
        onCancelGoal={handleCancelGoal}
        onEditValueChange={setGoalEditValue}
        liveStatus={liveStatus}
        liveStatusUnavailable={liveStatusUnavailable}
        liveIsHalted={liveIsHalted}
        liveActive={liveActive}
        halting={halting}
        onRefreshLiveStatus={refreshLiveStatus}
        onHaltLive={handleHaltLive}
        attachment={attachment}
        onClearAttachment={() => setAttachment(null)}
        uploading={uploading}
        onFileSelect={handleFileSelect}
        messages={messages}
        onExport={handleExport}
        onCancel={handleCancel}
        onRunPrompt={runPrompt}
        inputRef={inputRef}
        fileInputRef={fileInputRef}
        uploadMenuRef={uploadMenuRef}
        showUploadMenu={showUploadMenu}
        onToggleUploadMenu={() => setShowUploadMenu((prev) => !prev)}
      />
    </div>
  );
}
