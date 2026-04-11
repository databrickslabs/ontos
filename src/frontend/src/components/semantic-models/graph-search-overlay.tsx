/**
 * GraphSearchOverlay — floating search bar for graph views.
 * Filters concepts by label with type-ahead dropdown.
 * Selecting a match calls onSelect(concept).
 */
import React, { useState, useMemo, useRef, useCallback } from 'react';
import { Search } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import type { OntologyConcept } from '@/types/ontology';

const MAX_RESULTS = 8;

interface GraphSearchOverlayProps {
  concepts: OntologyConcept[];
  onSelect: (concept: OntologyConcept) => void;
  placeholder?: string;
}

export const GraphSearchOverlay: React.FC<GraphSearchOverlayProps> = ({
  concepts,
  onSelect,
  placeholder = 'Search concepts...',
}) => {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    if (!query.trim()) return [];
    const q = query.toLowerCase();
    return concepts
      .filter(c => {
        const labelMatch = (c.label ?? '').toLowerCase().includes(q);
        const altMatch = (c.synonyms ?? []).some(a => a.toLowerCase().includes(q));
        const commentMatch = (c.comment ?? '').toLowerCase().includes(q);
        return labelMatch || altMatch || commentMatch;
      })
      .slice(0, MAX_RESULTS);
  }, [query, concepts]);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setQuery(e.target.value);
    setOpen(true);
  }, []);

  const handleSelect = useCallback((concept: OntologyConcept) => {
    setQuery(concept.label ?? '');
    setOpen(false);
    onSelect(concept);
  }, [onSelect]);

  const handleBlur = useCallback(() => {
    // Delay to allow click events on dropdown items to fire first
    setTimeout(() => setOpen(false), 150);
  }, []);

  const handleFocus = useCallback(() => {
    if (query.trim()) setOpen(true);
  }, [query]);

  return (
    <div
      className="absolute top-4 left-4 z-20 w-[280px]"
      data-testid="graph-search-overlay"
    >
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleChange}
          onFocus={handleFocus}
          onBlur={handleBlur}
          placeholder={placeholder}
          data-testid="graph-search-input"
          className="w-full pl-9 pr-3 py-2 rounded-full border bg-popover text-sm text-foreground placeholder:text-muted-foreground outline-none shadow-md focus:ring-2 focus:ring-ring/20"
        />
      </div>

      {open && filtered.length > 0 && (
        <div
          className="absolute top-[calc(100%+4px)] left-0 right-0 bg-popover border rounded-xl shadow-lg overflow-hidden"
          data-testid="graph-search-dropdown"
        >
          {filtered.map(concept => (
            <button
              key={concept.iri}
              data-testid={`search-result-${concept.iri}`}
              onMouseDown={() => handleSelect(concept)}
              className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm hover:bg-muted/50 transition-colors border-b border-border/50 last:border-b-0"
            >
              <span className="flex-1 text-foreground">
                {concept.label}
              </span>
              {concept.iri && (
                <Badge variant="outline" className="text-[10px] font-mono">
                  {concept.iri.split(/[/#]/).pop()}
                </Badge>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default GraphSearchOverlay;
