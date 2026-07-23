import { Skeleton as TerminalSkeleton } from "@/components/terminal/primitives";

// Single Skeleton primitive — re-exported from the terminal design system
// so both terminal pages and legacy pages share the same shimmer style.
export const Skeleton = TerminalSkeleton;

export function SkeletonMetrics() {
  return (
    <div className="grid grid-cols-3 gap-1.5 p-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex flex-col items-center gap-1.5 py-2">
          <Skeleton className="h-2 w-10" />
          <Skeleton className="h-4 w-14" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonChart({ height = 300 }: { height?: number }) {
  return <Skeleton className="w-full" style={{ height }} />;
}
