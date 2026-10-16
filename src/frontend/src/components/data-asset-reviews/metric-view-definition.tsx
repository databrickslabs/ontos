import { useTranslation } from 'react-i18next';
import { MetricViewDefinition, MetricViewField } from '@/types/data-asset-review';

interface MetricViewDefinitionPanelProps {
    definition: MetricViewDefinition;
}

function FieldTable({ title, fields, empty }: { title: string; fields: MetricViewField[]; empty: string }) {
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
                        </tr>
                    </thead>
                    <tbody>
                        {fields.map((field) => (
                            <tr key={field.name} className="border-t align-top">
                                <td className="p-2">
                                    <div className="font-medium">{field.display_name || field.name}</div>
                                    {field.comment && <div className="text-muted-foreground">{field.comment}</div>}
                                </td>
                                <td className="p-2 font-mono break-all">{field.expr ?? ''}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </div>
    );
}

/** A Unity Catalog metric view's spec: its source, dimensions and measures, and the YAML. */
export default function MetricViewDefinitionPanel({ definition }: MetricViewDefinitionPanelProps) {
    const { t } = useTranslation('data-asset-reviews');
    const spec = definition.metric_view;

    return (
        <div className="space-y-4">
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
                    />
                    <FieldTable
                        title={t('editor.metricView.measures')}
                        fields={spec.measures}
                        empty={t('editor.metricView.noMeasures')}
                    />
                </>
            ) : (
                <p className="text-sm text-muted-foreground">{t('editor.metricView.unparsed')}</p>
            )}
            <details open={!spec}>
                <summary className="text-sm cursor-pointer">{t('editor.metricView.yaml')}</summary>
                <pre className="mt-2 border rounded bg-muted/30 p-2 text-xs overflow-auto max-h-96">{definition.definition}</pre>
            </details>
        </div>
    );
}
