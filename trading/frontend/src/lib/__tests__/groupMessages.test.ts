import { describe, it, expect } from "vitest";
import { groupMessages } from "../groupMessages";
import type { AgentMessage } from "@/types/agent";

function makeMsg(
  overrides: Partial<AgentMessage> & { type: AgentMessage["type"] }
): AgentMessage {
  return {
    id: `msg_${Math.random()}`,
    content: "",
    timestamp: Date.now(),
    ...overrides,
  };
}

describe("groupMessages", () => {
  it("empty array returns []", () => {
    expect(groupMessages([])).toEqual([]);
  });

  it("single user message returns [{kind: single}]", () => {
    const msg = makeMsg({ type: "user" });
    const result = groupMessages([msg]);
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({ kind: "single", msg });
  });

  it("single answer message returns [{kind: single}]", () => {
    const msg = makeMsg({ type: "answer" });
    const result = groupMessages([msg]);
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({ kind: "single", msg });
  });

  it("consecutive thinking messages group into one timeline", () => {
    const m1 = makeMsg({ type: "thinking" });
    const m2 = makeMsg({ type: "thinking" });
    const m3 = makeMsg({ type: "thinking" });
    const result = groupMessages([m1, m2, m3]);
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({ kind: "timeline", msgs: [m1, m2, m3] });
  });

  it("consecutive tool_call + tool_result group into one timeline", () => {
    const m1 = makeMsg({ type: "tool_call" });
    const m2 = makeMsg({ type: "tool_result" });
    const m3 = makeMsg({ type: "tool_call" });
    const m4 = makeMsg({ type: "tool_result" });
    const result = groupMessages([m1, m2, m3, m4]);
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({
      kind: "timeline",
      msgs: [m1, m2, m3, m4],
    });
  });

  it("mixed user → thinking → tool_call → answer returns 3 groups", () => {
    const user = makeMsg({ type: "user" });
    const thinking = makeMsg({ type: "thinking" });
    const toolCall = makeMsg({ type: "tool_call" });
    const answer = makeMsg({ type: "answer" });
    const result = groupMessages([user, thinking, toolCall, answer]);
    expect(result).toHaveLength(3);
    expect(result[0]).toEqual({ kind: "single", msg: user });
    expect(result[1]).toEqual({
      kind: "timeline",
      msgs: [thinking, toolCall],
    });
    expect(result[2]).toEqual({ kind: "single", msg: answer });
  });

  it("thinking after answer starts a new timeline", () => {
    // user → thinking → answer → thinking → answer
    const u1 = makeMsg({ type: "user" });
    const t1 = makeMsg({ type: "thinking" });
    const a1 = makeMsg({ type: "answer" });
    const t2 = makeMsg({ type: "thinking" });
    const a2 = makeMsg({ type: "answer" });
    const result = groupMessages([u1, t1, a1, t2, a2]);
    expect(result).toHaveLength(5);
    expect(result[0]).toEqual({ kind: "single", msg: u1 });
    expect(result[1]).toEqual({ kind: "timeline", msgs: [t1] });
    expect(result[2]).toEqual({ kind: "single", msg: a1 });
    expect(result[3]).toEqual({ kind: "timeline", msgs: [t2] });
    expect(result[4]).toEqual({ kind: "single", msg: a2 });
  });

  it("compact messages are grouped into timeline", () => {
    const m1 = makeMsg({ type: "compact" });
    const m2 = makeMsg({ type: "thinking" });
    const m3 = makeMsg({ type: "compact" });
    const result = groupMessages([m1, m2, m3]);
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({
      kind: "timeline",
      msgs: [m1, m2, m3],
    });
  });

  it("error messages are NOT grouped (single)", () => {
    const e1 = makeMsg({ type: "error" });
    const e2 = makeMsg({ type: "error" });
    const result = groupMessages([e1, e2]);
    expect(result).toHaveLength(2);
    expect(result[0]).toEqual({ kind: "single", msg: e1 });
    expect(result[1]).toEqual({ kind: "single", msg: e2 });
  });

  it("swarm_status messages are NOT grouped (single)", () => {
    const s1 = makeMsg({ type: "swarm_status" });
    const s2 = makeMsg({ type: "swarm_status" });
    const result = groupMessages([s1, s2]);
    expect(result).toHaveLength(2);
    expect(result[0]).toEqual({ kind: "single", msg: s1 });
    expect(result[1]).toEqual({ kind: "single", msg: s2 });
  });
});
