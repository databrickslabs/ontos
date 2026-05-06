import { useEffect, useMemo, useRef, useState } from 'react';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { X, Loader2 } from 'lucide-react';
import { ConsumerPrincipal } from '@/types/data-product';

// Multi-select picker backed by /api/workspace/groups, surfacing workspace
// group display names and packaging each selection as a typed
// `{type: "group", value: <name>}` ConsumerPrincipal. Today the picker only
// collects groups; the typed shape leaves room to add other principal types
// (service principals, IdP roles, OAuth scopes) in the same widget later
// without a wire-format break.
//
// Accepts free-text additions for groups the SDK can't enumerate (e.g. cross-
// account groups synced from external IdPs) — falls back gracefully when the
// endpoint returns nothing.

interface WorkspaceGroup {
  id: string | null;
  display_name: string;
}

interface Props {
  value: ConsumerPrincipal[];
  onChange: (next: ConsumerPrincipal[]) => void;
}

export function ConsumerGroupsPicker({ value, onChange }: Props) {
  const [available, setAvailable] = useState<WorkspaceGroup[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<number | null>(null);

  const fetchGroups = (q: string) => {
    setLoading(true);
    setError(null);
    const url = q
      ? `/api/workspace/groups?search=${encodeURIComponent(q)}&limit=50`
      : `/api/workspace/groups?limit=50`;
    fetch(url)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: WorkspaceGroup[]) => setAvailable(data || []))
      .catch((e) => setError(e.message || 'Failed to load groups'))
      .finally(() => setLoading(false));
  };

  // Initial load
  useEffect(() => {
    fetchGroups('');
  }, []);

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => fetchGroups(search), 250);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [search]);

  // Selected-set keyed on the {type:"group"} pair so we don't double-add a
  // group that's already selected, while leaving room for other principal
  // types in the future.
  const selectedGroupNames = useMemo(
    () => new Set(value.filter((p) => p.type === 'group').map((p) => p.value)),
    [value],
  );
  const candidates = available.filter((g) => !selectedGroupNames.has(g.display_name));

  const addGroup = (name: string) => {
    const trimmed = name.trim();
    if (!trimmed || selectedGroupNames.has(trimmed)) return;
    onChange([...value, { type: 'group', value: trimmed }]);
  };

  const removeGroup = (name: string) => {
    // Match on value AND type — leaves non-group principals untouched.
    onChange(value.filter((p) => !(p.type === 'group' && p.value === name)));
  };

  return (
    <div className="space-y-2">
      {/* Selected chips */}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {value.map((p) => (
            <Badge key={`${p.type}:${p.value}`} variant="secondary" className="flex items-center gap-1">
              {p.value}
              <button
                type="button"
                aria-label={`Remove ${p.value}`}
                className="hover:text-destructive"
                onClick={() => removeGroup(p.value)}
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}

      {/* Search + free-text add */}
      <div className="flex items-center gap-2">
        <Input
          placeholder="Search workspace groups…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && search.trim()) {
              e.preventDefault();
              addGroup(search.trim());
              setSearch('');
            }
          }}
          className="flex-1"
        />
        {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        {search.trim() && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              addGroup(search.trim());
              setSearch('');
            }}
          >
            Add
          </Button>
        )}
      </div>

      {/* Suggestions list */}
      {candidates.length > 0 && (
        <div className="border rounded-md max-h-40 overflow-y-auto">
          {candidates.slice(0, 20).map((g) => (
            <button
              key={`${g.id ?? ''}-${g.display_name}`}
              type="button"
              className="w-full text-left px-3 py-1.5 text-sm hover:bg-muted"
              onClick={() => addGroup(g.display_name)}
            >
              {g.display_name}
            </button>
          ))}
        </div>
      )}

      {error && (
        <p className="text-xs text-muted-foreground">
          Could not load workspace groups ({error}). You can still add groups by typing the name and pressing Enter.
        </p>
      )}
    </div>
  );
}
