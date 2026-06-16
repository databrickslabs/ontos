import { useEffect, useMemo, useState } from 'react';
import { Check, Copy, Search, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type {
  TemplateVarDescriptor,
  TemplateVarGroup,
  TemplateVarsResponse,
} from '@/types/template-vars';

interface TemplateVarsInspectorProps {
  // Trigger type slug (e.g. ``on_request_access``). When unset the
  // inspector renders a hint asking the author to pick a trigger first.
  triggerType?: string;
  // Entity type slug (e.g. ``data_product``). When the trigger declares
  // multiple entity types this should be the one the author wants
  // templates to resolve against; ``workflow-designer.tsx`` defaults to
  // the first entry in ``trigger.entity_types``.
  entityType?: string;
}

// Compact preview for a sample value. Lists/objects render as compact
// JSON so the chip stays single-line; long previews are truncated with
// the full payload available on hover via the native ``title`` attr.
function formatSample(sample: unknown): string {
  if (sample === null || sample === undefined) {
    return '';
  }
  if (typeof sample === 'string') {
    return sample;
  }
  try {
    return JSON.stringify(sample);
  } catch {
    return String(sample);
  }
}

function truncate(value: string, max = 60): string {
  if (value.length <= max) {
    return value;
  }
  return `${value.slice(0, max - 1)}…`;
}

function VariableRow({
  descriptor,
  groupLabel,
}: {
  descriptor: TemplateVarDescriptor;
  // Shown only when this row is rendered in the flat search-result list,
  // so authors can see which namespace a hit came from.
  groupLabel?: string;
}) {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);

  const placeholder = `\${${descriptor.path}}`;
  const sample = formatSample(descriptor.sample);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(placeholder);
      setCopied(true);
      toast({
        title: 'Copied',
        description: `${placeholder} copied to clipboard.`,
      });
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast({
        title: 'Copy failed',
        description: 'Browser blocked clipboard access.',
        variant: 'destructive',
      });
    }
  };

  return (
    <div className="py-2 border-b last:border-b-0">
      {/* Row 1: placeholder + copy button on its own line. Giving the
          path a full row prevents the type badge from squeezing it down
          to a couple of characters per line on narrow panels. */}
      <div className="flex items-start gap-2">
        <code className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded break-all flex-1 min-w-0">
          {placeholder}
        </code>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleCopy}
          aria-label={`Copy ${placeholder}`}
          title={`Copy ${placeholder}`}
          className="shrink-0 h-6 w-6 p-0"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-emerald-600" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
        </Button>
      </div>
      {/* Row 2: type badge + (optional) group label, then description.
          Type lives on its own line so a long path never has to share
          horizontal space with the badge. */}
      <div className="flex items-center gap-2 mt-1">
        <Badge variant="outline" className="text-xs shrink-0">
          {descriptor.type}
        </Badge>
        {groupLabel && (
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground/70">
            {groupLabel}
          </span>
        )}
      </div>
      <p className="text-xs text-muted-foreground mt-1">
        {descriptor.description}
      </p>
      {sample && (
        <p
          className="text-xs text-muted-foreground/80 mt-0.5 font-mono truncate"
          title={sample}
        >
          e.g. {truncate(sample)}
        </p>
      )}
    </div>
  );
}

// Case-insensitive substring match across path, description, and the
// rendered sample preview. Splitting the query on whitespace lets
// authors type multiple tokens that must all hit (e.g. "catalog array"
// surfaces the catalogs array variable).
function matchesQuery(
  descriptor: TemplateVarDescriptor,
  tokens: string[],
): boolean {
  if (tokens.length === 0) return true;
  const haystack = [
    descriptor.path,
    descriptor.description,
    descriptor.type,
    formatSample(descriptor.sample),
  ]
    .join(' ')
    .toLowerCase();
  return tokens.every((tok) => haystack.includes(tok));
}

function filterGroups(
  groups: TemplateVarGroup[],
  query: string,
): { namespace: string; description: string; variables: TemplateVarDescriptor[] }[] {
  const tokens = query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  if (tokens.length === 0) return groups;
  return groups
    .map((g) => ({
      ...g,
      variables: g.variables.filter((v) => matchesQuery(v, tokens)),
    }))
    .filter((g) => g.variables.length > 0);
}

export default function TemplateVarsInspector({
  triggerType,
  entityType,
}: TemplateVarsInspectorProps) {
  const { get } = useApi();
  const [data, setData] = useState<TemplateVarsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  useEffect(() => {
    if (!triggerType || !entityType) {
      setData(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const url = `/api/workflows/template-vars?trigger=${encodeURIComponent(
      triggerType,
    )}&entity_type=${encodeURIComponent(entityType)}`;
    get<TemplateVarsResponse>(url)
      .then((response) => {
        if (cancelled) return;
        if (response.error) {
          setError(response.error);
          setData(null);
        } else {
          setData(response.data);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load variables');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [triggerType, entityType, get]);

  // Reset the search whenever the (trigger, entity_type) pair changes so
  // we don't strand a query that doesn't match the new descriptor set.
  useEffect(() => {
    setQuery('');
  }, [triggerType, entityType]);

  const filteredGroups = useMemo(
    () => (data ? filterGroups(data.groups, query) : []),
    [data, query],
  );
  const totalMatches = useMemo(
    () => filteredGroups.reduce((acc, g) => acc + g.variables.length, 0),
    [filteredGroups],
  );

  if (!triggerType || !entityType) {
    return (
      <div className="rounded-md border bg-muted/30 p-3">
        <p className="text-xs text-muted-foreground">
          Pick a trigger and entity type to see the variables available for{' '}
          <code className="font-mono">{'${...}'}</code> substitution.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="rounded-md border p-3">
        <p className="text-xs text-muted-foreground">Loading variables…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3">
        <p className="text-xs text-destructive">Failed to load variables: {error}</p>
      </div>
    );
  }

  if (!data || data.groups.length === 0) {
    return (
      <div className="rounded-md border p-3">
        <p className="text-xs text-muted-foreground">
          No variable descriptors are registered for this trigger and
          entity type yet. You can still use the universal placeholders
          ({' '}
          <code className="font-mono">{'${entity_name}'}</code>,{' '}
          <code className="font-mono">{'${user_email}'}</code>, etc.).
        </p>
      </div>
    );
  }

  const isSearching = query.trim().length > 0;
  // Groups are collapsed by default — the section can host 10+ variables
  // per group and that's overwhelming on first load. Authors expand
  // what they need, or use the search input to find a specific var.

  return (
    <div className="rounded-md border overflow-hidden flex flex-col">
      <div className="px-3 py-2 border-b bg-muted/30">
        <p className="text-xs font-medium">Available variables</p>
        <p className="text-xs text-muted-foreground">
          Click the copy icon to grab a placeholder.
        </p>
      </div>
      <div className="px-3 py-2 border-b">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by name or description…"
            className="h-8 text-xs pl-7 pr-7"
            aria-label="Search template variables"
          />
          {isSearching && (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        {isSearching && (
          <p className="text-[11px] text-muted-foreground mt-1">
            {totalMatches} match{totalMatches === 1 ? '' : 'es'}
          </p>
        )}
      </div>

      {isSearching ? (
        // Flat list view when searching — easier to scan than expanding
        // every accordion group. Empty state lives inline.
        <div className="px-3">
          {totalMatches === 0 ? (
            <p className="text-xs text-muted-foreground py-3">
              No variables match <code className="font-mono">{query}</code>.
            </p>
          ) : (
            filteredGroups.flatMap((group) =>
              group.variables.map((variable) => (
                <VariableRow
                  key={`${group.namespace}.${variable.path}`}
                  descriptor={variable}
                  groupLabel={group.namespace}
                />
              )),
            )
          )}
        </div>
      ) : (
        <Accordion type="multiple" defaultValue={[]}>
          {data.groups.map((group) => (
            <AccordionItem
              key={group.namespace}
              value={group.namespace}
              className="border-b last:border-b-0"
            >
              <AccordionTrigger className="px-3 py-2 text-xs font-medium hover:no-underline">
                <span>
                  {group.namespace}
                  <span className="ml-2 text-muted-foreground font-normal">
                    ({group.variables.length})
                  </span>
                </span>
              </AccordionTrigger>
              <AccordionContent className="px-3 pb-2 pt-0">
                <p className="text-xs text-muted-foreground mb-1">
                  {group.description}
                </p>
                <div>
                  {group.variables.map((variable) => (
                    <VariableRow key={variable.path} descriptor={variable} />
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      )}
    </div>
  );
}
