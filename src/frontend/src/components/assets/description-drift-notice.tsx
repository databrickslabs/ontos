import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { GitCompare, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useApi } from '@/hooks/use-api';
import { DescriptionCompareDialog } from '@/components/assets/description-compare-dialog';
import type { AssetDescriptionDrift } from '@/types/asset';

interface Props {
  assetId: string;
  assetTypeName?: string | null;
  /** Whether Unity Catalog may be read for this asset (a Databricks table, view or column) */
  enabled: boolean;
  /** Changes when the asset was saved, so Unity Catalog is read again. */
  refreshKey?: string | null;
  /** Called after descriptions were replaced, so the asset is read again. */
  onReset: () => void;
}

/**
 * When a table, view or column asset opens, Unity Catalog is read once as the user (on demand,
 * never by a job) and the page says so if its comment changed since Ontos last saw it. A table
 * or view also offers "Compare with Unity Catalog" for itself and its columns. A failed read
 * (no token, no SELECT, metric view) shows nothing: the page works without it.
 */
export function DescriptionDriftNotice({
  assetId, assetTypeName, enabled, refreshKey, onReset,
}: Props) {
  const { t } = useTranslation(['assets']);
  const { get } = useApi();
  const [drift, setDrift] = useState<AssetDescriptionDrift | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setDrift(null);
      return;
    }
    let cancelled = false;
    get<AssetDescriptionDrift>(`/api/assets/${assetId}/description/drift`).then((res) => {
      if (!cancelled) setDrift(res.error || !res.data ? null : res.data);
    });
    return () => { cancelled = true; };
  }, [assetId, enabled, refreshKey, get]);

  if (!enabled || !drift) return null;
  const own = drift.fields[0];
  const others = drift.fields.slice(1).filter((f) => f.changed_in_uc && f.differs).length;
  const canCompare = (assetTypeName ?? '').trim().toLowerCase() !== 'column';

  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-sm" data-testid="description-drift">
      {own?.changed_in_uc && own.differs && (
        <Badge variant="secondary" className="gap-1 text-amber-700 dark:text-amber-400">
          <RefreshCw className="h-3 w-3" />
          {t('assets:descriptionDrift.changedInUc')}
        </Badge>
      )}
      {others > 0 && (
        <Badge variant="secondary" className="gap-1 text-amber-700 dark:text-amber-400">
          <RefreshCw className="h-3 w-3" />
          {t('assets:descriptionDrift.columnsChangedInUc', { count: others })}
        </Badge>
      )}
      {canCompare && (
        <Button
          type="button" variant="link" size="sm" className="h-auto p-0 text-xs"
          onClick={() => setCompareOpen(true)}
        >
          <GitCompare className="mr-1 h-3 w-3" />
          {t('assets:descriptionDrift.compare')}
        </Button>
      )}
      {canCompare && (
        <DescriptionCompareDialog
          assetId={assetId} open={compareOpen} onOpenChange={setCompareOpen} onReset={onReset}
        />
      )}
    </div>
  );
}
