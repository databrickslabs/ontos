import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Sparkles } from 'lucide-react';
import { Sidebar } from './sidebar';
import { Header } from './header';
import { Breadcrumbs } from '@/components/ui/breadcrumbs';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
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

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => {});
  }, []);

  const showWarning = health && (!health.ws_ok || (health.warnings && health.warnings.length > 0));

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar isCollapsed={isSidebarCollapsed} />
      <div className={cn(
        "flex flex-col flex-1 transition-all duration-300 ease-in-out",
        isSidebarCollapsed ? "ml-[56px]" : "ml-[240px]",
        isCopilotOpen && "mr-[400px]"
      )}>
        <Header onToggleSidebar={toggleSidebar} isSidebarCollapsed={isSidebarCollapsed} />
        {showWarning && (
          <Alert variant="destructive" className="mx-6 mt-4">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>System Warning</AlertTitle>
            <AlertDescription>
              {!health.ws_ok && (
                <p>Databricks workspace connection failed. Some features may be unavailable.</p>
              )}
              {health.warnings?.map((w, i) => <p key={i}>{w}</p>)}
            </AlertDescription>
          </Alert>
        )}
        <main className="flex-1 overflow-y-auto p-6">
          <Breadcrumbs className="mb-6" />
          {children}
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