import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useApi } from '@/hooks/use-api';
import { llmCheckText, type LlmCheck } from '@/lib/compliance-llm-checks';

/** Response of POST /api/compliance/llm-check/test. */
export interface LlmCheckTestResult {
  entity_type: string;
  entity_id?: string | null;
  entity_name?: string | null;
  passed: boolean;
  error_code?: string | null;
  llm_checks: LlmCheck[];
}

interface LlmCheckTesterProps {
  /** The rule as it is in the editor (not saved yet). */
  getRule: () => string;
}

/**
 * Tries the rule in the editor on one entity it matches, LLM_CHECK criteria
 * included, before the rule is saved. Nothing but cached verdicts is stored.
 */
export function LlmCheckTester({ getRule }: LlmCheckTesterProps) {
  const { t } = useTranslation(['compliance']);
  const { post } = useApi();
  const [entity, setEntity] = useState('');
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<LlmCheckTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runTest = async () => {
    const rule = getRule().trim();
    setResult(null);
    setError(null);
    if (!rule) {
      setError(t('compliance:llmCheck.test.noRule'));
      return;
    }
    setTesting(true);
    try {
      const response = await post<LlmCheckTestResult>('/api/compliance/llm-check/test', {
        rule,
        entity: entity.trim() || null,
      });
      if (response.error || !response.data?.entity_type) {
        const fallback = response.error || t('compliance:llmCheck.test.failed');
        setError(response.errorCode
          ? t([
              `compliance:llmCheck.errors.${response.errorCode}`,
              `compliance:saveErrors.${response.errorCode}`,
            ], {
              ...(response.errorParams ?? {}),
              defaultValue: fallback,
            }) as string
          : fallback);
        return;
      }
      setResult(response.data);
    } finally {
      setTesting(false);
    }
  };

  const entityLabel = result ? (result.entity_name || result.entity_id || '') : '';

  return (
    <div className="space-y-2 rounded-md border p-3" data-testid="llm-check-tester">
      <Label htmlFor="llm-check-sample">{t('compliance:llmCheck.test.title')}</Label>
      <p className="text-xs text-muted-foreground">{t('compliance:llmCheck.test.hint')}</p>
      <div className="flex gap-2">
        <Input
          id="llm-check-sample"
          value={entity}
          onChange={(e) => setEntity(e.target.value)}
          placeholder={t('compliance:llmCheck.test.entityPlaceholder')}
        />
        <Button type="button" variant="outline" onClick={runTest} disabled={testing}>
          {testing ? t('compliance:llmCheck.test.running') : t('compliance:llmCheck.test.run')}
        </Button>
      </div>
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
      {result && (
        <div className="space-y-2 text-sm" data-testid="llm-check-test-result">
          <div className="flex items-center gap-2">
            <span>
              {t('compliance:llmCheck.test.entity', { type: result.entity_type, name: entityLabel })}
            </span>
            <Badge variant={result.passed ? 'secondary' : 'destructive'}>
              {result.passed ? t('compliance:results.passed') : t('compliance:results.failed')}
            </Badge>
          </div>
          {result.error_code && !result.llm_checks.some((c) => c.code === result.error_code) && (
            <p className="text-destructive">
              {t(`compliance:llmCheck.codes.${result.error_code}`, { defaultValue: result.error_code })}
            </p>
          )}
          {result.llm_checks.length === 0 && !result.error_code && (
            <p className="text-muted-foreground">{t('compliance:llmCheck.test.noChecks')}</p>
          )}
          <ul className="space-y-1">
            {result.llm_checks.map((check, i) => (
              <li key={i} className="flex flex-wrap items-baseline gap-2">
                <Badge variant={check.passed ? 'secondary' : 'destructive'}>
                  {check.passed ? t('compliance:llmCheck.pass') : t('compliance:llmCheck.fail')}
                </Badge>
                <span className="font-medium">{check.criterion}</span>
                <span className="text-muted-foreground break-words">{llmCheckText(t, check)}</span>
                {check.cached && (
                  <span className="text-xs text-muted-foreground">{t('compliance:llmCheck.cached')}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
