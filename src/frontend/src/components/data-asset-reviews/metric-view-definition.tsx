import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import ConceptSelectDialog from '@/components/semantic/concept-select-dialog';
import LinkedConceptChips from '@/components/semantic/linked-concept-chips';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import type { EntitySemanticLink } from '@/types/semantic-link';
import type { LinkCheck, LinkWarning } from '@/types/metric-view-consistency';
import MetricViewLinkWarnings from '@/components/metric-views/metric-view-link-warnings';
import {
    MetricViewDefinition,
    MetricViewField,
    MetricViewFieldLinks,
    MetricViewLinks,
} from '@/types/data-asset-review';

interface MetricViewDefinitionPanelProps {
    definition: MetricViewDefinition;
}

/** What a concept is linked to: the view (`uc_table`) or one of its fields (`uc_column`). */
interface LinkTarget {
    entityType: 'uc_table' | 'uc_column';
    entityId: string;
    name: string;
}

/** The links with `link` added to the view or the field whose entity id is `entityId`. */
function withLink(
    links: MetricViewLinks, entityId: string, link: EntitySemanticLink,
): MetricViewLinks {
    const add = (list: EntitySemanticLink[]) =>
        list.some((l) => l.id === link.id) ? list : [...list, link];
    const addToField = (f: MetricViewFieldLinks) =>
        f.entity_id === entityId ? { ...f, links: add(f.links) } : f;
    return {
        ...links,
        view_links: links.view_entity_id === entityId ? add(links.view_links) : links.view_links,
        fields: links.fields.map(addToField),
        removed_fields: links.removed_fields.map(addToField),
    };
}

/** The links without the link `linkId`. */
function withoutLink(links: MetricViewLinks, linkId: string): MetricViewLinks {
    const drop = (list: EntitySemanticLink[]) => list.filter((l) => l.id !== linkId);
    const dropFromField = (f: MetricViewFieldLinks) => ({ ...f, links: drop(f.links) });
    return {
        ...links,
        view_links: drop(links.view_links),
        fields: links.fields.map(dropFromField),
        removed_fields: links.removed_fields.map(dropFromField),
    };
}

function ConceptCell({ links, target, canEdit, onAdd, onRemove }: {
    links: EntitySemanticLink[];
    target: LinkTarget;
    canEdit: boolean;
    onAdd: (target: LinkTarget) => void;
    onRemove: (linkId: string) => void;
}) {
    const { t } = useTranslation('data-asset-reviews');
    return (
        <LinkedConceptChips
            links={links}
            onRemove={canEdit ? onRemove : undefined}
            trailing={canEdit ? (
                <Button
                    size="sm"
                    variant="outline"
                    className="h-6 text-xs"
                    aria-label={t('editor.metricView.linkConceptTo', { name: target.name })}
                    onClick={() => onAdd(target)}
                >
                    {t('editor.metricView.linkConcept')}
                </Button>
            ) : undefined}
        />
    );
}

interface FieldLinksProps {
    linksByName: Map<string, MetricViewFieldLinks> | null;
    canEdit: boolean;
    onAdd: (target: LinkTarget) => void;
    onRemove: (linkId: string) => void;
}

function FieldTable({ title, fields, empty, linksByName, canEdit, onAdd, onRemove }: {
    title: string;
    fields: MetricViewField[];
    empty: string;
} & FieldLinksProps) {
    const { t } = useTranslation('data-asset-reviews');
    return (
        <div className="space-y-1">
            <h4 className="text-sm font-semibold">{title} <span className="text-muted-foreground font-normal">({fields.length})</span></h4>
            {fields.length === 0 ? (
                <p className="text-xs text-muted-foreground">{empty}</p>
            ) : (
                <table className="w-full text-xs border rounded">
                    <thead className="bg-muted/50">
                        <tr>
                            <th className="text-left p-2 font-medium">{t('editor.metricView.name')}</th>
                            <th className="text-left p-2 font-medium">{t('editor.metricView.expression')}</th>
                            {linksByName && (
                                <th className="text-left p-2 font-medium">
                                    {t('editor.metricView.concepts')}
                                </th>
                            )}
                        </tr>
                    </thead>
                    <tbody>
                        {fields.map((field) => {
                            const fieldLinks = linksByName?.get(field.name);
                            return (
                                <tr key={field.name} className="border-t align-top">
                                    <td className="p-2">
                                        <div className="font-medium">
                                            {field.display_name || field.name}
                                        </div>
                                        {field.comment && (
                                            <div className="text-muted-foreground">
                                                {field.comment}
                                            </div>
                                        )}
                                    </td>
                                    <td className="p-2 font-mono break-all">{field.expr ?? ''}</td>
                                    {linksByName && (
                                        <td className="p-2">
                                            {fieldLinks && (
                                                <ConceptCell
                                                    links={fieldLinks.links}
                                                    target={{
                                                        entityType: 'uc_column',
                                                        entityId: fieldLinks.entity_id,
                                                        name: field.display_name || field.name,
                                                    }}
                                                    canEdit={canEdit}
                                                    onAdd={onAdd}
                                                    onRemove={onRemove}
                                                />
                                            )}
                                        </td>
                                    )}
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            )}
        </div>
    );
}

/**
 * A Unity Catalog metric view's spec: its source, dimensions and measures, and the YAML.
 *
 * When the definition carries `links`, the concepts linked to the view and to
 * each dimension and measure are shown, and users who can edit semantic links
 * can link and unlink them. Links of fields that are no longer in the
 * definition are listed apart, so they can be reviewed and removed.
 */
export default function MetricViewDefinitionPanel({ definition }: MetricViewDefinitionPanelProps) {
    const { t } = useTranslation('data-asset-reviews');
    const { get, post, delete: apiDelete } = useApi();
    const { toast } = useToast();
    const { hasPermission } = usePermissions();
    const canEdit = hasPermission('semantic-models', FeatureAccessLevel.READ_WRITE);
    const spec = definition.metric_view;

    const [links, setLinks] = useState<MetricViewLinks | null>(definition.links ?? null);
    const [target, setTarget] = useState<LinkTarget | null>(null);
    const [linkWarnings, setLinkWarnings] = useState<
        { name: string; warnings: LinkWarning[] } | null
    >(null);
    useEffect(() => setLinks(definition.links ?? null), [definition]);

    const linksOf = (kind: 'dimension' | 'measure') =>
        links ? new Map(links.fields.filter((f) => f.kind === kind).map((f) => [f.name, f])) : null;

    const linkedIris = (entityId: string): string[] => {
        if (!links) return [];
        if (entityId === links.view_entity_id) return links.view_links.map((l) => l.iri);
        const field = [...links.fields, ...links.removed_fields]
            .find((f) => f.entity_id === entityId);
        return field ? field.links.map((l) => l.iri) : [];
    };

    /** The non-blocking warnings linking a measure to `iri` raises (none if the check fails). */
    const checkLink = async (link: LinkTarget, iri: string): Promise<LinkWarning[]> => {
        if (link.entityType !== 'uc_column') return [];
        try {
            const res = await get<LinkCheck>(
                '/api/metric-views/consistency/link-check'
                + `?entity_id=${encodeURIComponent(link.entityId)}&iri=${encodeURIComponent(iri)}`,
            );
            return !res?.error && Array.isArray(res?.data?.warnings) ? res.data.warnings : [];
        } catch {
            return [];
        }
    };

    const addLink = async (iri: string) => {
        if (!target) return;
        const warnings = await checkLink(target, iri);
        const res = await post<EntitySemanticLink>('/api/semantic-links/', {
            entity_type: target.entityType,
            entity_id: target.entityId,
            iri,
        });
        if (res.error || !res.data?.id) {
            toast({ title: t('editor.metricView.linkError'), variant: 'destructive' });
            return;
        }
        setLinks((current) => (current ? withLink(current, target.entityId, res.data) : current));
        setLinkWarnings(warnings.length > 0 ? { name: target.name, warnings } : null);
        toast({ title: t('editor.metricView.linked', { name: target.name }) });
        setTarget(null);
    };

    const removeLink = async (linkId: string) => {
        const res = await apiDelete(`/api/semantic-links/${linkId}`);
        if (res.error) {
            toast({ title: t('editor.metricView.unlinkError'), variant: 'destructive' });
            return;
        }
        setLinks((current) => (current ? withoutLink(current, linkId) : current));
        toast({ title: t('editor.metricView.unlinked') });
    };

    const fieldLinkProps = { canEdit, onAdd: setTarget, onRemove: removeLink };
    const removedWithLinks = links ? links.removed_fields.filter((f) => f.links.length > 0) : [];

    return (
        <div className="space-y-4">
            {linkWarnings && (
                <MetricViewLinkWarnings
                    name={linkWarnings.name}
                    warnings={linkWarnings.warnings}
                    onDismiss={() => setLinkWarnings(null)}
                />
            )}
            {links && (
                <div className="space-y-1">
                    <h4 className="text-sm font-semibold">{t('editor.metricView.viewConcepts')}</h4>
                    <ConceptCell
                        links={links.view_links}
                        target={{
                            entityType: 'uc_table',
                            entityId: links.view_entity_id,
                            name: links.view_entity_id,
                        }}
                        {...fieldLinkProps}
                    />
                </div>
            )}
            {spec ? (
                <>
                    <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-sm">
                        <dt className="text-muted-foreground">{t('editor.metricView.source')}</dt>
                        <dd className="font-mono text-xs break-all">{spec.source ?? '—'}</dd>
                        {spec.filter && (
                            <>
                                <dt className="text-muted-foreground">{t('editor.metricView.filter')}</dt>
                                <dd className="font-mono text-xs break-all">{spec.filter}</dd>
                            </>
                        )}
                        {spec.joins.length > 0 && (
                            <>
                                <dt className="text-muted-foreground">{t('editor.metricView.joins')}</dt>
                                <dd className="font-mono text-xs break-all space-y-0.5">
                                    {spec.joins.map((join, i) => (
                                        <div key={`${join.name ?? join.source}-${i}`}>
                                            {join.name || join.source}
                                            {join.on && <span className="text-muted-foreground"> ON {join.on}</span>}
                                            {join.using && join.using.length > 0 && (
                                                <span className="text-muted-foreground"> USING ({join.using.join(', ')})</span>
                                            )}
                                        </div>
                                    ))}
                                </dd>
                            </>
                        )}
                        {spec.materialization && (
                            <>
                                <dt className="text-muted-foreground">{t('editor.metricView.materialization')}</dt>
                                <dd className="text-xs break-all">
                                    {t('editor.metricView.materializationSummary', {
                                        schedule: spec.materialization.schedule ?? '—',
                                        count: spec.materialization.materialized_views.length,
                                    })}
                                    {spec.materialization.materialized_views.length > 0 && (
                                        <span className="font-mono text-muted-foreground">
                                            {' '}({spec.materialization.materialized_views
                                                .map((v) => (v.type ? `${v.name}: ${v.type}` : v.name))
                                                .join(', ')})
                                        </span>
                                    )}
                                </dd>
                            </>
                        )}
                    </dl>
                    <FieldTable
                        title={t('editor.metricView.dimensions')}
                        fields={spec.dimensions}
                        empty={t('editor.metricView.noDimensions')}
                        linksByName={linksOf('dimension')}
                        {...fieldLinkProps}
                    />
                    <FieldTable
                        title={t('editor.metricView.measures')}
                        fields={spec.measures}
                        empty={t('editor.metricView.noMeasures')}
                        linksByName={linksOf('measure')}
                        {...fieldLinkProps}
                    />
                </>
            ) : (
                <p className="text-sm text-muted-foreground">{t('editor.metricView.unparsed')}</p>
            )}
            {removedWithLinks.length > 0 && (
                <Alert>
                    <AlertTriangle className="h-4 w-4" />
                    <AlertTitle>{t('editor.metricView.removedFields')}</AlertTitle>
                    <AlertDescription className="space-y-2">
                        <p>{t('editor.metricView.removedFieldsHint')}</p>
                        {removedWithLinks.map((field) => (
                            <div
                                key={field.entity_id}
                                className="flex flex-wrap items-center gap-2"
                            >
                                <span className="font-medium text-xs">{field.name}</span>
                                <LinkedConceptChips
                                    links={field.links}
                                    onRemove={canEdit ? removeLink : undefined}
                                />
                            </div>
                        ))}
                    </AlertDescription>
                </Alert>
            )}
            <details open={!spec}>
                <summary className="text-sm cursor-pointer">{t('editor.metricView.yaml')}</summary>
                <pre className="mt-2 border rounded bg-muted/30 p-2 text-xs overflow-auto max-h-96">{definition.definition}</pre>
            </details>
            <ConceptSelectDialog
                isOpen={target !== null}
                onOpenChange={(open) => { if (!open) setTarget(null); }}
                onSelect={addLink}
                excludeIris={target ? linkedIris(target.entityId) : undefined}
                title={target
                    ? t('editor.metricView.linkConceptTo', { name: target.name })
                    : undefined}
            />
        </div>
    );
}
