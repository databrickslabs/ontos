/**
 * The deprecation of a data product or data contract, on its details page:
 * shown while it is deprecated or retired, with the reason, the sunset date
 * and a link to the replacement.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { useApi } from '@/hooks/use-api';
import { SkeletonLine } from '@/components/common/list-view-skeleton';

interface DeprecationNoticeProps {
  entityType: 'data_product' | 'data_contract';
  status?: string | null;
  reason?: string | null;
  sunsetDate?: string | null;
  replacementId?: string | null;
}

const PATHS = {
  data_product: { api: '/api/data-products', page: '/data-products' },
  data_contract: { api: '/api/data-contracts', page: '/data-contracts' },
};

export default function DeprecationNotice({
  entityType,
  status,
  reason,
  sunsetDate,
  replacementId,
}: DeprecationNoticeProps) {
  const { t } = useTranslation(['common']);
  const { get } = useApi();
  const [replacement, setReplacement] = useState<{ id: string; name?: string } | null>(null);
  const lifecycle = (status || '').toLowerCase();
  const shown = lifecycle === 'deprecated' || lifecycle === 'retired';

  useEffect(() => {
    if (!shown || !replacementId) return;
    let cancelled = false;
    get<{ name?: string }>(`${PATHS[entityType].api}/${replacementId}`).then((res) => {
      if (!cancelled) setReplacement({ id: replacementId, name: res.data?.name });
    });
    return () => {
      cancelled = true;
    };
  }, [shown, replacementId, entityType, get]);

  // Until the replacement's name is fetched for this id, a line skeleton stands in for the link
  const replacementLoading = !!replacementId && replacement?.id !== replacementId;
  const replacementName = replacementLoading ? undefined : replacement?.name;

  if (!shown) return null;

  return (
    <Alert
      className={
        'border-amber-300 bg-amber-50 text-amber-900 '
        + 'dark:bg-amber-950/30 dark:text-amber-200'
      }
    >
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>
        {t(lifecycle === 'retired'
          ? 'common:deprecation.notice.retired'
          : 'common:deprecation.notice.deprecated')}
      </AlertTitle>
      <AlertDescription>
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="font-medium">{t('common:deprecation.reason')}</dt>
          <dd data-testid="deprecation-reason">
            {reason || t('common:deprecation.notice.noReason')}
          </dd>
          {sunsetDate && (
            <>
              <dt className="font-medium">{t('common:deprecation.sunsetDate')}</dt>
              <dd data-testid="deprecation-sunset-date">{sunsetDate}</dd>
            </>
          )}
          {replacementId && (
            <>
              <dt className="font-medium">{t('common:deprecation.replacement')}</dt>
              <dd>
                {replacementLoading ? (
                  <SkeletonLine height="h-4" width="w-32" />
                ) : (
                  <Link
                    to={`${PATHS[entityType].page}/${replacementId}`}
                    className="underline underline-offset-2"
                    data-testid="deprecation-replacement"
                  >
                    {replacementName || replacementId}
                  </Link>
                )}
              </dd>
            </>
          )}
        </dl>
      </AlertDescription>
    </Alert>
  );
}
