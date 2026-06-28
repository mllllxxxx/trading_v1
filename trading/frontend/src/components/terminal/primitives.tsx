import { cn } from "@/lib/utils";

export { cn };

/**
 * Shared primitives for the Trading Command Center terminal.
 * Kept tiny + dependency-free so any panel can drop them in.
 */

export function PanelLabel({
  children,
  icon: Icon,
  tone,
  right,
}: {
  children: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
  tone?: "bull" | "bear" | "warn" | "muted" | "info" | "accent";
  right?: React.ReactNode;
}) {
  const toneCls =
    tone === "bull" ? "text-ttcc-green"
    : tone === "bear" ? "text-ttcc-red"
    : tone === "warn" ? "text-ttcc-yellow"
    : tone === "info" ? "text-ttcc-blue"
    : tone === "accent" ? "text-ttcc-accent"
    : "text-ttcc-text-secondary";
  return (
    <div className="flex items-center justify-between gap-2 px-2.5 py-1.5 border-b border-ttcc-border/60">
      <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">
        {Icon ? <Icon className={cn("h-3 w-3 shrink-0", toneCls)} /> : null}
        <span className={cn(tone !== "muted" && toneCls)}>{children}</span>
      </span>
      {right ? <span className="shrink-0">{right}</span> : null}
    </div>
  );
}

export function PillBadge({
  tone,
  children,
  mono,
}: {
  tone: "long" | "short" | "ok" | "fail" | "neutral" | "tp" | "sl" | "info" | "warn" | "critical";
  children: React.ReactNode;
  mono?: boolean;
}) {
  const cls: Record<string, string> = {
    long: "bg-ttcc-green/10 text-ttcc-green border-ttcc-green/40",
    short: "bg-ttcc-red/10 text-ttcc-red border-ttcc-red/40",
    ok: "bg-ttcc-green/10 text-ttcc-green border-ttcc-green/40",
    fail: "bg-ttcc-red/10 text-ttcc-red border-ttcc-red/40",
    tp: "bg-ttcc-green/10 text-ttcc-green border-ttcc-green/40",
    sl: "bg-ttcc-red/10 text-ttcc-red border-ttcc-red/40",
    info: "bg-ttcc-blue/10 text-ttcc-blue border-ttcc-blue/40",
    warn: "bg-ttcc-yellow/10 text-ttcc-yellow border-ttcc-yellow/40",
    critical: "bg-ttcc-red/15 text-ttcc-red border-ttcc-red/50",
    neutral: "bg-ttcc-surface-2 text-ttcc-text-secondary border-ttcc-border",
  };
  return (
    <span className={cn(
      "inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider leading-none",
      mono && "font-mono",
      cls[tone]
    )}>
      {children}
    </span>
  );
}

export function LiveDot({ idle }: { idle?: boolean }) {
  return (
    <span
      className={cn(
        "tt-live-dot",
        idle && "tt-live-dot--idle"
      )}
      aria-hidden
    />
  );
}

export function MetricCard({
  label,
  children,
  className,
  tone,
  dense,
  icon: Icon,
}: {
  label: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  tone?: "bull" | "bear" | "warn" | "muted" | "info" | "accent";
  dense?: boolean;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  const ringCls =
    tone === "bull" ? "before:bg-ttcc-green"
    : tone === "bear" ? "before:bg-ttcc-red"
    : tone === "warn" ? "before:bg-ttcc-yellow"
    : tone === "info" ? "before:bg-ttcc-blue"
    : tone === "accent" ? "before:bg-ttcc-accent"
    : tone === "muted" ? "before:bg-ttcc-text-muted"
    : null;
  return (
    <div className={cn(
      "relative overflow-hidden rounded border border-ttcc-border bg-ttcc-surface",
      ringCls && "before:absolute before:left-0 before:top-0 before:h-full before:w-[2px] before:content-['']",
      className
    )}>
      <div className={cn(
        "flex items-center justify-between px-2.5 border-b border-ttcc-border/60",
        dense ? "py-1" : "py-1.5"
      )}>
        <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-ttcc-text-secondary">
          {Icon ? <Icon className="h-3 w-3 text-ttcc-text-secondary" /> : null}
          {label}
        </span>
      </div>
      <div className={cn("px-2.5", dense ? "py-1.5" : "py-2.5")}>{children}</div>
    </div>
  );
}

export function NumberCell({
  value,
  tone,
  size = "md",
  bold,
  className,
}: {
  value: React.ReactNode;
  tone?: "bull" | "bear" | "muted" | "default";
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  bold?: boolean;
  className?: string;
}) {
  const sizeCls = {
    xs: "text-[10px]",
    sm: "text-xs",
    md: "text-sm",
    lg: "text-lg",
    xl: "text-2xl",
  }[size];
  const toneCls =
    tone === "bull" ? "text-ttcc-green"
    : tone === "bear" ? "text-ttcc-red"
    : tone === "muted" ? "text-ttcc-text-muted"
    : "text-ttcc-text";
  return (
    <span className={cn(
      "font-mono tabular leading-none",
      sizeCls,
      bold && "font-bold",
      toneCls,
      className
    )}>
      {value}
    </span>
  );
}

export function Skeleton({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={cn("tt-skeleton", className)} style={style} />;
}

/**
 * Number formatting helpers — exported here so panels + Trader page share them.
 * Backward-compat: TraderHistory.tsx imports these from @/pages/Trader, which
 * re-exports from this module.
 */

export function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined || isNaN(n)) return "—";
  const sign = n < 0 ? "-" : "";
  return sign + "$" + Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function fmtPct(n: number | null | undefined): string {
  return n === null || n === undefined || isNaN(n) ? "—" : n.toFixed(1) + "%";
}

export function fmtPctSigned(n: number | null | undefined): string {
  return n === null || n === undefined || isNaN(n) ? "—" : (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}

export function fmtPx(n: number | null | undefined): string {
  if (n === null || n === undefined || isNaN(n)) return "—";
  if (n >= 1000) return n.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 2 });
  if (n >= 1) return n.toFixed(3);
  return n.toFixed(4);
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return String(iso).substring(0, 19).replace("T", " ");
}

export function fmtAge(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "—";
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export function colorClass(n: number | null | undefined, posT = 0): string {
  if (n === null || n === undefined || isNaN(n)) return "text-ttcc-text-secondary";
  return n > posT ? "text-ttcc-green"
    : n < posT ? "text-ttcc-red"
    : "text-ttcc-text";
}

/**
 * Hook — flashes a class for ~500ms when `value` changes direction.
 * Returns "" between flashes.
 */
import { useEffect, useRef, useState } from "react";

export function useFlashClass(value: number, tolerance = 0.0001): string {
  const prevRef = useRef<number>(value);
  const [cls, setCls] = useState<string>("");
  useEffect(() => {
    const prev = prevRef.current;
    if (Math.abs(value - prev) > tolerance) {
      setCls(value > prev ? "tt-flash-up" : "tt-flash-down");
      const t = window.setTimeout(() => setCls(""), 520);
      prevRef.current = value;
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [value, tolerance]);
  return cls;
}
