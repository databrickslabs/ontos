import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertCircle, ArrowRightCircle } from 'lucide-react';
import { ListItemSkeleton } from '@/components/common/list-view-skeleton';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

interface Entry {
  id: string;
  entity_type: string;
  entity_id: string;
  action: string;
  username?: string | null;
  timestamp?: string | null;
  details_json?: string | null;
}

interface RecentActivityProps {
  limit?: number;
}

export default function RecentActivity({ limit = 10 }: RecentActivityProps) {
  const { t } = useTranslation('home');
  const { isLoading: permissionsLoading, hasPermission } = usePermissions();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const makeEntityPath = useMemo(() => {
    return (entityType?: string | null, entityId?: string | null): string | null => {
      if (!entityType || !entityId) return null;
      const base = String(entityType).split(':')[0].toLowerCase();
      switch (base) {
        case 'data_product':
          return `/data-products/${entityId}`;
        case 'data_domain':
          return `/settings/data-domains/${entityId}`;
        case 'data_contract':
          return `/data-contracts/${entityId}`;
        default:
          return null;
      }
    };
  }, []);

  useEffect(() => {
    const load = async () => {
      if (permissionsLoading || !hasPermission('audit', FeatureAccessLevel.READ_ONLY)) {
        setEntries([]);
        return;
      }
      try {
        setLoading(true);
        const resp = await fetch(`/api/change-log?limit=${limit}`);
        if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
        const data = await resp.json();
        setEntries(Array.isArray(data) ? data : []);
        setError(null);
      } catch (e: any) {
        setEntries([]);
        setError(e.message || t('recentActivity.error'));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [permissionsLoading, hasPermission, limit, t]);

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-4">{t('recentActivity.title')}</h2>
      <Card>
        <CardContent className="p-6">
          {loading ? (
            <ListItemSkeleton count={4} height="h-10" className="space-y-2" />
          ) : error ? (
            <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>{error}</AlertDescription></Alert>
          ) : entries.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('recentActivity.noActivity')}</p>
          ) : (
            <ul className="space-y-2">
              {entries.map(e => {
                let iri: string | undefined;
                let linkId: string | undefined;
                if (e.details_json && e.action && e.action.startsWith('SEMANTIC_LINK_')) {
                  try {
                    const details = JSON.parse(e.details_json);
                    iri = typeof details?.iri === 'string' ? details.iri : undefined;
                    linkId = typeof details?.link_id === 'string' ? details.link_id : undefined;
                  } catch (_) {
                    // ignore malformed details
                  }
                }

                const path = makeEntityPath(e.entity_type, e.entity_id);
                const summary = (
                  <span>
                    <span className="font-medium">{e.entity_type}</span> {e.entity_id} — {e.action}
                    {e.username ? <> {t('recentActivity.by')} <span className="italic">{e.username}</span></> : null}
                    {e.timestamp ? <> {t('recentActivity.at')} {new Date(e.timestamp).toLocaleString()}</> : null}
                  </span>
                );

                return (
                  <li key={e.id} className="text-sm text-muted-foreground">
                    <div className="flex items-center gap-2">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex-1 truncate cursor-default" title={`${e.entity_type} ${e.entity_id}`}>
                            {summary}
                          </div>
                        </TooltipTrigger>
                        <TooltipContent side="left" className="max-w-md text-primary-foreground">
                          <div className="space-y-1">
                            <div><span className="font-semibold">{t('recentActivity.entityLabel')}</span> {e.entity_type} / {e.entity_id}</div>
                            <div><span className="font-semibold">{t('recentActivity.actionLabel')}</span> {e.action}</div>
                            {e.username && <div><span className="font-semibold">{t('recentActivity.userLabel')}</span> {e.username}</div>}
                            {e.timestamp && <div><span className="font-semibold">{t('recentActivity.timeLabel')}</span> {new Date(e.timestamp).toLocaleString()}</div>}
                            {(iri || linkId) && (
                              <div className="pt-1 space-y-0.5">
                                {iri && <div><span className="font-semibold">{t('recentActivity.iriLabel')}</span> {iri}</div>}
                                {linkId && <div><span className="font-semibold">{t('recentActivity.linkIdLabel')}</span> {linkId}</div>}
                              </div>
                            )}
                            {path && (
                              <div className="pt-1">
                                <button
                                  className="underline underline-offset-2"
                                  onClick={(ev) => { ev.preventDefault(); navigate(path); }}
                                >
                                  {t('recentActivity.openButton')}
                                </button>
                              </div>
                            )}
                          </div>
                        </TooltipContent>
                      </Tooltip>

                      <button
                        className={`shrink-0 p-1 rounded hover:bg-accent ${path ? 'text-primary hover:text-primary' : 'opacity-40 cursor-not-allowed'}`}
                        aria-label={t('recentActivity.openDetails')}
                        title={path ? t('recentActivity.openDetails') : t('recentActivity.noDetails')}
                        onClick={() => { if (path) navigate(path); }}
                      >
                        <ArrowRightCircle className="h-4 w-4" />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}


