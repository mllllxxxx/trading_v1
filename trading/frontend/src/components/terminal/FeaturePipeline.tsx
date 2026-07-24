import { useEffect, useState } from "react";
import { GitBranch, ListChecks } from "lucide-react";
import { api, type ProjectFeature } from "@/lib/api";
import { PanelLabel, PillBadge, Skeleton } from "@/components/terminal/primitives";

/**
 * FeaturePipeline — project feature design tracker.
 * Lists features tracked under `trading/docs/features/` with their status,
 * branch, and a one-line summary.
 */
export function FeaturePipeline() {
  const [features, setFeatures] = useState<ProjectFeature[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.listProjectFeatures()
      .then((res) => {
        if (!alive) return;
        setFeatures(res.features);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setError(err instanceof Error ? err.message : "Failed to load features");
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="rounded-lg border border-ttcc-border bg-ttcc-surface">
      <PanelLabel
        icon={ListChecks}
        tone="accent"
        right={
          features ? (
            <span className="font-mono text-[10px] tabular text-ttcc-text-muted">
              {features.length}
            </span>
          ) : null
        }
      >
        Feature pipeline
      </PanelLabel>
      {loading ? (
        <div className="space-y-1 p-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="px-2.5 py-3 text-[11px] text-ttcc-red">{error}</div>
      ) : !features || features.length === 0 ? (
        <div className="px-2.5 py-3 text-[11px] text-ttcc-text-secondary">
          No features tracked. Add one under <code className="font-mono text-ttcc-text">trading/docs/features/</code>.
        </div>
      ) : (
        <ul>
          {features.map((f) => (
            <li
              key={f.id}
              className="border-b border-ttcc-border/40 px-2.5 py-1.5 last:border-b-0 hover:bg-ttcc-surface-2 transition-colors"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[11px] font-semibold truncate text-ttcc-text">
                  {f.id}
                </span>
                <StatusPill status={f.status} />
              </div>
              <div className="mt-0.5 line-clamp-2 text-[10px] text-ttcc-text-secondary">
                {f.summary || f.name}
              </div>
              {f.branch ? (
                <div className="mt-1 flex items-center gap-1 font-mono text-[10px] text-ttcc-text-muted">
                  <GitBranch className="h-3 w-3 shrink-0" />
                  <span className="truncate">{f.branch}</span>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const norm = status.toLowerCase();
  const tone =
    norm.includes("done") || norm === "shipped" ? "ok"
    : norm.includes("blocked") ? "fail"
    : norm.includes("design") || norm.includes("plan") ? "warn"
    : norm.includes("implement") || norm.includes("progress") || norm.includes("review") ? "info"
    : "neutral";
  return (
    <PillBadge tone={tone as "ok" | "fail" | "warn" | "info" | "neutral"} mono>
      {status}
    </PillBadge>
  );
}
