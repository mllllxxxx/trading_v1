import { Suspense, lazy, type ComponentType } from "react";
import { createBrowserRouter } from "react-router-dom";
import { TerminalLayout } from "@/components/layout/TerminalLayout";

const Cockpit = lazy(() => import("@/pages/Cockpit").then((m) => ({ default: m.Cockpit })));
const Agent = lazy(() => import("@/pages/Agent").then((m) => ({ default: m.Agent })));
const RunDetail = lazy(() =>
  import("@/pages/RunDetail").then((m) => ({ default: m.RunDetail })),
);
const Compare = lazy(() =>
  import("@/pages/Compare").then((m) => ({ default: m.Compare })),
);
const Settings = lazy(() =>
  import("@/pages/Settings").then((m) => ({ default: m.Settings })),
);
const Runtime = lazy(() =>
  import("@/pages/Runtime").then((m) => ({ default: m.Runtime })),
);
const Correlation = lazy(() =>
  import("@/pages/Correlation").then((m) => ({ default: m.Correlation })),
);
const AlphaZoo = lazy(() =>
  import("@/pages/AlphaZoo").then((m) => ({ default: m.AlphaZoo })),
);
const Trader = lazy(() =>
  import("@/pages/Trader").then((m) => ({ default: m.Trader })),
);
const TraderHistory = lazy(() =>
  import("@/pages/TraderHistory").then((m) => ({ default: m.TraderHistory })),
);
const BerkshireDesk = lazy(() =>
  import("@/pages/BerkshireDesk").then((m) => ({ default: m.BerkshireDesk })),
);
const NotFoundPage = lazy(() =>
  import("@/pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage })),
);

function PageLoader() {
  return (
    <div className="flex h-[60vh] items-center justify-center text-ttcc-text-secondary">
      Loading…
    </div>
  );
}

function wrap(Component: ComponentType) {
  return (
    <Suspense fallback={<PageLoader />}>
      <Component />
    </Suspense>
  );
}

export const router = createBrowserRouter([
  {
    element: <TerminalLayout />,
    children: [
      { path: "/", element: wrap(Cockpit) },
      { path: "/agent", element: wrap(Agent) },
      { path: "/runtime", element: wrap(Runtime) },
      { path: "/settings", element: wrap(Settings) },
      { path: "/runs/:runId", element: wrap(RunDetail) },
      { path: "/compare", element: wrap(Compare) },
      { path: "/correlation", element: wrap(Correlation) },
      { path: "/alpha-zoo", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/bench", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/compare", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/:alphaId", element: wrap(AlphaZoo) },
      { path: "/trader", element: wrap(Trader) },
      { path: "/trader/history", element: wrap(TraderHistory) },
      { path: "/berkshire", element: wrap(BerkshireDesk) },
      { path: "*", element: wrap(NotFoundPage) },
    ],
  },
]);
