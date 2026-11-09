import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useApi } from '@/hooks/use-api';
import TemplateVarsInspector from './template-vars-inspector';
import {
  scriptSchema,
  stepConfigIssueText,
  type ConditionCheckResult,
  type StepConfigIssue,
} from './step-config-checks';

// Forms for the Conditional and Script steps (#943, #942). The step contract
// (languages, defaults, minimum timeout) comes from the step's config_schema
// returned by GET /api/workflows/step-types; the texts are i18n keys.

const CONDITION_EXAMPLES = [
  "obj.status = 'active'",
  "obj.name CONTAINS 'email' OR obj.name CONTAINS 'phone'",
  "obj.status IN ['approved', 'active'] AND NOT HAS_TAG('pii')",
  'LENGTH(obj.description) > 20',
];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type JsonSchema = Record<string, any>;

const PYTHON_VARIABLES = ['entity', 'entity_type', 'entity_id', 'entity_name', 'user_email', 'step_results'];

function IssueText({ issue, testId }: { issue: StepConfigIssue; testId: string }) {
  const { t } = useTranslation(['workflows']);
  return (
    <p className="text-xs text-destructive mt-1" role="alert" data-testid={testId}>
      {stepConfigIssueText(issue, t)}
    </p>
  );
}

export function ConditionalStepConfig({
  config,
  onChange,
  showRequired = false,
}: {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  showRequired?: boolean;
}) {
  const { t } = useTranslation(['workflows']);
  const { post } = useApi();
  const condition = typeof config.condition === 'string' ? config.condition : '';
  const [touched, setTouched] = useState(false);
  const [checked, setChecked] = useState<{ condition: string; issue: StepConfigIssue | null } | null>(null);

  // Ask the backend whether the condition parses, once typing pauses.
  useEffect(() => {
    if (!condition.trim()) {
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      const response = await post<ConditionCheckResult>('/api/workflows/check-condition', { condition });
      if (cancelled || response.error || typeof response.data?.valid !== 'boolean') {
        return;
      }
      setChecked({ condition, issue: response.data.valid ? null : response.data });
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [condition, post]);

  let issue: StepConfigIssue | null = null;
  if (!condition.trim()) {
    issue = touched || showRequired ? { code: 'condition_required' } : null;
  } else if (checked?.condition === condition) {
    issue = checked.issue;
  }

  return (
    <div className="space-y-3" data-testid="conditional-step-config">
      <div>
        <Label htmlFor="conditional-condition">{t('workflows:designer.conditional.condition')}</Label>
        <Textarea
          id="conditional-condition"
          value={condition}
          onChange={(e) => {
            setTouched(true);
            onChange({ ...config, condition: e.target.value });
          }}
          placeholder={t('workflows:designer.conditional.placeholder')}
          rows={6}
          className="font-mono text-sm"
          aria-invalid={issue ? true : undefined}
        />
        {issue && <IssueText issue={issue} testId="conditional-condition-issue" />}
      </div>
      <p className="text-xs text-muted-foreground">{t('workflows:designer.conditional.branchHelp')}</p>
      <p className="text-xs text-muted-foreground">{t('workflows:designer.conditional.fieldsHelp')}</p>
      <div>
        <p className="text-xs font-medium">{t('workflows:designer.conditional.examplesTitle')}</p>
        <ul className="mt-1 space-y-1">
          {CONDITION_EXAMPLES.map((example) => (
            <li key={example}>
              <code className="text-xs font-mono bg-muted rounded px-1 py-0.5">{example}</code>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function ScriptStepConfig({
  config,
  schema,
  onChange,
  triggerType,
  entityType,
  showRequired = false,
}: {
  config: Record<string, unknown>;
  schema?: JsonSchema;
  onChange: (config: Record<string, unknown>) => void;
  triggerType?: string;
  entityType?: string;
  showRequired?: boolean;
}) {
  const { t } = useTranslation(['workflows']);
  const { languages, defaultLanguage, defaultTimeout, minimumTimeout } = scriptSchema(schema);
  const language = typeof config.language === 'string' ? config.language : defaultLanguage;
  const code = typeof config.code === 'string' ? config.code : '';
  const [touched, setTouched] = useState(false);

  const codeIssue: StepConfigIssue | null =
    !code.trim() && (touched || showRequired) ? { code: 'script_code_required' } : null;
  const timeout = config.timeout_seconds;
  const timeoutIssue: StepConfigIssue | null =
    timeout !== undefined && (!Number.isInteger(timeout) || (timeout as number) < minimumTimeout)
      ? { code: 'script_timeout_invalid', params: { minimum: minimumTimeout } }
      : null;

  return (
    <div className="space-y-3" data-testid="script-step-config">
      <div>
        <Label>{t('workflows:designer.script.language')}</Label>
        <Select value={language} onValueChange={(value) => onChange({ ...config, language: value })}>
          <SelectTrigger data-testid="script-language"><SelectValue /></SelectTrigger>
          <SelectContent>
            {languages.map((option) => (
              <SelectItem key={option} value={option}>
                {t(`workflows:designer.script.languages.${option}`, { defaultValue: option })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div>
        <Label htmlFor="script-code">{t('workflows:designer.script.code')}</Label>
        <Textarea
          id="script-code"
          value={code}
          onChange={(e) => {
            setTouched(true);
            onChange({ ...config, code: e.target.value });
          }}
          placeholder={t(
            language === 'sql'
              ? 'workflows:designer.script.sqlPlaceholder'
              : 'workflows:designer.script.pythonPlaceholder',
          )}
          rows={12}
          className="font-mono text-sm"
          aria-invalid={codeIssue ? true : undefined}
        />
        {codeIssue && <IssueText issue={codeIssue} testId="script-code-issue" />}
      </div>
      {language === 'sql' ? (
        <>
          <p className="text-xs text-muted-foreground">{t('workflows:designer.script.sqlHelp')}</p>
          <TemplateVarsInspector triggerType={triggerType} entityType={entityType} />
        </>
      ) : (
        <>
          <div>
            <Label htmlFor="script-timeout">{t('workflows:designer.script.timeout')}</Label>
            <Input
              id="script-timeout"
              type="number"
              min={minimumTimeout}
              step={1}
              value={timeout === undefined ? defaultTimeout : String(timeout)}
              onChange={(e) => {
                const raw = e.target.value;
                const next = { ...config };
                if (raw === '') {
                  delete next.timeout_seconds;
                } else {
                  next.timeout_seconds = Number(raw);
                }
                onChange(next);
              }}
              aria-invalid={timeoutIssue ? true : undefined}
            />
            {timeoutIssue ? (
              <IssueText issue={timeoutIssue} testId="script-timeout-issue" />
            ) : (
              <p className="text-xs text-muted-foreground mt-1">{t('workflows:designer.script.timeoutHelp')}</p>
            )}
          </div>
          <div data-testid="script-python-variables">
            <p className="text-xs font-medium">{t('workflows:designer.script.variablesTitle')}</p>
            <ul className="mt-1 space-y-1">
              {PYTHON_VARIABLES.map((name) => (
                <li key={name} className="text-xs text-muted-foreground">
                  <code className="font-mono bg-muted rounded px-1 py-0.5 text-foreground">{name}</code>{' '}
                  {t(`workflows:designer.script.pythonVariables.${name}`)}
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground mt-2">{t('workflows:designer.script.pythonResultHelp')}</p>
          </div>
        </>
      )}
    </div>
  );
}
