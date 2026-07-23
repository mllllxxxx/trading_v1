import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  ApiError,
  AUTH_REQUIRED_MESSAGE,
  api,
  isAuthRequiredError,
  type GoalSnapshot,
} from "@/lib/api";
import { useAgentStore } from "@/stores/agent";
import { goalKickoffPrompt, goalContinuePrompt } from "@/components/agent/goalHelpers";

const act = () => useAgentStore.getState();

export interface UseGoalManagerParams {
  sessionId: string | null;
  status: "idle" | "streaming" | "error";
  setupSSE: (sid: string) => void;
  setSearchParams: (params: Record<string, string>, options?: { replace?: boolean }) => void;
  forceScrollToBottom: () => void;
  syncCompletedAttempt: (sid: string, attemptId?: string) => Promise<boolean>;
}

export function useGoalManager({
  sessionId,
  status,
  setupSSE,
  setSearchParams,
  forceScrollToBottom,
  syncCompletedAttempt,
}: UseGoalManagerParams) {
  const { t } = useTranslation();
  const pendingGoalSessionRef = useRef<string | null>(null);
  const [goalComposerActive, setGoalComposerActive] = useState(false);
  const [goalDetailsOpen, setGoalDetailsOpen] = useState(false);
  const [goalSnapshot, setGoalSnapshot] = useState<GoalSnapshot | null>(null);
  const [goalEditActive, setGoalEditActive] = useState(false);
  const [goalEditValue, setGoalEditValue] = useState("");

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
  }, []);

  const handleCancelGoal = useCallback(async () => {
    if (!sessionId || !goalSnapshot) return;
    try {
      await api.updateGoalStatus(sessionId, {
        goal_id: goalSnapshot.goal.goal_id,
        expected_goal_id: goalSnapshot.goal.goal_id,
        status: "cancelled",
        recap: "Cancelled from Web UI.",
      });
      setGoalSnapshot(null);
      setGoalDetailsOpen(false);
      toast.success(t('agent.researchGoalCancelled'));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('agent.failedToCancelGoal'));
    }
  }, [goalSnapshot, sessionId]);

  const handleStartGoalEdit = useCallback(() => {
    if (!goalSnapshot) return;
    setGoalEditValue(goalSnapshot.goal.objective);
    setGoalEditActive(true);
  }, [goalSnapshot]);

  const handleSaveGoalEdit = useCallback(async () => {
    const objective = goalEditValue.trim();
    if (!sessionId || !goalSnapshot || !objective) return;
    try {
      const response = await api.updateGoal(sessionId, {
        goal_id: goalSnapshot.goal.goal_id,
        expected_goal_id: goalSnapshot.goal.goal_id,
        objective,
      });
      setGoalSnapshot(response.snapshot);
      setGoalEditActive(false);
      toast.success(t('agent.researchGoalUpdated'));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('agent.failedToUpdateGoal'));
    }
  }, [goalEditValue, goalSnapshot, sessionId]);

  const handleContinueGoal = useCallback(async () => {
    if (!sessionId || !goalSnapshot || status === "streaming") return;
    const prompt = goalContinuePrompt(goalSnapshot);
    act().addMessage({ id: "", type: "user", content: prompt, timestamp: Date.now() });
    act().setStatus("streaming");
    forceScrollToBottom();
    try {
      setupSSE(sessionId);
      const sent = await api.sendMessage(sessionId, prompt);
      void syncCompletedAttempt(sessionId, sent.attempt_id);
    } catch (error) {
      act().setStatus("error");
      const message = isAuthRequiredError(error) ? AUTH_REQUIRED_MESSAGE : t('agent.failedToContinue');
      toast.error(message);
      act().addMessage({ id: "", type: "error", content: message, timestamp: Date.now() });
    }
  }, [forceScrollToBottom, goalSnapshot, sessionId, setupSSE, status, syncCompletedAttempt]);

  const ensureGoalSession = useCallback(async (title: string): Promise<string> => {
    let sid = act().sessionId;
    if (sid) return sid;
    const session = await api.createSession(title.slice(0, 50));
    sid = session.session_id;
    pendingGoalSessionRef.current = sid;
    act().setSessionId(sid);
    setSearchParams({ session: sid }, { replace: true });
    setupSSE(sid);
    return sid;
  }, [setSearchParams, setupSSE]);

  useEffect(() => {
    if (!sessionId) {
      setGoalSnapshot(null);
      setGoalDetailsOpen(false);
      return;
    }
    if (pendingGoalSessionRef.current === sessionId) {
      pendingGoalSessionRef.current = null;
      return;
    }
    loadGoalSnapshot(sessionId);
  }, [sessionId, loadGoalSnapshot]);

  return {
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
    goalKickoffPrompt,
    goalContinuePrompt,
  };
}
