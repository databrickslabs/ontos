/**
 * Read-only Turtle serialization viewer for a concept's RDF triples.
 * Advanced view only. Fetches triples via SPARQL query and displays as Turtle syntax.
 */
import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import { Copy, Loader2 } from 'lucide-react';

interface TurtleSerializationPanelProps {
  conceptIri: string;
}

export function TurtleSerializationPanel({ conceptIri }: TurtleSerializationPanelProps) {
  const { t } = useTranslation(['semantic-models', 'common']);
  const { post } = useApi();
  const { toast } = useToast();

  const [turtleText, setTurtleText] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchTriples = async () => {
      setLoading(true);
      setError(null);
      try {
        // Query the triples for this concept
        const sparql = `SELECT ?p ?o WHERE { <${conceptIri}> ?p ?o }`;
        const res = await post<Array<{ p: string; o: string | object }>>('/api/semantic-models/query', {
          sparql,
        });

        if (res.error) {
          throw new Error(res.error);
        }

        if (!res.data || !Array.isArray(res.data)) {
          throw new Error('Invalid response format');
        }

        // Format as Turtle: <subject> <predicate> <object> .
        const lines = res.data.map((row) => {
          const p = row.p || '';
          let o = row.o || '';

          // Handle object: if it's a URI, wrap in <>; if string, quote it
          let objStr: string;
          if (typeof o === 'string') {
            // Simple heuristic: if it looks like a URL/IRI, wrap in <>; else quote
            if (o.startsWith('http://') || o.startsWith('https://') || o.startsWith('urn:')) {
              objStr = `<${o}>`;
            } else {
              // Escape quotes in the string
              const escaped = o.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
              objStr = `"${escaped}"`;
            }
          } else {
            // JSON object — stringify it
            objStr = JSON.stringify(o);
          }

          return `<${conceptIri}> <${p}> ${objStr} .`;
        });

        if (lines.length === 0) {
          setTurtleText(`# No triples found for <${conceptIri}>`);
        } else {
          setTurtleText(lines.join('\n'));
        }
      } catch (err: any) {
        setError(err?.message || 'Failed to fetch triples');
        setTurtleText('');
      } finally {
        setLoading(false);
      }
    };

    if (conceptIri) {
      fetchTriples();
    }
  }, [conceptIri, post]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(turtleText);
      toast({
        title: t('common:toast.success'),
        description: t('common:messages.copiedToClipboard', { defaultValue: 'Copied to clipboard' }),
      });
    } catch (err: any) {
      toast({
        variant: 'destructive',
        title: t('common:toast.error'),
        description: err?.message || 'Failed to copy',
      });
    }
  };

  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-medium">
          {t('semantic-models:advanced.turtle', 'RDF (Turtle)')}
        </h3>
        {!loading && !error && turtleText && (
          <Button size="sm" variant="ghost" onClick={handleCopy} className="h-6 w-6 p-0">
            <Copy className="h-4 w-4" />
          </Button>
        )}
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
          <Loader2 className="h-3 w-3 animate-spin" />
          {t('common:actions.loading')}
        </div>
      )}

      {error && (
        <p className="text-xs text-destructive py-2">{error}</p>
      )}

      {!loading && !error && turtleText && (
        <pre className="text-xs bg-muted p-2 rounded border overflow-x-auto max-h-64 overflow-y-auto font-mono whitespace-pre-wrap break-words">
          {turtleText}
        </pre>
      )}
    </div>
  );
}
