import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Truck } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import type { BatchImportResult } from '@/types/import-results';

/** How many created entities of an import aren't delivered yet (failed or queued). */
export function undeliveredCount(result: BatchImportResult | null | undefined): number {
  if (!result) return 0;
  return result.items.filter(
    (i) => i.status === 'created'
      && (i.delivery?.status === 'failed' || i.delivery?.status === 'pending'),
  ).length;
}

/**
 * The import dialog's "not delivered" line (#1688): the delivery outbox retries
 * them, and Settings > Delivery Modes lists them with "Deliver again".
 */
export default function ImportDeliveryAlert({ result }: { result: BatchImportResult | null }) {
  const { t } = useTranslation(['common']);
  const { hasPermission } = usePermissions();
  const count = undeliveredCount(result);
  if (!count) return null;
  const canOpen = hasPermission('settings-delivery', FeatureAccessLevel.READ_ONLY);
  return (
    <Alert data-testid="import-delivery-alert">
      <Truck className="h-4 w-4" />
      <AlertDescription>
        {t('common:importDeliveryOutbox.notDelivered', { count })}
        {canOpen && (
          <>
            {' '}
            <Link to="/settings/delivery" className="font-medium underline">
              {t('common:importDeliveryOutbox.openSettings')}
            </Link>
          </>
        )}
      </AlertDescription>
    </Alert>
  );
}
