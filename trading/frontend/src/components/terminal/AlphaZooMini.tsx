import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Layers } from "lucide-react";
import { api, type AlphaBenchTopRow } from "@/lib/api";
import { PanelLabel, Skeleton, cn } from "@/components/terminal/primitives";

/**
 * AlphaZooMini — top alphas snapshot inside the terminal.
 *
 * Loads the most recent bench (or latest benchmark row from
 * `/alpha/bench` job) and shows the top 5 by IR. Read-only link
 * to the full zoo at `/alpha-zoo`.
 */
export function AlphaZooMini({ topRows }: { topRows?: AlphaBenchTopRow[] }) {
  const [rows, setRows] = useState<AlphaBenchTopRow[] | null>(topRows ?? null);
  const [loading, setLoading] = useState(!topRows);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (topRows) {
      setRows(topRows);
      setLoading(false);
      return;
    }
    let alive = true;
    // No canonical "top alphas" endpoint — derive from listAlphas w/ best signal.
    // We render a static "no bench cached" state to avoid paying the bench cost
    // every 5s on the terminal poll cycle. The full bench lives at /alpha-zoo.
    api.listAlphas({ limit: 5 })
      .then((res) => {
        if (!alive) return;
        // Convert AlphaSummary → topRows-shaped entries (no real IC, fallback zeros).
        const adapted: AlphaBenchTopRow[] = res.alphas.slice(0, 5).map((a) => ({
          id: a.id,
          ic_mean: 0,
          ir: 0,
          theme: a.theme ?? [],
          formula_latex: "",
          category: "alive",
        }));
        setRows(adapted);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setError(err instanceof Error ? err.message : "Failed to load alphas");
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [topRows]);

  return (
    <div className="rounded border border-ttcc-border bg-ttcc-surface">
      <PanelLabel
        icon={Layers}
        tone="accent"
        right={
          <Link
            to="/alpha-zoo/bench"
            className="font-mono text-[10px] text-ttcc-accent hover:text-ttcc-blue transition-colors"
          >
            browse →
          </Link>
        }
      >
        Alpha zoo · top
      </PanelLabel>
      {loading ? (
        <div className="space-y-1 p-2">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-5 w-full" />
          ))}
        </div>
      ) : error ? (
        <div className="px-2.5 py-3 text-[11px] text-ttcc-text-secondary">{error}</div>
      ) : !rows || rows.length === 0 ? (
        <div className="px-2.5 py-3 text-[11px] text-ttcc-text-secondary">
          No alphas yet — open the zoo to run a benchmark.
        </div>
      ) : (
        <ul className="px-1.5 pb-1.5">
          {rows.slice(0, 5).map((r) => (
            <li
              key={r.id}
              className="flex items-center justify-between gap-2 px-1.5 py-1 hover:bg-ttcc-surface-2 rounded transition-colors"
            >
              <div className="min-w-0 flex-1">
                <div className="font-mono text-[11px] truncate text-ttcc-text">{r.id}</div>
                <div className="font-mono text-[9px] truncate text-ttcc-text-muted">
                  {(r.theme ?? []).join(", ") || "—"}
                </div>
              </div>
              <div className="text-right">
                <div className={cn(
                  "font-mono text-[11px] tabular font-semibold",
                  (r.ir ?? 0) > 1 ? "text-ttcc-green"
                  : (r.ir ?? 0) > 0 ? "text-ttcc-text"
                  : (r.ir ?? 0) < 0 ? "text-ttcc-red"
                  : "text-ttcc-text-muted"
                )}>
                  {typeof r.ir === "number" ? r.ir.toFixed(2) : "—"}
                </div>
                <div className="font-mono text-[9px] tabular text-ttcc-text-muted">
                  IR · ic={r.ic_mean?.toFixed?.(2) ?? "—"}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
