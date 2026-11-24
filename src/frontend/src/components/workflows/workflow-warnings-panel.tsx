import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle, XCircle } from 'lucide-react';

export interface WorkflowIssueItem {
  key: string;
  tone: 'error' | 'warning';
  text: string;
  /** Canvas nodes the issue is about; a click selects the first one */
  nodeIds: string[];
}

export interface WorkflowWarningsPanelProps {
  items: WorkflowIssueItem[];
  /** A check ran and found no problems */
  clean: boolean;
  onSelectNode: (nodeId: string) => void;
}

/** Summary of the problems the designer found: errors of a check, and warnings that don't block a save (#1438). */
export function WorkflowWarningsPanel({ items, clean, onSelectNode }: WorkflowWarningsPanelProps) {
  const { t } = useTranslation(['workflows']);
  if (items.length === 0 && !clean) return null;

  const errorCount = items.filter(item => item.tone === 'error').length;
  const warningCount = items.length - errorCount;

  return (
    <div
      role="status"
      data-testid="workflow-warnings"
      className="max-w-md max-h-[40vh] overflow-auto bg-background/95 backdrop-blur-sm border border-border rounded-lg shadow-lg p-3 space-y-2 dark:bg-slate-800/95"
    >
      {items.length === 0 ? (
        <p className="flex items-center gap-2 text-sm text-green-700 dark:text-green-400">
          <CheckCircle className="h-4 w-4 shrink-0" />
          {t('workflows:designer.checks.clean')}
        </p>
      ) : (
        <>
          <p className="text-sm font-medium">
            {[
              errorCount > 0 && t('workflows:designer.checks.errorsCount', { count: errorCount }),
              warningCount > 0 && t('workflows:designer.checks.warningsCount', { count: warningCount }),
            ].filter(Boolean).join(', ')}
          </p>
          <ul className="space-y-1">
            {items.map(item => {
              const Icon = item.tone === 'error' ? XCircle : AlertTriangle;
              const tone = item.tone === 'error' ? 'text-destructive' : 'text-amber-700 dark:text-amber-400';
              const content = (
                <>
                  <Icon className="mt-0.5 h-4 w-4 shrink-0" />
                  <span className="text-left">{item.text}</span>
                </>
              );
              return (
                <li key={item.key} className={`text-xs ${tone}`}>
                  {item.nodeIds.length > 0 ? (
                    <button
                      type="button"
                      className="flex items-start gap-2 rounded-sm hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onClick={() => onSelectNode(item.nodeIds[0])}
                    >
                      {content}
                    </button>
                  ) : (
                    <div className="flex items-start gap-2">{content}</div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
