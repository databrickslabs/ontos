import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useApi } from '@/hooks/use-api';
import type {
    MeasureConsistency,
    MeasureMatch,
    MetricViewConsistency,
} from '@/types/metric-view-consistency';
import { DiffList, VerdictBadge, iriLabel, measureLabel } from './consistency-parts';

function MatchRow({ match, measureName }: { match: MeasureMatch; measureName: string }) {
    const { t } = useTranslation('metric-views');
    const other = match.measure;
    const label = measureLabel(other);
    return (
        <li className="space-y-1" data-testid="measure-match">
            <div className="flex flex-wrap items-center gap-2">
                <VerdictBadge verdict={match.verdict} />
                {other.asset_id ? (
                    <Link
                        className="font-mono text-xs text-primary hover:underline break-all"
                        to={`/assets/${other.asset_id}`}
                    >
                        {label}
                    </Link>
                ) : (
                    <span className="font-mono text-xs break-all">{label}</span>
                )}
                {match.score !== null && match.verdict !== 'duplicate' && (
                    <span className="text-xs text-muted-foreground">
                        {t('similarity', { score: Math.round(match.score * 100) })}
                    </span>
                )}
                {other.concepts.length > 0 && (
                    <span className="text-xs text-muted-foreground">
                        {t('asset.linkedTo', { concepts: other.concepts.map(iriLabel).join(', ') })}
                    </span>
                )}
            </div>
            {match.differences ? (
                <DiffList
                    differences={match.differences}
                    aLabel={t('asset.onlyIn', { name: measureName })}
                    bLabel={t('asset.onlyIn', { name: label })}
                />
            ) : (
                <p className="text-xs text-muted-foreground">{t('hidden')}</p>
            )}
        </li>
    );
}

function MeasureBlock({ item }: { item: MeasureConsistency }) {
    const { t } = useTranslation('metric-views');
    const name = item.measure.display_name || item.measure.name;
    return (
        <li className="border rounded p-2 space-y-1" data-testid="measure-consistency">
            <div className="text-sm font-medium">{name}</div>
            {item.error ? (
                <p className="text-xs text-muted-foreground">{t(`asset.error.${item.error}`)}</p>
            ) : (
                <ul className="space-y-2">
                    {item.matches.map((match) => (
                        <MatchRow key={match.measure.entity_id} match={match} measureName={name} />
                    ))}
                </ul>
            )}
        </li>
    );
}

/**
 * Per measure of a metric view asset: other measures with the same or a similar
 * definition over the same data, and conflicting links (read-only). Measures
 * without any match are left out; renders nothing when no measure has one.
 */
export default function MeasureConsistencyList({ assetId }: { assetId: string }) {
    const { t } = useTranslation('metric-views');
    const { get } = useApi();
    const [data, setData] = useState<MetricViewConsistency | null>(null);

    useEffect(() => {
        let cancelled = false;
        setData(null);
        (async () => {
            const res = await get<MetricViewConsistency>(
                `/api/metric-views/consistency?asset_id=${encodeURIComponent(assetId)}`,
            );
            if (cancelled || !res || res.error || !Array.isArray(res.data?.measures)) return;
            setData(res.data);
        })();
        return () => { cancelled = true; };
    }, [assetId, get]);

    const shown = (data?.measures ?? []).filter((m) => m.error || m.matches.length > 0);
    if (shown.length === 0) return null;

    return (
        <div className="space-y-2 mt-4" data-testid="measure-consistency-list">
            <h4 className="text-sm font-semibold">{t('asset.title')}</h4>
            <p className="text-xs text-muted-foreground">{t('asset.hint')}</p>
            <ul className="space-y-2">
                {shown.map((item) => <MeasureBlock key={item.measure.entity_id} item={item} />)}
            </ul>
        </div>
    );
}
