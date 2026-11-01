import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import MetricViewDefinitionPanel from '@/components/data-asset-reviews/metric-view-definition';
import MetricViewStatus from '@/components/assets/metric-view-status';
import { useApi } from '@/hooks/use-api';
import type { MetricViewDefinition } from '@/types/data-asset-review';

const METRIC_VIEW_TYPE = 'Metric View';
// A metric view is imported as a Metric View asset; one imported before that type
// existed is still a View until it is re-imported, so Views are asked too.
const METRIC_VIEW_ASSET_TYPES = new Set(['View', METRIC_VIEW_TYPE]);

type CardState = 'loading' | 'ready' | 'none' | 'noToken' | 'error';

/** Whether an asset may be a Unity Catalog metric view, so its definition is worth asking for. */
export function mayBeMetricView(
    asset: { asset_type_name?: string | null; platform?: string | null },
): boolean {
    return METRIC_VIEW_ASSET_TYPES.has(asset.asset_type_name ?? '')
        && (asset.platform ?? '').toLowerCase() === 'databricks';
}

/**
 * The metric view behind an asset: its dimensions and measures, the
 * concepts linked to the view and to each field, its drift from the baseline
 * and its refresh state, read from Unity Catalog as the user. Renders
 * nothing when the asset isn't a metric view the user can read
 * (`metric_view_not_found`).
 *
 * On a View asset (most are plain views) the card only appears once the
 * metric view is loaded: loading, a missing token and errors stay silent
 * there. A Metric View asset shows them.
 */
export default function AssetMetricViewCard({ assetId, assetTypeName }: {
    assetId: string;
    assetTypeName?: string | null;
}) {
    const quiet = assetTypeName !== METRIC_VIEW_TYPE;
    const { t } = useTranslation('assets');
    const { get } = useApi();
    const [definition, setDefinition] = useState<MetricViewDefinition | null>(null);
    const [state, setState] = useState<CardState>('loading');

    useEffect(() => {
        let cancelled = false;
        setState('loading');
        setDefinition(null);
        (async () => {
            const res = await get<MetricViewDefinition>(`/api/assets/${assetId}/metric-view`);
            if (cancelled) return;
            if (res.errorCode === 'metric_view_not_found') {
                setState('none');
            } else if (res.errorCode === 'user_token_required') {
                // Unity Catalog is read as the user: without their token nothing is read
                setState('noToken');
            } else if (res.error || !res.data || typeof res.data.definition !== 'string') {
                setState('error');
            } else {
                setDefinition(res.data);
                setState('ready');
            }
        })();
        return () => { cancelled = true; };
    }, [assetId, get]);

    if (state === 'none' || (quiet && state !== 'ready')) return null;

    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="text-base">{t('detail.metricView.title')}</CardTitle>
            </CardHeader>
            <CardContent>
                {state === 'loading' && (
                    <div className="flex justify-center py-6">
                        <Loader2
                            className="h-6 w-6 animate-spin text-muted-foreground"
                            aria-label={t('detail.metricView.loading')}
                        />
                    </div>
                )}
                {state === 'noToken' && (
                    <p className="text-sm text-muted-foreground">
                        {t('detail.metricView.userTokenRequired')}
                    </p>
                )}
                {state === 'error' && (
                    <p className="text-sm text-muted-foreground">
                        {t('detail.metricView.loadError')}
                    </p>
                )}
                {state === 'ready' && definition && (
                    <>
                        <MetricViewStatus
                            baseline={definition.baseline}
                            drift={definition.drift}
                            refresh={definition.refresh}
                        />
                        <MetricViewDefinitionPanel definition={definition} />
                    </>
                )}
            </CardContent>
        </Card>
    );
}
