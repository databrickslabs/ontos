// Corresponds to api/models/metric_view_consistency.py (#1263, phase 1)

export type MeasureVerdict =
    | 'duplicate'
    | 'link_conflict'
    | 'unrecognized_duplicate'
    | 'variant'
    | 'conflict'
    | 'near_duplicate';

export type FingerprintLevel = 'expression' | 'scope' | 'full';

export type ConceptVerdict = 'none' | 'consistent' | 'conflict';

export interface MeasureRef {
    asset_id: string | null;
    asset_name: string | null;
    view: string;
    name: string;
    display_name: string | null;
    entity_id: string;
    concepts: string[];
    /** Whether the user can read the view's definition in Unity Catalog */
    readable: boolean;
}

export interface WindowRange {
    kind: string;
    value: number | string | null;
    unit: string | null;
    inclusive: boolean;
}

export interface MeasureWindow {
    order: string | null;
    range: WindowRange;
    semiadditive: string | null;
    offset: string | null;
}

export interface MeasureJoin {
    source: string;
    on: string | null;
    using: string[] | null;
    cardinality: string | null;
}

export interface MeasureParameter {
    name: string;
    data_type: string | null;
    default: unknown;
}

export interface MeasureDefinition {
    expression: string;
    source: string;
    filter: string[];
    joins: MeasureJoin[];
    window: MeasureWindow[];
    parameters: MeasureParameter[];
}

export interface ComponentDiff {
    component: string;
    only_a: string[];
    only_b: string[];
}

export interface MeasureMatch {
    measure: MeasureRef;
    verdict: MeasureVerdict;
    first_level: FingerprintLevel | null;
    score: number | null;
    /** null when either definition can't be shown to the user */
    differences: ComponentDiff[] | null;
}

export interface MeasureConsistency {
    measure: MeasureRef;
    error: string | null;
    matches: MeasureMatch[];
}

export interface FingerprintGroup {
    full_digest: string;
    measures: MeasureRef[];
    definition: MeasureDefinition | null;
    other_concepts: string[];
    first_level: FingerprintLevel | null;
    score: number | null;
    differences: ComponentDiff[] | null;
}

export interface MetricViewConsistency {
    concept_iri: string | null;
    asset_id: string | null;
    verdict: ConceptVerdict | null;
    groups: FingerprintGroup[];
    unresolved: MeasureRef[];
    measures: MeasureConsistency[];
    threshold: number;
}

export interface LinkWarning {
    code: string;
    message: string;
    params: Record<string, unknown>;
}

export interface LinkCheck {
    entity_id: string;
    iri: string;
    warnings: LinkWarning[];
}
