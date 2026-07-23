import { Link } from "react-router-dom";
import { Home, AlertTriangle } from "lucide-react";

export function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center">
      <AlertTriangle className="h-12 w-12 text-ttcc-yellow" />
      <div>
        <h1 className="text-2xl font-bold text-ttcc-text">404 — Page not found</h1>
        <p className="mt-2 text-sm text-ttcc-text-secondary">
          The page you're looking for doesn't exist or has been moved.
        </p>
      </div>
      <Link
        to="/"
        className="inline-flex items-center gap-2 rounded-lg border border-ttcc-accent/50 bg-ttcc-accent/10 px-4 py-2 text-sm font-medium text-ttcc-accent hover:bg-ttcc-accent/20 transition-colors"
      >
        <Home className="h-4 w-4" />
        Back to Terminal
      </Link>
    </div>
  );
}
