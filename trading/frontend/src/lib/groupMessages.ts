import type { AgentMessage } from "@/types/agent";

/**
 * Group consecutive `thinking` / `tool_call` / `tool_result` / `compact`
 * messages into a single timeline item; everything else renders as a
 * standalone message.
 *
 * Shared by Agent.tsx and AgentChatConsole.tsx.
 */
export type MsgGroup =
  | { kind: "single"; msg: AgentMessage }
  | { kind: "timeline"; msgs: AgentMessage[] };

const TIMELINE_TYPES = new Set(["thinking", "tool_call", "tool_result", "compact"]);

export function groupMessages(msgs: AgentMessage[]): MsgGroup[] {
  const out: MsgGroup[] = [];
  let buf: AgentMessage[] = [];
  const flush = () => {
    if (buf.length) {
      out.push({ kind: "timeline", msgs: [...buf] });
      buf = [];
    }
  };
  for (const m of msgs) {
    if (TIMELINE_TYPES.has(m.type)) {
      buf.push(m);
    } else {
      flush();
      out.push({ kind: "single", msg: m });
    }
  }
  flush();
  return out;
}
