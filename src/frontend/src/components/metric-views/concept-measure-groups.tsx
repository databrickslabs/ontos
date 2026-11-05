import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight, Sigma } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { useApi } from '@/hooks/use-api';
import type { FingerprintGroup, MetricViewConsistency } from '@/types/metric-view-consistency';
import { DefinitionSummary, DiffList, iriLabel, measureLabel } from './consistency-parts';

function GroupCard({ group, index }: { group: FingerprintGroup; index: number }) {
    const { t } = useTranslation('metric-views');
    const title = t('concept.group', { n: index + 1 });
    return (
        <li className="border rounded p-2 space-y-2" data-testid="fingerprint-group">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{title}</span>
                {group.first_level && (
                    <Badge variant="outline" className="text-[11px]">
                        {t('concept.differsAt', { level: t(`level.${group.first_level}`) })}
                    </Badge>
                )}
                {group.score !== null && (
                    <span className="text-xs text-muted-foreground">
                        {t('similarity', { score: Math.round(group.score * 100) })}
                    </span>
                )}
            </div>
            <ul className="text-xs space-y-0.5">
                {group.measures.map((m) => (
                    <li key={m.entity_id} className="font-mono break-all">
                        {m.asset_id ? (
                            <Link
                                className="text-primary hover:underline"
                                to={`/assets/${m.asset_id}`}
                            >
                                {measureLabel(m)}
                            </Link>
                        ) : measureLabel(m)}
                    </li>
                ))}
            </ul>
            {group.definition
                ? <DefinitionSummary definition={group.definition} />
                : <p className="text-xs text-muted-foreground">{t('hidden')}</p>}
            {group.differences && (
                <DiffList
                    differences={group.differences}
                    aLabel={t('concept.onlyIn', { name: t('concept.group', { n: 1 }) })}
                    bLabel={t('concept.onlyIn', { name: title })}
                />
            )}
            {group.other_concepts.length > 0 && (
                <p className="text-xs text-destructive">
                    {t('concept.otherConcepts', {
                        concepts: group.other_concepts.map(iriLabel).join(', '),
                    })}
                </p>
            )}
        </li>
    );
}

/**
 * The metric view measures linked to a concept, grouped by definition
 * (full fingerprint), each group compared with the first. Definitions of views
 * the user can't read in Unity Catalog aren't shown. Renders nothing when no
 * metric view measure is linked to the concept.
 */
export default function ConceptMeasureGroups({ conceptIri }: { conceptIri: string }) {
    const { t } = useTranslation('metric-views');
    const { get } = useApi();
    const [data, setData] = useState<MetricViewConsistency | null>(null);
    const [open, setOpen] = useState(true);

    useEffect(() => {
        let cancelled = false;
        setData(null);
        (async () => {
            const res = await get<MetricViewConsistency>(
                `/api/metric-views/consistency?concept_iri=${encodeURIComponent(conceptIri)}`,
            );
            if (cancelled || !res || res.error || !Array.isArray(res.data?.groups)) return;
            setData(res.data);
        })();
        return () => { cancelled = true; };
    }, [conceptIri, get]);

    if (!data || (data.groups.length === 0 && data.unresolved.length === 0)) return null;
    const conflict = data.verdict === 'conflict';

    return (
        <Collapsible open={open} onOpenChange={setOpen}>
            <div className="border rounded-lg mt-3" data-testid="concept-measure-groups">
                <CollapsibleTrigger
                    className="flex items-center justify-between w-full p-3 hover:bg-muted/50"
                >
                    <div className="flex items-center gap-2">
                        {open
                            ? <ChevronDown className="h-4 w-4" />
                            : <ChevronRight className="h-4 w-4" />}
                        <Sigma className="h-4 w-4 text-muted-foreground" />
                        <span className="font-medium text-sm">{t('concept.title')}</span>
                        {data.verdict && data.verdict !== 'none' && (
                            <Badge
                                variant={conflict ? 'destructive' : 'secondary'}
                                className="text-[11px]"
                            >
                                {t(`concept.verdict.${data.verdict}`)}
                            </Badge>
                        )}
                    </div>
                </CollapsibleTrigger>
                <CollapsibleContent>
                    <div className="px-3 pb-3 space-y-2">
                        {data.verdict && data.verdict !== 'none' && (
                            <p className="text-xs text-muted-foreground">
                                {t(`concept.hint.${data.verdict}`, { count: data.groups.length })}
                            </p>
                        )}
                        <ul className="space-y-2">
                            {data.groups.map((group, i) => (
                                <GroupCard key={group.full_digest} group={group} index={i} />
                            ))}
                        </ul>
                        {data.unresolved.length > 0 && (
                            <p className="text-xs text-muted-foreground">
                                {t('concept.unresolved', {
                                    fields: data.unresolved.map(measureLabel).join(', '),
                                })}
                            </p>
                        )}
                    </div>
                </CollapsibleContent>
            </div>
        </Collapsible>
    );
}
