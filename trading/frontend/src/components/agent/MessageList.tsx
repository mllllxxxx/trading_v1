import { useTranslation } from "react-i18next";
import { Loader2, ArrowDown } from "lucide-react";
import type { AgentMessage, ToolCallEntry } from "@/types/agent";
import { type MandateProposal, type MandateCommitted, type LiveAction } from "@/lib/api";
import type { MsgGroup } from "@/lib/groupMessages";
import { AgentAvatar } from "@/components/chat/AgentAvatar";
import { WelcomeScreen } from "@/components/chat/WelcomeScreen";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { ThinkingTimeline } from "@/components/chat/ThinkingTimeline";
import { ConversationTimeline } from "@/components/chat/ConversationTimeline";
import { ToolProgressIndicator } from "@/components/chat/ToolProgressIndicator";
import { MandateProposalCard } from "@/components/chat/MandateProposalCard";
import { SwarmStatusCard } from "@/components/chat/SwarmStatusCard";
import { LiveActionChip } from "./LiveActionChip";

export interface ProposalItem {
  kind: "proposal";
  timestamp: number;
  proposal: MandateProposal;
}

export interface LiveActionItem {
  kind: "live_action";
  timestamp: number;
  action: LiveAction;
}

export type LiveItem = ProposalItem | LiveActionItem;

export type TimelineRow =
  | { sort: number; render: "group"; group: MsgGroup; key: string }
  | { sort: number; render: "live"; item: LiveItem; key: string };

export interface MessageListProps {
  listRef: React.RefObject<HTMLDivElement | null>;
  sessionLoading: boolean;
  messages: AgentMessage[];
  status: "idle" | "streaming" | "error";
  streamingText: string;
  reasoningActive: boolean;
  toolCalls: ToolCallEntry[];
  timelineRows: TimelineRow[];
  showScrollBtn: boolean;
  onScrollToBottom: () => void;
  onExample: (prompt: string) => void;
  onRetry: (errorMsg: AgentMessage) => void;
  committedMandates: Record<string, MandateCommitted>;
  liveItems: LiveItem[];
}

export function MessageList({
  listRef,
  sessionLoading,
  messages,
  status,
  streamingText,
  reasoningActive,
  toolCalls,
  timelineRows,
  showScrollBtn,
  onScrollToBottom,
  onExample,
  onRetry,
  committedMandates,
  liveItems: _liveItems,
}: MessageListProps) {
  const { t } = useTranslation();

  return (
    <div ref={listRef} className="flex-1 overflow-auto p-6 scroll-smooth relative">
      <div className="max-w-3xl mx-auto space-y-4">
        {sessionLoading && (
          <div className="space-y-4 py-4">
            {[1, 2, 3].map(i => (
              <div key={i} className="flex gap-3 animate-pulse">
                <div className="h-8 w-8 rounded-full bg-muted shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 bg-muted rounded w-3/4" />
                  <div className="h-3 bg-muted/60 rounded w-1/2" />
                </div>
              </div>
            ))}
          </div>
        )}
        {!sessionLoading && messages.length === 0 && <WelcomeScreen onExample={onExample} />}

        {timelineRows.map((row, rowIdx) => {
          if (row.render === "live") {
            if (row.item.kind === "proposal") {
              return (
                <MandateProposalCard
                  key={row.key}
                  proposal={row.item.proposal}
                  committed={committedMandates[row.item.proposal.proposal_id] ?? null}
                  onAdjust={onExample}
                />
              );
            }
            return <LiveActionChip key={row.key} action={row.item.action} />;
          }
          const g = row.group;
          if (g.kind === "timeline") {
            const isLastRow = rowIdx === timelineRows.length - 1;
            return (
              <ThinkingTimeline
                key={row.key}
                messages={g.msgs}
                isLatest={isLastRow && status === "streaming"}
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
              <MessageBubble msg={g.msg} onRetry={g.msg.type === "error" ? onRetry : undefined} />
            </div>
          );
        })}

        {status === "streaming" && !reasoningActive && !streamingText && toolCalls.length === 0 && !messages.some((m) => m.type === "swarm_status" && m.swarmStatus?.status === "running") && (
          <div className="flex gap-3">
            <AgentAvatar />
            <div className="flex-1 min-w-0 flex items-center gap-2 text-xs text-muted-foreground pt-1">
              <Loader2 className="h-3 w-3 animate-spin text-primary shrink-0" />
              <span>{t('agent.agentWorking')}</span>
            </div>
          </div>
        )}

        {(streamingText || reasoningActive || (status === "streaming" && toolCalls.length > 0)) && (
          <div className="flex gap-3">
            <AgentAvatar />
            <div className="flex-1 min-w-0 space-y-1.5">
              {reasoningActive && !streamingText && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin text-primary shrink-0" />
                  <span>{t('agent.reasoning')}</span>
                </div>
              )}
              {streamingText && (
                <div className="prose prose-sm dark:prose-invert max-w-none leading-relaxed">
                  {streamingText}
                  <span className="inline-block w-0.5 h-4 bg-primary ml-0.5 animate-pulse align-middle" />
                </div>
              )}
              {status === "streaming" && toolCalls.length > 0 && (
                <ToolProgressIndicator toolCalls={toolCalls} />
              )}
            </div>
          </div>
        )}

        {status === "streaming" && (
          <div className="flex items-center gap-2 px-1 pt-1">
            <div className="h-0.5 flex-1 rounded-full bg-primary/20 overflow-hidden">
              <div className="h-full w-1/3 bg-primary rounded-full animate-[pulse-slide_2s_ease-in-out_infinite]" />
            </div>
            <span className="text-[10px] text-muted-foreground shrink-0 tabular-nums">{t('agent.running')}</span>
          </div>
        )}

      </div>

      {showScrollBtn && (
        <button
          onClick={onScrollToBottom}
          className="sticky bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-1 px-3 py-1.5 rounded-full bg-primary text-primary-foreground text-xs font-medium shadow-lg hover:opacity-90 transition-opacity z-10"
        >
          <ArrowDown className="h-3 w-3" /> {t('agent.newMessages')}
        </button>
      )}
      <ConversationTimeline messages={messages} containerRef={listRef} />
    </div>
  );
}
