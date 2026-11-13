import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  CheckCircle2, XCircle, AlertTriangle, Loader2, RefreshCw, TrendingUp,
  ChevronDown, ChevronRight,
} from 'lucide-react';
import { MaturityBadge } from '@/components/common/maturity-badge';
import type { TFunction } from 'i18next';
import type {
  MaturityReport, LevelResult, MaturitySnapshot, GateResult,
} from '@/types/maturity';

interface MaturityPanelProps {
  /** 'Asset' only for table and view assets (other asset types have no maturity) */
  entityType: 'DataProduct' | 'DataContract' | 'Asset';
  entityId: string;
}

const STATUS_CONFIG = {
  pass: { icon: CheckCircle2, color: 'text-green-600 dark:text-green-400', bg: 'bg-green-50 dark:bg-green-950/30' },
  fail: { icon: XCircle, color: 'text-red-600 dark:text-red-400', bg: 'bg-red-50 dark:bg-red-950/30' },
  warn: { icon: AlertTriangle, color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-50 dark:bg-amber-950/30' },
};

const API_PREFIX: Record<string, string> = {
  DataProduct: '/api/data-products',
  DataContract: '/api/data-contracts',
  Asset: '/api/assets',
};

/** Why a gate failed: a coded reason in the UI language, else the policy's failure text. */
function gateReason(gate: GateResult, t: TFunction): string | null {
  if (gate.passed) return null;
  if (gate.message_code) {
    return t(`data-products:maturityGateCodes.${gate.message_code}`, {
      ...(gate.message_params ?? {}),
      defaultValue: gate.failure_message || gate.message || '',
    });
  }
  return gate.failure_message || gate.message || null;
}

export function MaturityPanel({ entityType, entityId }: MaturityPanelProps) {
  const { t } = useTranslation(['data-products', 'common']);
  const [report, setReport] = useState<MaturityReport | null>(null);
  const [history, setHistory] = useState<MaturitySnapshot[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // undefined = not chosen by the user yet: the next level to reach is open
  const [expandedLevel, setExpandedLevel] = useState<number | null | undefined>(undefined);

  const prefix = API_PREFIX[entityType] || API_PREFIX.DataProduct;

  const fetchReport = useCallback(async (evaluate = false) => {
    setIsLoading(true);
    setError(null);
    try {
      const url = evaluate
        ? `${prefix}/${entityId}/maturity/evaluate`
        : `${prefix}/${entityId}/maturity`;
      const method = evaluate ? 'POST' : 'GET';
      const res = await fetch(url, { method });
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      setReport(await res.json());
    } catch (e: any) {
      setError(e.message || t('data-products:maturity.loadFailed'));
    } finally {
      setIsLoading(false);
    }
  }, [entityId, prefix, t]);

  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch(`${prefix}/${entityId}/maturity/history?limit=10`);
      if (res.ok) setHistory(await res.json());
    } catch { /* non-critical */ }
  }, [entityId, prefix]);

  useEffect(() => { fetchReport(); fetchHistory(); }, [fetchReport, fetchHistory]);

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <span className="ml-2 text-sm text-muted-foreground">{t('data-products:maturity.evaluating')}</span>
        </CardContent>
      </Card>
    );
  }

  if (error || !report) {
    return (
      <Card>
        <CardContent className="py-6 text-center">
          <p className="text-sm text-destructive">{error || t('data-products:maturity.unableToLoad')}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={() => fetchReport()}>
            <RefreshCw className="mr-2 h-3.5 w-3.5" /> {t('data-products:maturity.retry')}
          </Button>
        </CardContent>
      </Card>
    );
  }

  const nextLevel = report.levels.find((l) => !l.achieved) ?? null;
  const openLevel = expandedLevel === undefined ? nextLevel?.level_order ?? null : expandedLevel;
  const currentLabel = report.achieved_level_name
    || (report.total_levels > 0
      ? t('data-products:maturity.belowFirstLevel')
      : t('common:maturity.notAssessed'));

  return (
    <Card data-testid="maturity-panel">
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            {t('data-products:maturity.title')}
          </span>
          <div className="flex items-center gap-2">
            <span className="text-sm font-normal text-muted-foreground">
              {t('data-products:maturity.gatesPassed', { passed: report.gates_passed, total: report.gates_total })}
            </span>
            <MaturityBadge
              levelName={report.achieved_level_name}
              levelOrder={report.achieved_level_order}
              totalLevels={report.total_levels}
              emptyLabel={report.total_levels > 0
                ? t('data-products:maturity.belowFirstLevel')
                : undefined}
            />
            <Button variant="ghost" size="icon" className="h-7 w-7"
              onClick={() => { fetchReport(true); fetchHistory(); }}
              title={t('data-products:maturity.reevaluate')}>
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {report.notices?.map((notice) => (
          <p key={notice.code} className="text-xs text-muted-foreground">
            {t(`data-products:maturityGateCodes.${notice.code}`, {
              ...(notice.params ?? {}),
              defaultValue: notice.message,
            })}
          </p>
        ))}
        {report.total_levels === 0 ? (
          <p className="text-sm text-muted-foreground">{t('data-products:maturity.noLevels')}</p>
        ) : (
          <dl
            className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2"
            data-testid="maturity-summary"
          >
            <div>
              <dt className="text-xs text-muted-foreground">
                {t('data-products:maturity.currentLevel')}
              </dt>
              <dd className="font-medium">{currentLabel}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">
                {t('data-products:maturity.nextLevel')}
              </dt>
              <dd className="font-medium">
                {nextLevel ? nextLevel.level_name : t('data-products:maturity.topLevelReached')}
              </dd>
            </div>
          </dl>
        )}
        {/* Level progression */}
        {report.levels.map((level: LevelResult) => {
          const isExpanded = openLevel === level.level_order;
          const hasWarnings = level.gates.some(g => !g.passed && !g.required);
          const hasFails = level.gates.some(g => !g.passed && g.required);

          let levelStatus: 'pass' | 'fail' | 'warn' = 'pass';
          if (hasFails) levelStatus = 'fail';
          else if (hasWarnings) levelStatus = 'warn';

          const cfg = STATUS_CONFIG[levelStatus];
          const LevelIcon = cfg.icon;

          return (
            <div key={level.level_order} className="rounded-md border overflow-hidden">
              <button
                className={`flex items-center gap-3 w-full px-3 py-2.5 text-left ${cfg.bg}`}
                aria-expanded={isExpanded}
                onClick={() => setExpandedLevel(isExpanded ? null : level.level_order)}
              >
                <LevelIcon className={`h-4 w-4 flex-shrink-0 ${cfg.color}`} />
                {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                <span className="font-mono text-xs text-muted-foreground w-4">{level.level_order}</span>
                <span className="text-sm font-medium flex-1">{level.level_name}</span>
                <span className="text-xs text-muted-foreground">
                  {t('data-products:maturity.gates', { passed: level.gates.filter(g => g.passed).length, total: level.gates.length })}
                </span>
              </button>

              {isExpanded && level.gates.length > 0 && (
                <div className="px-3 py-2 space-y-1 bg-background">
                  {level.gates.map((gate, gi) => {
                    const gStatus = gate.passed ? 'pass' : (gate.required ? 'fail' : 'warn');
                    const gCfg = STATUS_CONFIG[gStatus];
                    const GateIcon = gCfg.icon;
                    const reason = gateReason(gate, t);
                    return (
                      <div key={gate.gate_id || gi} className="flex items-start gap-2 py-1"
                        data-testid="maturity-gate" data-status={gStatus}>
                        <GateIcon className={`h-3.5 w-3.5 mt-0.5 flex-shrink-0 ${gCfg.color}`}
                          aria-hidden="true" />
                        <div className="min-w-0 flex-1">
                          <p className="text-xs font-medium">{gate.policy_name}</p>
                          {reason && <p className="text-xs text-muted-foreground">{reason}</p>}
                        </div>
                        <span className={`text-[10px] font-medium ${gCfg.color}`}>
                          {t(`data-products:maturity.gateStatus.${gStatus}`)}
                        </span>
                        <Badge variant="outline" className="text-[10px]">
                          {gate.required ? t('data-products:maturity.required') : t('data-products:maturity.advisory')}
                        </Badge>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        {/* History mini-chart */}
        {history.length > 1 && (
          <div className="pt-2 border-t">
            <p className="text-xs text-muted-foreground mb-2">{t('data-products:maturity.overTime')}</p>
            <div className="flex items-end gap-0.5 h-8">
              {history.slice().reverse().map((snap, i) => {
                const maxLevel = snap.total_levels || 5;
                const pct = snap.achieved_level_order != null
                  ? Math.max(10, (snap.achieved_level_order / maxLevel) * 100)
                  : 5;
                return (
                  <div
                    key={snap.id || i}
                    className="bg-primary/60 rounded-t flex-1 min-w-1"
                    style={{ height: `${pct}%` }}
                    title={`${snap.achieved_level_name || 'None'} (${new Date(snap.evaluated_at).toLocaleDateString()})`}
                  />
                );
              })}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
