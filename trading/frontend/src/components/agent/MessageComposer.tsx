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
  OctagonX,
  Download,
  Landmark,
} from "lucide-react";
import { RunnerStatus } from "@/components/chat/RunnerStatus";
import { GoalPanel } from "./GoalPanel";
import type { AgentMessage } from "@/types/agent";
import type { GoalSnapshot, LiveStatus } from "@/lib/api";

const CONNECTOR_CHECK_PROMPT =
  "List my trading connector profiles, show which one is selected, then check that selected connector. If it is not ready, tell me exactly what setup step is missing. Do not place or modify orders.";
const CONNECTOR_PORTFOLIO_PROMPT =
  "Use the selected trading connector profile to summarize my account, positions, concentration, cash, and portfolio risk. Do not place or modify orders.";

export interface MessageComposerProps {
  input: string;
  onInputChange: (v: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  status: "idle" | "streaming" | "error";
  swarmPreset: { name: string; title: string } | null;
  onClearSwarmPreset: () => void;
  goalComposerActive: boolean;
  onClearGoalComposer: () => void;
  goalSnapshot: GoalSnapshot | null;
  goalDetailsOpen: boolean;
  goalEditActive: boolean;
  goalEditValue: string;
  onToggleGoalDetails: () => void;
  onStartGoalEdit: () => void;
  onSaveGoalEdit: () => void;
  onCancelGoalEdit: () => void;
  onContinueGoal: () => void;
  onCancelGoal: () => void;
  onEditValueChange: (v: string) => void;
  liveStatus: LiveStatus | null;
  liveStatusUnavailable: boolean;
  liveIsHalted: boolean;
  liveActive: boolean;
  halting: boolean;
  onRefreshLiveStatus: () => void;
  onHaltLive: () => void;
  attachment: { filename: string; filePath: string } | null;
  onClearAttachment: () => void;
  uploading: boolean;
  onFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void;
  messages: AgentMessage[];
  onExport: () => void;
  onCancel: () => void;
  onRunPrompt: (prompt: string) => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  uploadMenuRef: React.RefObject<HTMLDivElement | null>;
  showUploadMenu: boolean;
  onToggleUploadMenu: () => void;
}

export function MessageComposer({
  input,
  onInputChange,
  onSubmit,
  status,
  swarmPreset,
  onClearSwarmPreset,
  goalComposerActive,
  onClearGoalComposer,
  goalSnapshot,
  goalDetailsOpen,
  goalEditActive,
  goalEditValue,
  onToggleGoalDetails,
  onStartGoalEdit,
  onSaveGoalEdit,
  onCancelGoalEdit,
  onContinueGoal,
  onCancelGoal,
  onEditValueChange,
  liveStatus,
  liveStatusUnavailable,
  liveIsHalted,
  liveActive,
  halting,
  onRefreshLiveStatus,
  onHaltLive,
  attachment,
  onClearAttachment,
  uploading,
  onFileSelect,
  messages,
  onExport,
  onCancel,
  onRunPrompt,
  inputRef,
  fileInputRef,
  uploadMenuRef,
  showUploadMenu,
  onToggleUploadMenu,
}: MessageComposerProps) {
  const { t } = useTranslation();

  return (
    <form onSubmit={onSubmit} className="border-t border-ttcc-border-subtle tt-glass p-4">
      <div className="max-w-3xl mx-auto space-y-2">
        {swarmPreset && (
          <div className="flex items-center gap-1">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-ttcc-accent/10 text-ttcc-accent text-xs font-medium">
              <Users className="h-3 w-3" />
              {swarmPreset.title}
              <button type="button" onClick={onClearSwarmPreset} className="hover:text-ttcc-red transition-colors">
                <X className="h-3 w-3" />
              </button>
            </span>
          </div>
        )}
        {goalComposerActive && (
          <div className="flex items-center gap-1">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-ttcc-accent/10 text-ttcc-accent text-xs font-medium">
              <Target className="h-3 w-3" />
              New Research Goal
              <button type="button" onClick={onClearGoalComposer} className="hover:text-ttcc-red transition-colors">
                <X className="h-3 w-3" />
              </button>
            </span>
          </div>
        )}
        {goalSnapshot && !goalComposerActive && (
          <GoalPanel
            goalSnapshot={goalSnapshot}
            goalDetailsOpen={goalDetailsOpen}
            goalEditActive={goalEditActive}
            goalEditValue={goalEditValue}
            onToggleDetails={onToggleGoalDetails}
            onStartGoalEdit={onStartGoalEdit}
            onSaveGoalEdit={onSaveGoalEdit}
            onCancelGoalEdit={onCancelGoalEdit}
            onContinueGoal={onContinueGoal}
            onCancelGoal={onCancelGoal}
            onEditValueChange={onEditValueChange}
            disabled={status === "streaming"}
          />
        )}
        <RunnerStatus
          status={liveStatus}
          unavailable={liveStatusUnavailable}
          halted={liveIsHalted}
          onRefresh={onRefreshLiveStatus}
        />
        {attachment && (
          <div className="flex items-center gap-1">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-ttcc-accent/10 text-ttcc-accent text-xs font-medium">
              <Paperclip className="h-3 w-3" />
              {attachment.filename}
              <button type="button" onClick={onClearAttachment} className="hover:text-ttcc-red transition-colors">
                <X className="h-3 w-3" />
              </button>
            </span>
          </div>
        )}
        {uploading && (
          <div className="flex items-center gap-1.5 text-xs text-ttcc-text-secondary">
            <Loader2 className="h-3 w-3 animate-spin" />
            Uploading...
          </div>
        )}
        {liveActive && (
          <div className="flex items-center gap-2">
            {liveIsHalted ? (
              <span className="inline-flex items-center gap-1.5 rounded-lg bg-ttcc-red/10 px-2.5 py-1 text-xs font-medium text-ttcc-red">
                <OctagonX className="h-3 w-3" />
                Connector runtime halted
              </span>
            ) : (
              <button
                type="button"
                onClick={onHaltLive}
                disabled={halting}
                className="inline-flex items-center gap-1.5 rounded-lg border border-ttcc-red/40 bg-ttcc-red/5 px-2.5 py-1 text-xs font-medium text-ttcc-red transition-colors hover:bg-ttcc-red/10 disabled:opacity-40"
                title="Instantly halt connector runtime activity"
              >
                {halting ? <Loader2 className="h-3 w-3 animate-spin" /> : <OctagonX className="h-3 w-3" />}
                Halt connector runtime
              </button>
            )}
          </div>
        )}
        <div className="flex gap-2 items-end">
          <div className="relative" ref={uploadMenuRef}>
            <button
              type="button"
              onClick={onToggleUploadMenu}
              disabled={status === "streaming" || uploading}
              className="w-9 h-9 rounded-full border border-ttcc-border-subtle flex items-center justify-center text-ttcc-text-secondary hover:text-ttcc-text hover:bg-ttcc-surface-2/50 transition-colors disabled:opacity-40 shrink-0"
              title="More options"
            >
              <Plus className="h-4 w-4" />
            </button>
            {showUploadMenu && (
              <div className="absolute bottom-full left-0 mb-2 w-52 tt-glass shadow-tt-lg rounded-xl py-1 z-50">
                <button
                  type="button"
                  onClick={() => { fileInputRef.current?.click(); onToggleUploadMenu(); }}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-ttcc-surface-2/50 transition-colors flex items-center gap-2"
                >
                  <Paperclip className="h-4 w-4" />
                  Upload PDF document
                </button>
                <div className="border-t my-1" />
                <button
                  type="button"
                  onClick={() => {
                    onToggleUploadMenu();
                    onClearSwarmPreset();
                    onClearGoalComposer();
                    inputRef.current?.focus();
                  }}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-ttcc-surface-2/50 transition-colors flex items-center gap-2"
                >
                  <Target className="h-4 w-4" />
                  Research Goal
                </button>
                <button
                  type="button"
                  onClick={() => {
                    onToggleUploadMenu();
                    onClearGoalComposer();
                    onRunPrompt("auto");
                    inputRef.current?.focus();
                  }}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-ttcc-surface-2/50 transition-colors flex items-center gap-2"
                >
                  <Users className="h-4 w-4" />
                  Agent Swarm
                </button>
                <div className="border-t my-1" />
                <button
                  type="button"
                  onClick={() => {
                    onToggleUploadMenu();
                    onRunPrompt(CONNECTOR_CHECK_PROMPT);
                  }}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-ttcc-surface-2/50 transition-colors flex items-center gap-2"
                >
                  <Landmark className="h-4 w-4" />
                  Check Trading Connector
                </button>
                <button
                  type="button"
                  onClick={() => {
                    onToggleUploadMenu();
                    onRunPrompt(CONNECTOR_PORTFOLIO_PROMPT);
                  }}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-ttcc-surface-2/50 transition-colors flex items-center gap-2"
                >
                  <Landmark className="h-4 w-4" />
                  Analyze Connector Portfolio
                </button>
              </div>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.xlsx,.xls,.pptx,.csv,.tsv,.txt,.md,.log,.json,.yaml,.yml,.toml,.html,.xml,.rst,.png,.jpg,.jpeg,.gif,.bmp,.webp,.tiff"
            onChange={onFileSelect}
            className="hidden"
          />
          <textarea
            ref={inputRef}
            value={input}
            rows={1}
            onChange={(e) => onInputChange(e.target.value)}
            onInput={(e) => {
              const el = e.target as HTMLTextAreaElement;
              el.style.height = "auto";
              el.style.height = el.scrollHeight + "px";
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onRunPrompt(input.trim());
              }
            }}
            placeholder={
              goalComposerActive
                ? "Describe the research goal to attach to this session"
                : "e.g. Create a dual MA crossover strategy for 000001.SZ, backtest 2024"
            }
            className="flex-1 px-4 py-2.5 rounded-xl border border-ttcc-border-subtle bg-ttcc-surface text-sm focus:outline-none focus:ring-2 focus:ring-ttcc-accent/30 transition-shadow resize-none max-h-32 overflow-y-auto"
            disabled={status === "streaming"}
          />
          {messages.length > 0 && (
            <button
              type="button"
              onClick={onExport}
              className="px-3 py-2.5 rounded-xl border border-ttcc-border-subtle text-ttcc-text-secondary hover:text-ttcc-text hover:bg-ttcc-surface-2/50 transition-colors"
              title={t('agent.exportChat')}
            >
              <Download className="h-4 w-4" />
            </button>
          )}
          {status === "streaming" ? (
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2.5 rounded-xl bg-ttcc-red text-ttcc-bg text-sm font-medium hover:opacity-90 transition-opacity"
              title={t('agent.stopGeneration')}
            >
              <Square className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={goalComposerActive ? !input.trim() : (!input.trim() && !attachment)}
              className="px-4 py-2.5 rounded-xl bg-ttcc-accent text-ttcc-bg text-sm font-medium disabled:opacity-40 hover:opacity-90 transition-opacity"
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </form>
  );
}
