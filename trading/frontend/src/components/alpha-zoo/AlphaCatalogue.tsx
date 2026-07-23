import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Layers,
  Search,
  Play,
  ArrowLeftRight,
  Loader2,
  Library,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { api, type AlphaSummary } from "@/lib/api";
import i18n from "@/i18n";
import {
  PAGE_SIZE,
  UNIVERSE_OPTIONS,
  ZOO_CARDS,
} from "@/components/alpha-zoo/alphaHelpers";

export function AlphaCatalogue() {
  const [alphas, setAlphas] = useState<AlphaSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [zooFilter, setZooFilter] = useState<string>("");
  const [themeFilter, setThemeFilter] = useState<string>("");
  const [universeFilter, setUniverseFilter] = useState<string>("");
  const [search, setSearch] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [total, setTotal] = useState<number>(0);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());

  const toggleSelected = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const compareHref =
    selected.size >= 2
      ? `/alpha-zoo/compare?ids=${[...selected].map(encodeURIComponent).join(",")}`
      : "/alpha-zoo/compare";

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api
      .listAlphas({
        zoo: zooFilter || undefined,
        theme: themeFilter || undefined,
        universe: universeFilter || undefined,
        limit: 1000,
      })
      .then((res) => {
        if (!alive) return;
        setAlphas(res.alphas);
        setTotal(res.total);
        setVisibleCount(PAGE_SIZE);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        const msg = err instanceof Error ? err.message : "Failed to load alphas";
        toast.error(msg);
        setAlphas([]);
        setTotal(0);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [zooFilter, themeFilter, universeFilter]);

  const themeOptions = useMemo(() => {
    const set = new Set<string>();
    for (const a of alphas) for (const t of a.theme || []) set.add(t);
    return Array.from(set).sort();
  }, [alphas]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return alphas;
    return alphas.filter(
      (a) =>
        a.id.toLowerCase().includes(q) ||
        (a.nickname || "").toLowerCase().includes(q),
    );
  }, [alphas, search]);

  const visible = filtered.slice(0, visibleCount);

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-8">
      {/* Hero */}
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wide">
          <Layers className="h-3.5 w-3.5" aria-hidden="true" /> Alpha Zoo
        </div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight">
          {total > 0 ? total : 452} {i18n.t("alphaZoo.prebuiltAlpha", { count: total > 0 ? total : 452 })}
        </h1>
        <p className="text-sm text-muted-foreground max-w-2xl">
          Browse formula-driven cross-sectional signals from Qlib, the
          Kakushadze 101 set, GTJA 191, and the academic anomaly literature.
          Click any alpha to read its formula and source code, or run a bench
          to score the whole zoo on a universe and period.
        </p>
      </div>

      {/* Zoo cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {ZOO_CARDS.map((z) => {
          const active = zooFilter === z.id;
          return (
            <button
              key={z.id}
              type="button"
              onClick={() => setZooFilter(active ? "" : z.id)}
              className={cn(
                "text-left border rounded-xl p-4 space-y-2 transition bg-gradient-to-br",
                z.accent,
                "hover:border-primary/50",
                active && "border-primary ring-1 ring-primary/30",
              )}
            >
              <div className="flex items-center justify-between">
                <Library className="h-5 w-5 text-primary" aria-hidden="true" />
                <span className="text-xs font-mono text-muted-foreground">
                  {z.approxCount}
                </span>
              </div>
              <h3 className="font-semibold text-sm leading-tight">{z.title}</h3>
              <p className="text-xs text-muted-foreground line-clamp-3">
                {z.description}
              </p>
            </button>
          );
        })}
      </div>

      {/* Filter bar */}
      <div className="flex flex-col md:flex-row md:items-end gap-3 border rounded-xl p-4 bg-card">
        <div className="flex-1 min-w-0">
          <label htmlFor="alpha-search" className="text-xs text-muted-foreground block mb-1">
            Search
          </label>
          <div className="relative">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground"
              aria-hidden="true"
            />
            <input
              id="alpha-search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setVisibleCount(PAGE_SIZE);
              }}
              placeholder="Filter by id or nickname…"
              className="w-full pl-9 pr-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </div>
        </div>
        <div className="md:w-40">
          <label htmlFor="alpha-zoo-filter" className="text-xs text-muted-foreground block mb-1">Zoo</label>
          <select
            id="alpha-zoo-filter"
            value={zooFilter}
            onChange={(e) => setZooFilter(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          >
            <option value="">All zoos</option>
            {ZOO_CARDS.map((z) => (
              <option key={z.id} value={z.id}>
                {z.title}
              </option>
            ))}
          </select>
        </div>
        <div className="md:w-40">
          <label htmlFor="alpha-theme-filter" className="text-xs text-muted-foreground block mb-1">
            Theme
          </label>
          <select
            id="alpha-theme-filter"
            value={themeFilter}
            onChange={(e) => setThemeFilter(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          >
            <option value="">All themes</option>
            {themeOptions.map((tname) => (
              <option key={tname} value={tname}>
                {tname}
              </option>
            ))}
          </select>
        </div>
        <div className="md:w-44">
          <label htmlFor="alpha-universe-filter" className="text-xs text-muted-foreground block mb-1">
            Universe
          </label>
          <select
            id="alpha-universe-filter"
            value={universeFilter}
            onChange={(e) => setUniverseFilter(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
          >
            <option value="">All universes</option>
            {UNIVERSE_OPTIONS.map((u) => (
              <option key={u.value} value={u.value}>
                {u.label}
              </option>
            ))}
          </select>
        </div>
        <Link
          to={compareHref}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg border text-sm font-medium hover:bg-muted hover:text-foreground transition"
          title="Tick 2+ alphas below, then compare them head-to-head"
        >
          <ArrowLeftRight className="h-3.5 w-3.5" aria-hidden="true" /> Compare
          {selected.size >= 2 ? ` (${selected.size})` : ""}
        </Link>
        <Link
          to="/alpha-zoo/bench"
          className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition"
        >
          <Play className="h-3.5 w-3.5" aria-hidden="true" /> Run benchmark
        </Link>
      </div>

      {/* Table */}
      {/* TODO(v0.2): switch to react-window if alpha count exceeds 5000 */}
      <div className="border rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" aria-label="Alpha catalogue">
            <caption className="sr-only">Alpha catalogue</caption>
            <thead>
              <tr className="border-b bg-muted/40">
                <th className="w-10 px-3 py-2.5">
                  <span className="sr-only">Select for compare</span>
                </th>
                <th className="text-left px-4 py-2.5 text-muted-foreground">
                  ID
                </th>
                <th className="text-left px-4 py-2.5 text-muted-foreground">
                  Zoo
                </th>
                <th className="text-left px-4 py-2.5 text-muted-foreground">
                  Theme
                </th>
                <th className="text-left px-4 py-2.5 text-muted-foreground hidden md:table-cell">
                  Universe
                </th>
                <th className="text-right px-4 py-2.5 text-muted-foreground" title="Predictive half-life: trading days before the signal's edge decays">
                  Decay (days)
                </th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin inline mr-2" aria-hidden="true" />
                    Loading alphas…
                  </td>
                </tr>
              ) : visible.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                    No alphas match the current filters.
                  </td>
                </tr>
              ) : (
                visible.map((a) => (
                  <tr
                    key={`${a.zoo}:${a.id}`}
                    className={cn(
                      "border-b last:border-0 hover:bg-muted/20",
                      selected.has(a.id) && "bg-primary/5",
                    )}
                  >
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selected.has(a.id)}
                        onChange={() => toggleSelected(a.id)}
                        aria-label={`Select ${a.id} for compare`}
                        className="h-4 w-4 rounded border-input accent-primary cursor-pointer"
                      />
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">
                      <Link
                        to={`/alpha-zoo/${encodeURIComponent(a.id)}`}
                        className="text-primary hover:underline"
                      >
                        {a.id}
                      </Link>
                      {a.nickname && (
                        <span className="ml-2 text-muted-foreground font-sans">
                          {a.nickname}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-xs">{a.zoo}</td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">
                      {(a.theme || []).join(", ") || "—"}
                    </td>
                    <td className="px-4 py-2 text-xs text-muted-foreground hidden md:table-cell">
                      {(a.universe || []).join(", ") || "—"}
                    </td>
                    <td className="px-4 py-2 text-right font-mono tabular-nums text-xs">
                      {a.decay_horizon ?? "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {!loading && visible.length < filtered.length && (
          <div className="border-t p-3 flex items-center justify-between text-xs text-muted-foreground">
            <span>
              Showing {visible.length} of {filtered.length}
            </span>
            <button
              type="button"
              onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}
              className="px-3 py-1 rounded-md border hover:bg-muted hover:text-foreground transition"
            >
              Load more
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
