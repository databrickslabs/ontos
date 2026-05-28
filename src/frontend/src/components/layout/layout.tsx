import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, DatabaseZap, Sparkles } from 'lucide-react';
import { Sidebar } from './sidebar';
import { Header } from './header';
import { Breadcrumbs } from '@/components/ui/breadcrumbs';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useLayoutStore } from '@/stores/layout-store';
import { useCopilotStore } from '@/stores/copilot-store';
import CopilotPanel from '@/components/copilot/copilot-panel';

interface HealthState {
  db_ok: boolean;
  ws_ok: boolean;
  warnings: string[];
  db_error: string | null;
}

const HEALTH_POLL_INTERVAL_MS = 30_000;

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const { t } = useTranslation(['search']);
  const isSidebarCollapsed = useLayoutStore((state) => state.isSidebarCollapsed);
  const { toggleSidebar } = useLayoutStore((state) => state.actions);
  const isCopilotOpen = useCopilotStore((s) => s.isOpen);
  const { togglePanel } = useCopilotStore((s) => s.actions);
  const [health, setHealth] = useState<HealthState | null>(null);
  const [isRetrying, setIsRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  const refreshHealth = useCallback(async (): Promise<HealthState | null> => {
    try {
      const r = await fetch('/api/health');
      const h = (await r.json()) as HealthState;
      setHealth(h);
      return h;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    refreshHealth();
  }, [refreshHealth]);

  // Auto-poll while the DB is down so recovery is hands-free in dev too
  // (in prod, the FastAPI catch-all serves MAINTENANCE_HTML, which has its
  // own setInterval; this covers the Vite dev case where the SPA shell
  // boots before the middleware can intercept).
  useEffect(() => {
    if (!health || health.db_ok) return;
    const id = setInterval(() => {
      refreshHealth();
    }, HEALTH_POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [health, refreshHealth]);

  const handleRetry = useCallback(async () => {
    setIsRetrying(true);
    setRetryError(null);
    try {
      const r = await fetch('/api/health/retry', { method: 'POST' });
      const d = await r.json().catch(() => ({}));
      if (r.ok) {
        // Hard reload so permissions store, managers, search index, etc.
        // are re-fetched cleanly after recovery.
        window.location.reload();
        return;
      }
      setRetryError(d?.detail || 'Retry failed');
      await refreshHealth();
    } catch (e) {
      setRetryError(e instanceof Error ? e.message : 'Network error');
    } finally {
      setIsRetrying(false);
    }
  }, [refreshHealth]);

  const isDbDown = !!health && !health.db_ok;
  // Suppress the soft warning banner when the DB is down: startup short-circuits
  // before initialize_managers runs, so ws_ok stays false even though the real
  // problem is the DB. Showing both would be misleading.
  const showWarning =
    !!health &&
    !isDbDown &&
    (!health.ws_ok || (health.warnings && health.warnings.length > 0));

  return (
    <div className="min-h-screen bg-background">
      <Sidebar isCollapsed={isSidebarCollapsed} />
      {/* Sidebar/copilot offsets use padding (not margin) so the column
          stays at 100vw and never overflows horizontally. The Sidebar is
          position:fixed and contributes no flex/inline width. */}
      <div className={cn(
        "flex flex-col min-h-screen min-w-0 transition-[padding] duration-300 ease-in-out",
        isSidebarCollapsed ? "pl-[56px]" : "pl-[240px]",
        isCopilotOpen && "pr-[400px]"
      )}>
        <Header onToggleSidebar={toggleSidebar} isSidebarCollapsed={isSidebarCollapsed} />
        {/* Alerts wrapped in padded containers (not mx-6 on the Alert itself):
            shadcn Alert is `w-full`, so mx-6 would expand it past the
            parent and overflow horizontally by the margin width. */}
        {isDbDown && (
          <div className="px-6 pt-4">
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>Database unavailable</AlertTitle>
              <AlertDescription className="space-y-2">
                <p>
                  The application cannot reach its metadata database. Most features will
                  return errors until the connection is restored.
                </p>
                {health?.db_error && (
                  <pre className="text-xs whitespace-pre-wrap break-words bg-muted/40 rounded p-2 max-h-32 overflow-auto">
                    {health.db_error}
                  </pre>
                )}
                <div className="flex items-center gap-2 pt-1 flex-wrap">
                  <Button size="sm" onClick={handleRetry} disabled={isRetrying}>
                    {isRetrying ? 'Retrying…' : 'Retry connection'}
                  </Button>
                  {retryError && (
                    <span className="text-xs text-destructive">{retryError}</span>
                  )}
                  <span className="text-xs text-muted-foreground ml-auto">
                    Auto-retrying every {HEALTH_POLL_INTERVAL_MS / 1000} seconds
                  </span>
                </div>
              </AlertDescription>
            </Alert>
          </div>
        )}
        {showWarning && (
          <div className="px-6 pt-4">
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>System Warning</AlertTitle>
              <AlertDescription>
                {!health.ws_ok && (
                  <p>Databricks workspace connection failed. Some features may be unavailable.</p>
                )}
                {health.warnings?.map((w, i) => <p key={i}>{w}</p>)}
              </AlertDescription>
            </Alert>
          </div>
        )}
        <main className="flex-1 overflow-y-auto p-6">
          {isDbDown ? (
            // Don't render the routed page when the DB is down: most views
            // immediately fetch /api/* which 503s, producing noisy half-broken
            // UI (empty lists, inline error toasts, "HTTP error! status: 503").
            // Show a neutral placeholder instead — the banner above is the
            // single source of truth and offers the retry path.
            <div className="flex flex-col items-center justify-center text-center py-24 text-muted-foreground">
              <DatabaseZap className="h-12 w-12 mb-4 opacity-60" />
              <h2 className="text-lg font-medium text-foreground mb-1">
                Application paused
              </h2>
              <p className="text-sm max-w-md">
                The metadata database is unreachable, so navigation and data
                views are disabled to avoid showing inconsistent state. Use
                <span className="font-medium"> Retry connection </span>
                above (or wait for the next auto-retry) to resume.
              </p>
            </div>
          ) : (
            <>
              <Breadcrumbs className="mb-6" />
              {children}
            </>
          )}
        </main>
      </div>

      {/* Right-edge Ask Ontos tab */}
      {!isCopilotOpen && (
        <button
          onClick={togglePanel}
          className="fixed right-0 top-1/2 -translate-y-1/2 z-40
            flex flex-col items-center gap-2 px-1.5 py-4
            bg-gradient-to-b from-violet-500 to-purple-600
            text-white rounded-l-xl shadow-lg
            hover:px-2.5 hover:shadow-violet-500/25 hover:shadow-xl
            transition-all duration-200"
        >
          <Sparkles className="h-4 w-4 shrink-0" />
          <span className="text-xs font-medium [writing-mode:vertical-rl] rotate-180">
            {t('search:copilot.button')}
          </span>
        </button>
      )}

      <CopilotPanel />
    </div>
  );
} 