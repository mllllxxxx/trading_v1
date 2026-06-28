import { useEffect } from "react";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import { cn } from "@/components/terminal/primitives";

/**
 * ConfirmDialog — modal confirmation with keyboard shortcuts.
 * Esc cancels, Enter confirms. Click on backdrop cancels.
 */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  danger,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter") onConfirm();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel, onConfirm]);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onCancel}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-[360px] max-w-[92vw] rounded-md border border-ttcc-border bg-ttcc-surface p-4 shadow-2xl tt-toast-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 text-sm font-semibold text-ttcc-text">
          {danger ? (
            <ShieldAlert className="h-4 w-4 text-ttcc-red" />
          ) : (
            <AlertTriangle className="h-4 w-4 text-ttcc-yellow" />
          )}
          {title}
        </div>
        <div className="mt-2 text-xs text-ttcc-text-secondary">{body}</div>
        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded border border-ttcc-border bg-ttcc-surface-2 px-2.5 py-1 text-xs text-ttcc-text-secondary hover:text-ttcc-text transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={cn(
              "rounded border px-2.5 py-1 text-xs font-semibold transition-colors",
              danger
                ? "border-ttcc-red/60 bg-ttcc-red/15 text-ttcc-red hover:bg-ttcc-red/25"
                : "border-ttcc-green/60 bg-ttcc-green/15 text-ttcc-green hover:bg-ttcc-green/25"
            )}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
