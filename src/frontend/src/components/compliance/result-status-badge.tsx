import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';

interface ResultStatusBadgeProps {
  passed: boolean;
  /** No verdict: an LLM_CHECK couldn't run. Neither passed nor failed. */
  notEvaluated?: boolean;
}

/** The status of one compliance result: passed, failed, or not evaluated. */
export function ResultStatusBadge({ passed, notEvaluated }: ResultStatusBadgeProps) {
  const { t } = useTranslation(['compliance']);
  if (notEvaluated && !passed) {
    return (
      <Badge variant="outline" data-testid="result-not-evaluated">
        {t('compliance:llmCheck.notEvaluated')}
      </Badge>
    );
  }
  return (
    <Badge variant={passed ? 'secondary' : 'destructive'}>
      {passed ? t('compliance:results.passed') : t('compliance:results.failed')}
    </Badge>
  );
}
