import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { useApi } from '@/hooks/use-api';

const LATEST_URL = '/api/maturity-evaluations/assets/latest';
const LEVELS_URL = '/api/maturity-levels';
const START_URL = '/api/maturity-evaluations/assets';
const POLL_MS = 2000;

export interface BulkEvaluationError {
  asset_id: string;
  code: string;
  params?: Record<string, unknown>;
}

export interface BulkEvaluationRun {
  id: string;
  state: 'running' | 'completed' | 'failed';
  scope: { catalog: string | null; schema: string | null; asset_types: string[] };
  started_by: string | null;
  started_at: string;
  finished_at: string | null;
  total: number;
  processed: number;
  evaluated: number;
  changed: number;
  skipped: Record<string, number>;
  error_count: number;
  errors: BulkEvaluationError[];
}

// The latest-run endpoint answers null before any run; anything else that isn't a run is ignored
function isRun(value: unknown): value is BulkEvaluationRun {
  return !!value && typeof value === 'object' && !Array.isArray(value) && 'id' in value;
}

/** Trigger and last-run summary of a bulk evaluation of table and view assets (admin). */
export default function MaturityBulkEvaluationCard() {
  const { get, post } = useApi();
  const { t, i18n } = useTranslation(['settings']);
  const [catalog, setCatalog] = useState('');
  const [schema, setSchema] = useState('');
  const [run, setRun] = useState<BulkEvaluationRun | null>(null);
  const [hasAssetLevels, setHasAssetLevels] = useState(false);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const running = run?.state === 'running';

  const loadLatest = async (): Promise<void> => {
    const { data } = await get<BulkEvaluationRun | null>(LATEST_URL);
    if (isRun(data)) setRun(data);
  };

  const loadHasAssetLevels = async (): Promise<void> => {
    const { data } = await get<Array<{ entity_type: string }>>(LEVELS_URL);
    setHasAssetLevels(Array.isArray(data) && data.some((level) => level.entity_type === 'Asset'));
  };

  // Load the last run and the levels once
  useEffect(() => {
    loadLatest();
    loadHasAssetLevels();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll while a run is going. The interval survives a failed poll; it ends when a
  // poll answers a run that is no longer running.
  useEffect(() => {
    if (!running) return undefined;
    const id = setInterval(() => { loadLatest(); }, POLL_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  const startRun = async () => {
    setStarting(true);
    setStartError(null);
    const { data, error, errorCode } = await post<BulkEvaluationRun>(START_URL, {
      catalog: catalog.trim() || null,
      schema_name: schema.trim() || null,
    });
    setStarting(false);
    if (error || !isRun(data)) {
      setStartError(
        errorCode
          ? t(`maturityBulkEvaluation.codes.${errorCode}`, { defaultValue: error || '' })
          : (error || ''),
      );
      return;
    }
    setRun(data);
  };

  const scopeText = (r: BulkEvaluationRun) => (
    r.scope.catalog
      ? [r.scope.catalog, r.scope.schema].filter(Boolean).join('.')
      : t('maturityBulkEvaluation.allCatalogs')
  );
  const when = (value: string | null) => (
    value ? new Date(value).toLocaleString(i18n.language) : ''
  );

  return (
    <Card data-testid="maturity-bulk-evaluation">
      <CardHeader>
        <CardTitle className="text-base">{t('maturityBulkEvaluation.title')}</CardTitle>
        <CardDescription>{t('maturityBulkEvaluation.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="maturity-bulk-catalog">{t('maturityBulkEvaluation.catalog')}</Label>
            <Input
              id="maturity-bulk-catalog"
              value={catalog}
              onChange={(e) => setCatalog(e.target.value)}
              disabled={running || starting}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="maturity-bulk-schema">{t('maturityBulkEvaluation.schema')}</Label>
            <Input
              id="maturity-bulk-schema"
              value={schema}
              onChange={(e) => setSchema(e.target.value)}
              disabled={running || starting || !catalog.trim()}
            />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button
            size="sm"
            onClick={startRun}
            disabled={!hasAssetLevels || running || starting}
          >
            {t('maturityBulkEvaluation.start')}
          </Button>
          {running && run && (
            <span className="text-sm text-muted-foreground" role="status">
              {t('maturityBulkEvaluation.running', { processed: run.processed, total: run.total })}
            </span>
          )}
        </div>
        {!hasAssetLevels && (
          <p className="text-sm text-muted-foreground">
            {t('maturityBulkEvaluation.noAssetLevels')}
          </p>
        )}
        {startError && <p className="text-sm text-red-500">{startError}</p>}

        <div className="space-y-2 border-t pt-4">
          <h4 className="text-sm font-medium">{t('maturityBulkEvaluation.lastRun')}</h4>
          {!run && (
            <p className="text-sm text-muted-foreground">{t('maturityBulkEvaluation.none')}</p>
          )}
          {run && (
            <div className="space-y-2 text-sm" data-testid="maturity-bulk-summary">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{t(`maturityBulkEvaluation.state.${run.state}`)}</Badge>
                <span className="text-muted-foreground">
                  {t('maturityBulkEvaluation.scope', { scope: scopeText(run) })}
                </span>
              </div>
              <div className="text-muted-foreground">
                {run.started_by && (
                  <span>{t('maturityBulkEvaluation.startedBy', { user: run.started_by })} · </span>
                )}
                <span>{when(run.started_at)}</span>
              </div>
              <p>
                {t('maturityBulkEvaluation.summary', {
                  total: run.total,
                  evaluated: run.evaluated,
                  changed: run.changed,
                  errors: run.error_count,
                })}
              </p>
              {Object.keys(run.skipped).length > 0 && (
                <div>
                  <span className="font-medium">{t('maturityBulkEvaluation.skipped')}: </span>
                  {Object.entries(run.skipped).map(([code, count]) => (
                    <div key={code} className="text-muted-foreground">
                      {t(`maturityBulkEvaluation.codes.${code}`)}: {count}
                    </div>
                  ))}
                </div>
              )}
              {run.error_count > 0 && (
                <div>
                  <span className="font-medium">{t('maturityBulkEvaluation.errors')}: </span>
                  {[...new Set(run.errors.map((e) => e.code))].map((code) => (
                    <div key={code} className="text-red-500">
                      {t(`maturityBulkEvaluation.codes.${code}`)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
