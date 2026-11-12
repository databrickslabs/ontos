import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertCircle, FileText } from 'lucide-react';
import type { PolicyCitation, PolicyStatus } from '@/types/authority-resolution';

const STATUS_CLASS: Record<PolicyStatus, string> = {
  approved: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
  superseded: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
  withdrawn: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
  draft: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
};

export function PolicyStatusBadge({ status }: { status?: PolicyStatus | null }) {
  const { t } = useTranslation(['authority-resolution']);
  if (!status) return null;
  return <Badge variant="outline" className={STATUS_CLASS[status] || ''}>{t(`policy.status.${status}`)}</Badge>;
}

/** First 12 hex chars of a SHA-256, with the full digest on hover. */
export function ShortHash({ sha256 }: { sha256?: string | null }) {
  if (!sha256) return <span className="text-muted-foreground">—</span>;
  return <span className="font-mono text-xs" title={sha256}>{sha256.slice(0, 12)}…</span>;
}

/**
 * The Authority Policy an AR cites: version, status, the cited clauses and
 * the hashed source documents. Without a cited policy, the legacy free-form
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
  const cited = citation.clauses || [];
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
          <PolicyStatusBadge status={citation.status} />
          {citation.parent_policy_id && (
            <Link to={`/authority-resolution/policies/${citation.parent_policy_id}`} className="text-xs text-muted-foreground hover:underline">
              {t('policy.citation.derivedFrom')}
            </Link>
          )}
        </div>
      )}
      {citation.problem && (
        <Alert variant="destructive" className="py-2">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription className="text-xs">{t('policy.citation.problem', { problem: citation.problem })}</AlertDescription>
        </Alert>
      )}
      {cited.length > 0 ? (
        <div className="space-y-1">
          {cited.map((c) => (
            <div key={c.ref} className="rounded border p-2 text-xs space-y-0.5">
              <div className="flex items-center gap-2">
                <Badge variant="secondary" className="font-mono">{c.ref}</Badge>
                {c.title && <span className="font-medium">{c.title}</span>}
                {c.limits?.amount != null && (
                  <span className="ml-auto text-muted-foreground">
                    ≤ {c.limits.amount.toLocaleString()} {c.limits.currency || ''}
                  </span>
                )}
              </div>
              {c.text && <div className="text-muted-foreground">{c.text}</div>}
            </div>
          ))}
        </div>
      ) : (
        !missing && <div className="text-xs text-muted-foreground">{t('policy.citation.noClauses')}</div>
      )}
      {(citation.documents || []).length > 0 && (
        <div className="space-y-0.5">
          {(citation.documents || []).map((d) => (
            <div key={d.id} className="text-xs flex items-center gap-2">
              <FileText className="h-3 w-3" />
              <a href={`/api/documents/${d.id}/content`} className="hover:underline" target="_blank" rel="noopener noreferrer">{d.filename}</a>
              <ShortHash sha256={d.sha256} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
