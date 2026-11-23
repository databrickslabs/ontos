import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { ExternalLink } from 'lucide-react';
import type { PolicyCitation } from '@/types/authority-resolution';

/** The day part of an ISO timestamp, or an em dash. */
export const formatDay = (iso?: string | null) => (iso ? iso.slice(0, 10) : '—');

/** A link out is rendered only for http(s) URLs (the backend refuses other schemes too). */
export const safeHttpUrl = (url?: string | null): string | null => {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? url : null;
  } catch {
    return null;
  }
};

/** "from → to" with "open-ended" for no end, and an informational "Expired" badge. */
export function ValidityLine({ from, to, expired }: { from?: string | null; to?: string | null; expired?: boolean }) {
  const { t } = useTranslation(['authority-resolution']);
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span>
        {formatDay(from)} → {to ? formatDay(to) : t('policy.validity.openEnded')}
      </span>
      {expired && <ExpiredBadge />}
    </span>
  );
}

export function ExpiredBadge() {
  const { t } = useTranslation(['authority-resolution']);
  return (
    <Badge variant="outline" className="bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300">
      {t('policy.validity.expired')}
    </Badge>
  );
}

/**
 * The policy reference an AR cites: its name and version, validity, the link out and
 * the clause labels it cites (free text). Without a reference, the legacy free-form
 * justification chain is shown.
 */
export default function PolicyCitationView({ citation, legacy }: { citation?: PolicyCitation | null; legacy?: Record<string, any> | null }) {
  const { t } = useTranslation(['authority-resolution']);
  if (!citation) {
    if (legacy && Object.keys(legacy).length) {
      return (
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">{t('policy.citation.legacy')}</div>
          <pre className="text-xs bg-muted p-2 rounded overflow-auto">{JSON.stringify(legacy, null, 2)}</pre>
        </div>
      );
    }
    return <div className="text-xs text-muted-foreground">{t('policy.citation.none')}</div>;
  }
  const missing = citation.policy_key == null;
  const link = safeHttpUrl(citation.url);
  return (
    <div className="space-y-2">
      {missing ? (
        <span className="text-xs text-muted-foreground">{citation.authority_policy_id}</span>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Link to={`/authority-resolution/policies/${citation.authority_policy_id}`} className="font-medium text-primary hover:underline">
            {citation.policy_key} v{citation.version}
          </Link>
          <span className="text-muted-foreground">{citation.title}</span>
          {citation.parent_policy_id && (
            <Link to={`/authority-resolution/policies/${citation.parent_policy_id}`} className="text-xs text-muted-foreground hover:underline">
              {t('policy.citation.derivedFrom')}
            </Link>
          )}
        </div>
      )}
      {!missing && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{t('policy.fields.validity')}:</span>
          <ValidityLine from={citation.valid_from} to={citation.valid_to} expired={citation.expired} />
          {link && (
            <a href={link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 hover:underline">
              <ExternalLink className="h-3 w-3" /> {t('policy.citation.link')}
            </a>
          )}
        </div>
      )}
      {(citation.clause_refs || []).length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {citation.clause_refs.map((ref) => (
            <Badge key={ref} variant="secondary" className="font-mono text-xs">{ref}</Badge>
          ))}
        </div>
      ) : (
        !missing && <div className="text-xs text-muted-foreground">{t('policy.citation.noClauses')}</div>
      )}
    </div>
  );
}
