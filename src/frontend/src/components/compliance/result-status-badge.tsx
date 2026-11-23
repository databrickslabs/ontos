import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { complianceResultStatus } from '@/lib/compliance-run-warning';

interface ResultStatusBadgeProps {
  passed: boolean;
  /** Not evaluated: an LLM_CHECK without a verdict, or a field that could not be read. */
  notEvaluated?: boolean;
  /** The result's details, for results stored before ``notEvaluated`` (their code). */
  detailsJson?: string | null;
}

/** The status of one compliance result: passed, failed, or not evaluated. */
export function ResultStatusBadge({ passed, notEvaluated, detailsJson }: ResultStatusBadgeProps) {
  const { t } = useTranslation(['compliance']);
  if (notEvaluated && !passed) {
    return (
      <Badge variant="outline" data-testid="result-not-evaluated">
        {t('compliance:llmCheck.notEvaluated')}
      </Badge>
    );
  }
  const status = complianceResultStatus(t, { passed, details_json: detailsJson });
  return <Badge variant={status.variant}>{status.label}</Badge>;
}
