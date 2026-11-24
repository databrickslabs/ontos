import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import type {
    ComponentDiff,
    MeasureDefinition,
    MeasureRef,
    MeasureVerdict,
    MeasureWindow,
} from '@/types/metric-view-consistency';

/** Verdicts that mean two measures disagree, shown in red. */
const ALARMING: ReadonlySet<MeasureVerdict> = new Set(['conflict', 'link_conflict']);

/** `catalog.schema.view.measure`, with the measure's display name when it has one. */
export function measureLabel(measure: MeasureRef): string {
    const name = measure.display_name || measure.name;
    return `${measure.view}.${name}`;
}

/** The local name of an IRI (after the last `#` or `/`). */
export function iriLabel(iri: string): string {
    return iri.split(/[/#]/).pop() || iri;
}

export function VerdictBadge({ verdict }: { verdict: MeasureVerdict }) {
    const { t } = useTranslation('metric-views');
    return (
        <Badge
            variant={ALARMING.has(verdict) ? 'destructive' : 'secondary'}
            className="text-[11px]"
        >
            {t(`verdict.${verdict}`)}
        </Badge>
    );
}

export function formatWindow(window: MeasureWindow): string {
    const { kind, value, unit, inclusive } = window.range;
    const range = kind === 'raw'
        ? String(value ?? '')
        : [kind, value, unit, inclusive ? 'inclusive' : null].filter((x) => x !== null).join(' ');
    return [window.order, range, window.semiadditive].filter(Boolean).join(' · ');
}

/** The components of a definition, one row each (empty ones left out). */
export function DefinitionSummary({ definition }: { definition: MeasureDefinition }) {
    const { t } = useTranslation('metric-views');
    const rows: [string, string[]][] = [
        ['expression', [definition.expression]],
        ['source', [definition.source]],
        ['filter', definition.filter],
        ['window', definition.window.map(formatWindow)],
        ['joins', definition.joins.map((j) => [
            j.source, j.on ? `ON ${j.on}` : null, j.cardinality,
        ].filter(Boolean).join(' '))],
        ['parameters', definition.parameters.map((p) => `${p.name} = ${String(p.default)}`)],
    ];
    return (
        <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-0.5 text-xs">
            {rows.filter(([, values]) => values.length > 0).map(([key, values]) => (
                <div key={key} className="contents">
                    <dt className="text-muted-foreground">{t(`component.${key}`)}</dt>
                    <dd className="font-mono break-all space-y-0.5">
                        {values.map((value, i) => <div key={i}>{value}</div>)}
                    </dd>
                </div>
            ))}
        </dl>
    );
}

/** Per differing component: what only side a and only side b have. */
export function DiffList({ differences, aLabel, bLabel }: {
    differences: ComponentDiff[];
    aLabel: string;
    bLabel: string;
}) {
    const { t } = useTranslation('metric-views');
    if (differences.length === 0) return null;
    const side = (label: string, values: string[]) => values.length > 0 && (
        <div>
            <span className="text-muted-foreground">{label}: </span>
            <span className="font-mono break-all">{values.join(', ')}</span>
        </div>
    );
    return (
        <ul className="space-y-1 text-xs" aria-label={t('differences')}>
            {differences.map((diff) => (
                <li
                    key={diff.component}
                    className={
                        'rounded border border-amber-300 bg-amber-50 dark:bg-amber-950/30 p-1.5'
                    }
                >
                    <span className="font-medium">{t(`component.${diff.component}`)}</span>
                    {side(aLabel, diff.only_a)}
                    {side(bLabel, diff.only_b)}
                </li>
            ))}
        </ul>
    );
}
