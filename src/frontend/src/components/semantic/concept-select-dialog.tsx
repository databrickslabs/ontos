import { useEffect, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useApi } from '@/hooks/use-api';
import type {
  InlineSuggestRequest,
  InlineSuggestResponse,
  InlineSuggestion,
  TermMappingTargetEntityType,
} from '@/types/term-mapping';

type ConceptItem = { value: string; label: string; type: 'class' | 'property' };

interface MappingSource {
  /** Term-mapping entity_type (e.g. 'asset' or 'data_contract_property'). */
  entity_type: TermMappingTargetEntityType;
  /** Entity id in the same encoding the term-mapping adapters use. */
  entity_id: string;
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
}

export default function ConceptSelectDialog({ isOpen, onOpenChange, onSelect, parentConceptIris, entityType = 'class', mappingSource }: Props) {
  const { get, post } = useApi();
  const [q, setQ] = useState('');
  const [suggested, setSuggested] = useState<ConceptItem[]>([]);
  const [other, setOther] = useState<ConceptItem[]>([]);
  const [mappingHints, setMappingHints] = useState<InlineSuggestion[]>([]);

  useEffect(() => {
    const run = async () => {
      const params = new URLSearchParams({
        q: q,
        limit: '50'
      });

      const baseEndpoint = entityType === 'property' ? '/api/semantic-models/properties' : '/api/semantic-models/concepts';

      if (parentConceptIris && parentConceptIris.length > 0) {
        params.set('parent_iris', parentConceptIris.join(','));
        const res = await get<{suggested: ConceptItem[], other: ConceptItem[]}>(`${baseEndpoint}/suggestions?${params}`);
        setSuggested(res.data?.suggested || []);
        setOther(res.data?.other || []);
      } else {
        const res = await get<ConceptItem[]>(`${baseEndpoint}?${params}`);
        setSuggested([]);
        setOther(res.data || []);
      }
    };
    const t = setTimeout(run, 250);
    return () => clearTimeout(t);
  }, [q, parentConceptIris, entityType]);

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
  }, [isOpen, mappingSource?.entity_type, mappingSource?.entity_id]);

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl w-[90vw]">
        <DialogHeader>
          <DialogTitle>Select Business {entityType === 'property' ? 'Property' : 'Concept'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <Input placeholder={`Search business ${entityType === 'property' ? 'properties' : 'concepts'}...`} value={q} onChange={(e) => setQ(e.target.value)} />
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
            {suggested.length > 0 && (
              <div className="space-y-2">
                <div className="text-sm font-medium text-muted-foreground border-b pb-1">
                  Suggested (child {entityType === 'property' ? 'properties' : 'concepts'})
                </div>
                {suggested.map(r => (
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
            {other.length > 0 && (
              <div className="space-y-2">
                {suggested.length > 0 && (
                  <div className="text-sm font-medium text-muted-foreground border-b pb-1">
                    Other {entityType === 'property' ? 'properties' : 'concepts'}
                  </div>
                )}
                {other.map(r => (
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
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}