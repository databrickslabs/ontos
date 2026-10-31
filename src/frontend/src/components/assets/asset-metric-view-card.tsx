import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import MetricViewDefinitionPanel from '@/components/data-asset-reviews/metric-view-definition';
import { useApi } from '@/hooks/use-api';
import type { MetricViewDefinition } from '@/types/data-asset-review';

// Asset types a Unity Catalog metric view is imported as: View today, its own
// type once the Metric View asset type exists.
const METRIC_VIEW_ASSET_TYPES = new Set(['View', 'Metric View']);

type CardState = 'loading' | 'ready' | 'none' | 'noToken' | 'error';

/** Whether an asset may be a Unity Catalog metric view, so its definition is worth asking for. */
export function mayBeMetricView(
    asset: { asset_type_name?: string | null; platform?: string | null },
): boolean {
    return METRIC_VIEW_ASSET_TYPES.has(asset.asset_type_name ?? '')
        && (asset.platform ?? '').toLowerCase() === 'databricks';
}

/**
 * The metric view behind an asset: its dimensions and measures, and the
 * concepts linked to the view and to each field, read from Unity Catalog as
 * the user. Renders nothing when the asset isn't a metric view the user can
 * read (`metric_view_not_found`).
 */
export default function AssetMetricViewCard({ assetId }: { assetId: string }) {
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

    if (state === 'none') return null;

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
                    <MetricViewDefinitionPanel definition={definition} />
                )}
            </CardContent>
        </Card>
    );
}
