import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { useApi } from '@/hooks/use-api';
import type {
  InlineSuggestRequest,
  InlineSuggestResponse,
  InlineSuggestion,
  TermMappingTargetEntityType,
} from '@/types/term-mapping';

// `type` is the real concept_type when the list is type-filtered
// (e.g. 'class', 'individual'); otherwise 'class' or 'property'.
// `source_context` (type-filtered list only) is the scheme's group key.
type ConceptItem = { value: string; label: string; type: string; source_context?: string | null };

interface MappingSource {
  /** Term-mapping entity_type (e.g. 'asset' or 'data_contract_property'). */
  entity_type: TermMappingTargetEntityType;
  /** Entity id in the same encoding the term-mapping adapters use.
   *  Can be a placeholder when the entity isn't saved yet; pair with
   *  `name` so the backend can still propose suggestions. */
  entity_id: string;
  /** Display name to use when the entity isn't persisted (draft form). */
  name?: string;
  /** Primitive type hint (e.g. "string", "integer"). */
  type_label?: string;
  /** Parent entity name (e.g. table name for a column). */
  parent_name?: string;
}

interface Props {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (iri: string) => void;
  parentConceptIris?: string[];
  entityType?: 'class' | 'property';
  /** When provided, the dialog adds a "Suggested by mapping" tier sourced
   *  from the term-mapping inline heuristic. No persistence; purely a hint. */
  mappingSource?: MappingSource;
  /** Optional: only offer concepts whose `concept_type` is listed (e.g.
   *  ['class'] for an rdfs:subClassOf picker). Omit for the default list. */
  conceptTypes?: string[];
  /** Optional: restrict the type-filtered list to one scheme (its group key,
   *  sent as `source_context`). Ignored without `conceptTypes`. */
  scopeSourceKey?: string;
  /** Display label of the scoped scheme (group header). */
  scopeLabel?: string;
  /** Group key -> scheme label for the group headers; falls back to the key. */
  schemeLabels?: Record<string, string>;
  /** Scoped mode only: offer an "Include other schemes" checkbox (off by
   *  default) that lists all schemes, grouped by scheme. */
  allowOtherSchemes?: boolean;
  /** IRIs never offered (dropped client-side after the fetch). */
  excludeIris?: string[];
  /** Overrides for the default title and search placeholder. */
  title?: string;
  searchPlaceholder?: string;
}

// Scoped or widened lists drop excluded entries client-side, so ask for more.
const SCOPED_LIMIT = '200';

export default function ConceptSelectDialog({
  isOpen,
  onOpenChange,
  onSelect,
  parentConceptIris,
  entityType = 'class',
  mappingSource,
  conceptTypes,
  scopeSourceKey,
  scopeLabel,
  schemeLabels,
  allowOtherSchemes = false,
  excludeIris,
  title,
  searchPlaceholder,
}: Props) {
  const { t } = useTranslation();
  const { get, post } = useApi();
  const [q, setQ] = useState('');
  const [suggested, setSuggested] = useState<ConceptItem[]>([]);
  const [other, setOther] = useState<ConceptItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [includeOtherSchemes, setIncludeOtherSchemes] = useState(false);
  const [mappingHints, setMappingHints] = useState<InlineSuggestion[]>([]);

  // Type-filtered mode: the flat concepts endpoint narrows by concept_type
  // server-side. No "suggested" tier in this mode.
  const typeFilter = conceptTypes && conceptTypes.length > 0 ? conceptTypes.join(',') : '';
  // Scoped mode: type-filtered and limited to one scheme. The opt-in checkbox
  // widens it to all schemes (grouped by scheme below).
  const scoped = !!scopeSourceKey && !!typeFilter && entityType !== 'property';
  const widened = scoped && allowOtherSchemes && includeOtherSchemes;

  useEffect(() => {
    const run = async () => {
      const params = new URLSearchParams({
        q: q,
        limit: scoped ? SCOPED_LIMIT : '50'
      });

      const baseEndpoint = entityType === 'property' ? '/api/semantic-models/properties' : '/api/semantic-models/concepts';

      if (typeFilter && entityType !== 'property') {
        params.set('concept_types', typeFilter);
        if (scoped && !widened) params.set('source_context', scopeSourceKey!);
        const res = await get<ConceptItem[]>(`${baseEndpoint}?${params}`);
        setSuggested([]);
        setOther(res.data || []);
      } else if (parentConceptIris && parentConceptIris.length > 0) {
        params.set('parent_iris', parentConceptIris.join(','));
        const res = await get<{suggested: ConceptItem[], other: ConceptItem[]}>(`${baseEndpoint}/suggestions?${params}`);
        setSuggested(res.data?.suggested || []);
        setOther(res.data?.other || []);
      } else {
        const res = await get<ConceptItem[]>(`${baseEndpoint}?${params}`);
        setSuggested([]);
        setOther(res.data || []);
      }
      setLoaded(true);
    };
    const timer = setTimeout(run, 250);
    return () => clearTimeout(timer);
  }, [q, parentConceptIris, entityType, typeFilter, scoped, widened, scopeSourceKey]);

  const excludeKey = (excludeIris || []).join('|');
  const excluded = useMemo(() => new Set(excludeKey ? excludeKey.split('|') : []), [excludeKey]);
  const visibleSuggested = excluded.size ? suggested.filter((r) => !excluded.has(r.value)) : suggested;
  const visibleOther = excluded.size ? other.filter((r) => !excluded.has(r.value)) : other;

  // Widened list: one group per scheme, the scoped scheme first, then the
  // others by label. Headers only when more than one scheme is present.
  const schemeLabel = (key: string) => schemeLabels?.[key] || key;
  const byScheme = new Map<string, ConceptItem[]>();
  if (widened) {
    visibleOther.forEach((r) => {
      const key = r.source_context || '';
      if (!byScheme.has(key)) byScheme.set(key, []);
      byScheme.get(key)!.push(r);
    });
  }
  const groups = widened
    ? Array.from(byScheme.entries())
        .sort(([a], [b]) => {
          if (a === scopeSourceKey) return -1;
          if (b === scopeSourceKey) return 1;
          return schemeLabel(a).localeCompare(schemeLabel(b));
        })
        .map(([key, items]) => ({ key, items }))
    : [{ key: '', items: visibleOther }];
  const showGroupHeaders = groups.length > 1;
  const groupHeader = (key: string) => {
    if (key === scopeSourceKey) {
      return t('semantic-models:conceptSelect.thisScheme', 'This scheme: {{label}}', {
        label: scopeLabel || schemeLabel(key),
      });
    }
    return key ? schemeLabel(key) : t('semantic-models:conceptSelect.noScheme', 'No scheme');
  };
  const classesOnly = typeFilter === 'class';

  // Inline mapping suggestions. We deliberately re-fetch only when the
  // dialog is (re)opened or the source entity changes — these are
  // expensive (full heuristic run) and shouldn't fire on every keystroke.
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (!isOpen || !mappingSource) {
        setMappingHints([]);
        return;
      }
      try {
        const body: InlineSuggestRequest = {
          source_entity_type: mappingSource.entity_type,
          source_entity_id: mappingSource.entity_id,
          limit: 5,
          ...(mappingSource.name ? { name: mappingSource.name } : {}),
          ...(mappingSource.type_label ? { type_label: mappingSource.type_label } : {}),
          ...(mappingSource.parent_name ? { parent_name: mappingSource.parent_name } : {}),
        };
        const res = await post<InlineSuggestResponse>('/api/term-mappings/suggestions-for', body);
        if (cancelled) return;
        setMappingHints(res.data?.suggestions ?? []);
      } catch {
        // Mapping hints are pure value-add; never block the picker.
        if (!cancelled) setMappingHints([]);
      }
    };
    void run();
    return () => { cancelled = true; };
    // Re-fetch when the user edits the in-progress name in a draft form
    // so suggestions track what's actually typed.
  }, [
    isOpen,
    mappingSource?.entity_type,
    mappingSource?.entity_id,
    mappingSource?.name,
    mappingSource?.type_label,
    mappingSource?.parent_name,
  ]);

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl w-[90vw]">
        <DialogHeader>
          <DialogTitle>{title ?? `Select Business ${entityType === 'property' ? 'Property' : 'Concept'}`}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <Input placeholder={searchPlaceholder ?? `Search business ${entityType === 'property' ? 'properties' : 'concepts'}...`} value={q} onChange={(e) => setQ(e.target.value)} />
          {scoped && allowOtherSchemes && (
            <div className="flex items-center gap-2">
              <Checkbox
                id="concept-select-include-other-schemes"
                checked={includeOtherSchemes}
                onCheckedChange={(v) => setIncludeOtherSchemes(v === true)}
              />
              <Label htmlFor="concept-select-include-other-schemes" className="text-sm font-normal">
                {t('semantic-models:conceptSelect.includeOtherSchemes', 'Include other schemes')}
              </Label>
            </div>
          )}
          <div className="space-y-4 max-h-80 overflow-auto">
            {mappingHints.length > 0 && (
              <div className="space-y-2">
                <div className="text-sm font-medium text-muted-foreground border-b pb-1 flex items-center gap-1">
                  <Sparkles className="h-3.5 w-3.5" /> Suggested by term mapping
                </div>
                {mappingHints.map((h) => (
                  <div key={h.target_concept_iri} className="flex items-center justify-between gap-3 bg-purple-50 dark:bg-purple-950/40 p-2 rounded-lg">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <Badge variant="secondary" className="shrink-0">
                        {Math.round(h.confidence * 100)}%
                      </Badge>
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold truncate text-foreground" title={h.target_concept_label ?? h.target_concept_iri}>
                          {h.target_concept_label ?? h.target_concept_iri}
                        </div>
                        <div className="text-xs text-muted-foreground truncate" title={h.reason}>
                          {h.reason}
                        </div>
                        <div className="text-xs text-muted-foreground font-mono break-all" title={h.target_concept_iri}>
                          {h.target_concept_iri}
                        </div>
                      </div>
                    </div>
                    <Button size="sm" variant="default" className="shrink-0" onClick={() => onSelect(h.target_concept_iri)}>Select</Button>
                  </div>
                ))}
              </div>
            )}
            {visibleSuggested.length > 0 && (
              <div className="space-y-2">
                <div className="text-sm font-medium text-muted-foreground border-b pb-1">
                  Suggested (child {entityType === 'property' ? 'properties' : 'concepts'})
                </div>
                {visibleSuggested.map(r => (
                  <div key={r.value} className="flex items-center justify-between gap-3 bg-blue-50 dark:bg-blue-950 p-2 rounded-lg">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <Badge variant="secondary" className="shrink-0">{r.type}</Badge>
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold truncate text-foreground" title={r.label}>
                          {r.label}
                        </div>
                        <div className="text-xs text-muted-foreground font-mono break-all" title={r.value}>
                          {r.value}
                        </div>
                      </div>
                    </div>
                    <Button size="sm" variant="default" className="shrink-0" onClick={() => onSelect(r.value)}>Select</Button>
                  </div>
                ))}
              </div>
            )}
            {visibleOther.length > 0 && (
              <div className="space-y-2">
                {visibleSuggested.length > 0 && (
                  <div className="text-sm font-medium text-muted-foreground border-b pb-1">
                    Other {entityType === 'property' ? 'properties' : 'concepts'}
                  </div>
                )}
                {groups.map((group) => (
                  <div key={group.key || '_'} className="space-y-2">
                    {showGroupHeaders && (
                      <div className="text-sm font-medium text-muted-foreground border-b pb-1">
                        {groupHeader(group.key)}
                      </div>
                    )}
                    {group.items.map(r => (
                      <div key={r.value} className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <Badge variant="secondary" className="shrink-0">{r.type}</Badge>
                          <div className="min-w-0 flex-1">
                            <div className="text-sm font-semibold truncate" title={r.label}>
                              {r.label}
                            </div>
                            <div className="text-xs text-muted-foreground font-mono break-all" title={r.value}>
                              {r.value}
                            </div>
                          </div>
                        </div>
                        <Button size="sm" variant="outline" className="shrink-0" onClick={() => onSelect(r.value)}>Select</Button>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
            {scoped && !widened && loaded && visibleOther.length === 0 && (
              <div className="text-sm text-muted-foreground py-2 space-y-1">
                <p>
                  {q.trim()
                    ? t('semantic-models:conceptSelect.noMatchesInScheme', 'No matches in this scheme.')
                    : classesOnly
                      ? t('semantic-models:conceptSelect.noClassesInScheme', 'No classes in this scheme yet.')
                      : t('semantic-models:conceptSelect.noConceptsInScheme', 'No concepts in this scheme yet.')}
                </p>
                {allowOtherSchemes && (
                  <p>
                    {t(
                      'semantic-models:conceptSelect.includeOtherSchemesHint',
                      'Tick "Include other schemes" to pick from another scheme.',
                    )}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}