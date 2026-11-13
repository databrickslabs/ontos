import { useCallback, useEffect, useState } from 'react';
import { ClipboardCheck } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useApi } from '@/hooks/use-api';
import ComplianceModal from '@/components/compliance/compliance-modal';

/** Mirrors ComplianceCompletenessRead (backend models/compliance_templates.py). */
export interface ComplianceCompleteness {
  applicable: boolean;
  passed: boolean;
  missing: string[];
  messages: string[];
}

interface EntityComplianceButtonProps {
  /** Polymorphic entity type the template is bound to (e.g. "asset"). */
  entityType: string;
  entityId: string;
  /** When false the modal opens read-only. */
  canWrite: boolean;
}

/**
 * Compliance button + modal for an entity detail page.
 *
 * Renders nothing when no template is active for the entity type (or the
 * user can't read the values). Shows the number of mandatory fields still
 * missing as an advisory badge; it never blocks anything.
 */
export default function EntityComplianceButton({
  entityType,
  entityId,
  canWrite,
}: EntityComplianceButtonProps) {
  const { t } = useTranslation('compliance');
  const { get } = useApi();
  const [applicable, setApplicable] = useState(false);
  const [missingCount, setMissingCount] = useState(0);
  const [open, setOpen] = useState(false);

  const loadCompleteness = useCallback(async () => {
    const entityPath = `${entityType}/${encodeURIComponent(entityId)}`;
    const { data, error } = await get<ComplianceCompleteness>(
      `/api/compliance-templates/entities/${entityPath}/completeness`,
    );
    if (error || !data) {
      setApplicable(false);
      setMissingCount(0);
      return;
    }
    setApplicable(!!data.applicable);
    setMissingCount(data.applicable && !data.passed ? (data.missing?.length ?? 0) : 0);
  }, [get, entityType, entityId]);

  useEffect(() => {
    loadCompleteness();
  }, [loadCompleteness]);

  if (!applicable) return null;

  const status =
    missingCount > 0
      ? t('complianceTemplates.missingFields', { count: missingCount })
      : t('complianceTemplates.complete');

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} title={status}>
        <ClipboardCheck className="mr-2 h-4 w-4" />
        {t('complianceTemplates.button')}
        {missingCount > 0 && (
          <Badge
            variant="destructive"
            className="ml-2 px-1.5 py-0 text-[10px]"
            aria-label={status}
          >
            {missingCount}
          </Badge>
        )}
      </Button>
      <ComplianceModal
        open={open}
        onOpenChange={setOpen}
        entityType={entityType}
        entityId={entityId}
        canWrite={canWrite}
        onSaved={loadCompleteness}
      />
    </>
  );
}
