/**
 * Alpha Zoo — browse / detail / bench views.
 *
 * Routing model: a single page component, three URL shapes:
 *   /alpha-zoo                 → browse view
 *   /alpha-zoo/bench           → bench runner
 *   /alpha-zoo/compare         → head-to-head compare
 *   /alpha-zoo/:alphaId        → alpha detail
 *
 * The bench view uses a raw EventSource rather than the shared `useSSE` hook
 * because that hook hard-codes the agent's known event types (text_delta,
 * tool_call, …) and would silently drop the alpha bench events
 * (`progress`, `result`, `done`, `error`). The swarm page uses the same
 * raw-EventSource pattern (frontend/src/pages/Agent.tsx).
 */

import { useLocation, useParams } from "react-router-dom";
import { AlphaCatalogue } from "@/components/alpha-zoo/AlphaCatalogue";
import { AlphaDetail } from "@/components/alpha-zoo/AlphaDetail";
import { BenchRunner } from "@/components/alpha-zoo/BenchRunner";
import { CompareView } from "@/components/alpha-zoo/CompareView";

export function AlphaZoo() {
  const params = useParams<{ alphaId?: string }>();
  const { pathname } = useLocation();

  if (pathname === "/alpha-zoo/bench") {
    return <BenchRunner />;
  }
  if (pathname === "/alpha-zoo/compare") {
    return <CompareView />;
  }
  if (params.alphaId) {
    return <AlphaDetail alphaId={params.alphaId} />;
  }
  return <AlphaCatalogue />;
}
