import { useEffect, useRef, useState } from "react";
import { cn } from "@/components/terminal/primitives";

export type TabSpec<K extends string> = {
  key: K;
  label: string;
  icon?: React.ComponentType<{ className?: string }>;
  badge?: React.ReactNode;
};

/**
 * TabBar — pill-style tabs with fade transition on the active panel.
 *
 * Why a single component instead of inline JSX: keeps the keyboard /
 * ARIA semantics in one place so the Trader center stays scannable.
 */
export function TabBar<K extends string>({
  tabs,
  active,
  onChange,
  right,
}: {
  tabs: TabSpec<K>[];
  active: K;
  onChange: (key: K) => void;
  right?: React.ReactNode;
}) {
  return (
    <div className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-ttcc-border-subtle bg-ttcc-bg/80 px-2 py-1.5 backdrop-blur-sm">
      <div className="flex items-center gap-1">
        {tabs.map((t) => {
          const isActive = t.key === active;
          const Icon = t.icon;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => onChange(t.key)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider rounded-lg transition-all duration-150",
                isActive
                  ? "bg-ttcc-accent/10 text-ttcc-accent"
                  : "text-ttcc-text-secondary hover:text-ttcc-text hover:bg-ttcc-surface-2/40"
              )}
            >
              {Icon ? <Icon className="h-3 w-3" /> : null}
              {t.label}
              {t.badge ? (
                <span className="font-mono text-[10px] tabular opacity-70">{t.badge}</span>
              ) : null}
            </button>
          );
        })}
      </div>
      {right ? <div className="shrink-0">{right}</div> : null}
    </div>
  );
}

/**
 * TabPanel — wraps children in a 200ms fade-in. Re-mounts on tab change
 * so the animation re-triggers cleanly.
 */
export function TabPanel<K extends string>({
  active,
  children,
}: {
  active: K;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // Force a one-off remount of the wrapper so the CSS animation restarts.
  const [mountKey, setMountKey] = useState(active);
  useEffect(() => {
    setMountKey(active);
  }, [active]);
  return (
    <div key={mountKey} className="ttcc-tab-fade" ref={ref}>
      {children}
    </div>
  );
}
