import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { History, Loader2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { useApi } from '@/hooks/use-api';
import { usePagination, PaginationControls } from '@/components/common/paginated-list';

// ---------------------------------------------------------------------------
// VersionHistoryPanel — drives the signed-off versioning contract §1 (version
// info + history) and §2 (per-version detail).
//
// Simple view: entries read as "Edited by {who} on {date}"; the top one is
// "Current", older ones "Previous version". NO version integers, NO IRIs.
// Clicking an older entry loads the frozen definition of that version and shows
// it as "Previous definition: …" — the whole point of the panel.
//
// Advanced view (`.adv-only`): also surfaces v{n}, is_current, and status.
// ---------------------------------------------------------------------------

interface VersionEntry {
  version: number;
  is_current: boolean;
  status?: string | null;
  created_at?: string | null;
  created_by?: string | null;
}

interface VersionInfo {
  iri: string;
  label: string;
  current_version?: number | null;
  status?: string | null;
  versions: VersionEntry[];
  replaces_iri?: string | null;
  replaced_by_iris: string[];
}

interface VersionDetail {
  // The /version/detail endpoint returns the frozen text as `definition`.
  // (Older reads used comment/comments; keep them as fallbacks.)
  definition?: string;
  comment?: string;
  comments?: Record<string, string>;
  [key: string]: unknown;
}

interface VersionHistoryPanelProps {
  conceptIri: string;
  /** Bumped by the parent after a publish, to force a refetch. */
  refreshNonce?: number;
}

function formatDate(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString();
}

export function VersionHistoryPanel({
  conceptIri,
  refreshNonce = 0,
}: VersionHistoryPanelProps) {
  const { t } = useTranslation(['semantic-models', 'common']);
  const { get } = useApi();

  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Which version's frozen definition is expanded, and the cache of loaded
  // definitions keyed by version so re-clicking is instant.
  const [expandedVersion, setExpandedVersion] = useState<number | null>(null);
  const [detailByVersion, setDetailByVersion] = useState<Record<number, string>>({});
  const [detailLoading, setDetailLoading] = useState<number | null>(null);

  const fetchInfo = useCallback(async () => {
    if (!conceptIri) return;
    setLoading(true);
    setError(null);
    try {
      const res = await get<VersionInfo>(
        `/api/semantic-models/concepts/version?iri=${encodeURIComponent(conceptIri)}`,
      );
      if (res.error || !res.data) {
        setError(res.error || 'Failed to load version history');
        setInfo(null);
        return;
      }
      setInfo(res.data);
    } catch (err: any) {
      setError(err?.message || 'Failed to load version history');
      setInfo(null);
    } finally {
      setLoading(false);
    }
  }, [conceptIri, get]);

  useEffect(() => {
    fetchInfo();
    // Reset transient expand state whenever the concept or nonce changes.
    setExpandedVersion(null);
    setDetailByVersion({});
  }, [fetchInfo, refreshNonce]);

  const loadDefinition = useCallback(
    async (version: number) => {
      if (version in detailByVersion) return;
      setDetailLoading(version);
      try {
        const res = await get<VersionDetail>(
          `/api/semantic-models/concepts/version/detail?iri=${encodeURIComponent(
            conceptIri,
          )}&version=${version}`,
        );
        const detail = res.data;
        const text =
          detail?.definition ||
          detail?.comment ||
          (detail?.comments && Object.values(detail.comments)[0]) ||
          '';
        setDetailByVersion((prev) => ({ ...prev, [version]: String(text) }));
      } catch {
        setDetailByVersion((prev) => ({ ...prev, [version]: '' }));
      } finally {
        setDetailLoading(null);
      }
    },
    [conceptIri, detailByVersion, get],
  );

  const handleToggle = useCallback(
    (entry: VersionEntry) => {
      // The current version has no "previous definition" to reveal.
      if (entry.is_current) return;
      if (expandedVersion === entry.version) {
        setExpandedVersion(null);
        return;
      }
      setExpandedVersion(entry.version);
      void loadDefinition(entry.version);
    },
    [expandedVersion, loadDefinition],
  );

  const title = t('semantic-models:versionHistory.title', 'Version history');

  // Newest-first. is_current entry sorts to the top regardless of ordering.
  // Computed unconditionally (empty when not loaded) so the pagination hook
  // below is always called in the same order — Rules of Hooks.
  const versions = info ? [...info.versions].sort((a, b) => b.version - a.version) : [];
  const onlyOne = versions.length <= 1;

  // Cap long histories at 10 per page rather than rendering an unbounded list.
  const {
    pageItems: pagedVersions,
    page: versionPage,
    setPage: setVersionPage,
    pageCount: versionPageCount,
  } = usePagination(versions, 10);

  if (loading) {
    return (
      <div className="rounded-lg border bg-card p-3">
        <div className="flex items-center gap-2 mb-2">
          <History className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-medium">{title}</h3>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" />
          {t('common:loading', 'Loading…')}
        </div>
      </div>
    );
  }

  if (error || !info) {
    return (
      <div className="rounded-lg border bg-card p-3">
        <div className="flex items-center gap-2 mb-2">
          <History className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-medium">{title}</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          {t(
            'semantic-models:versionHistory.unavailable',
            'Version history is unavailable.',
          )}
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-center gap-2 mb-2">
        <History className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-medium">{title}</h3>
      </div>

      {onlyOne ? (
        <p className="text-xs text-muted-foreground">
          {t('semantic-models:versionHistory.none', 'No previous versions yet.')}
        </p>
      ) : (
        <ul className="space-y-1 text-xs">
          {pagedVersions.map((entry) => {
            const who =
              entry.created_by ||
              t('semantic-models:versionHistory.unknownEditor', 'someone');
            const when = formatDate(entry.created_at);
            const isExpanded = expandedVersion === entry.version;
            const frozen = detailByVersion[entry.version];

            return (
              <li key={entry.version}>
                <button
                  type="button"
                  disabled={entry.is_current}
                  onClick={() => handleToggle(entry)}
                  className={cn(
                    'flex w-full items-start gap-2 rounded-md px-1.5 py-1 text-left',
                    entry.is_current
                      ? 'cursor-default'
                      : 'hover:bg-accent hover:text-accent-foreground',
                  )}
                >
                  <span
                    className={cn(
                      'mt-1 h-1.5 w-1.5 shrink-0 rounded-full',
                      entry.is_current ? 'bg-emerald-600' : 'bg-muted-foreground/50',
                    )}
                  />
                  <span className="flex-1 min-w-0">
                    <span className="block">
                      {t(
                        'semantic-models:versionHistory.editedBy',
                        'Edited by {{who}} on {{when}}',
                        { who, when },
                      )}
                    </span>
                    {/* Advanced-only mechanics: version integer + status. */}
                    <span className="adv-only mt-0.5 block font-mono text-[10px] text-muted-foreground">
                      v{entry.version}
                      {entry.is_current
                        ? ' · current'
                        : ''}
                      {entry.status ? ` · ${entry.status}` : ''}
                    </span>
                    {/* Frozen previous definition, on expand. */}
                    {isExpanded && (
                      <span className="mt-1 block rounded-md border bg-muted/30 p-2 text-xs">
                        {detailLoading === entry.version ? (
                          <span className="flex items-center gap-2 text-muted-foreground">
                            <Loader2 className="h-3 w-3 animate-spin" />
                            {t('common:loading', 'Loading…')}
                          </span>
                        ) : frozen ? (
                          <>
                            <span className="font-medium">
                              {t(
                                'semantic-models:versionHistory.previousDefinition',
                                'Previous definition:',
                              )}
                            </span>{' '}
                            <span className="whitespace-pre-line">{frozen}</span>
                          </>
                        ) : (
                          <span className="text-muted-foreground">
                            {t(
                              'semantic-models:versionHistory.noDefinition',
                              'No definition recorded for this version.',
                            )}
                          </span>
                        )}
                      </span>
                    )}
                  </span>
                  <Badge
                    variant={entry.is_current ? 'secondary' : 'outline'}
                    className="shrink-0 text-[10px]"
                  >
                    {entry.is_current
                      ? t('semantic-models:versionHistory.current', 'Current')
                      : t(
                          'semantic-models:versionHistory.previous',
                          'Previous version',
                        )}
                  </Badge>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {!onlyOne && (
        <PaginationControls
          page={versionPage}
          pageCount={versionPageCount}
          onPageChange={setVersionPage}
        />
      )}
    </div>
  );
}

export default VersionHistoryPanel;
