import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, ShieldAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import GateExemptionsField, {
  EMPTY_GATE_EXEMPTIONS,
} from '@/components/workflows/gate-exemptions-field';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type { GateExemptions } from '@/types/process-workflow';

export const GUARD_URL = '/api/certified-deprecation-guard';

/**
 * Where the certified deprecation guard is switched off.
 *
 * The guard refuses a direct deprecation of a certified data product or data
 * contract (it needs an approved status change request). Like a status gate,
 * it can be switched off per domain, data product or data contract; the
 * backend logs and audits each skip.
 */
export default function CertifiedDeprecationGuardSettings() {
  const { t } = useTranslation(['workflow-gates', 'common']);
  const { get, put } = useApi();
  const { toast } = useToast();
  const [value, setValue] = useState<GateExemptions>(EMPTY_GATE_EXEMPTIONS);
  const [missing, setMissing] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    get<GateExemptions>(GUARD_URL).then((response) => {
      if (cancelled) return;
      if (response.error || !response.data) {
        toast({ title: t('workflow-gates:certifiedGuard.loadFailed'), variant: 'destructive' });
      } else {
        setValue({ ...EMPTY_GATE_EXEMPTIONS, ...response.data });
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [get, toast, t]);

  const onMissingChange = useCallback((ids: string[]) => setMissing(ids), []);

  const save = async () => {
    if (missing.length > 0) {
      toast({
        title: t('workflow-gates:certifiedGuard.saveFailed'),
        description: t('workflow-gates:certifiedGuard.missingOnSave', { count: missing.length }),
        variant: 'destructive',
      });
      return;
    }
    setSaving(true);
    const response = await put<GateExemptions>(GUARD_URL, value);
    setSaving(false);
    if (response.error) {
      const id = String(response.errorParams?.id ?? '');
      toast({
        title: t('workflow-gates:certifiedGuard.saveFailed'),
        description: response.errorCode === 'gate_exemption_not_found'
          ? t('workflow-gates:certifiedGuard.notFound', { id, defaultValue: response.error })
          : response.error,
        variant: 'destructive',
      });
      return;
    }
    toast({ title: t('workflow-gates:certifiedGuard.saved') });
  };

  return (
    <Card data-testid="certified-deprecation-guard">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <ShieldAlert className="h-5 w-5" />
          {t('workflow-gates:certifiedGuard.title')}
        </CardTitle>
        <CardDescription>{t('workflow-gates:certifiedGuard.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : (
          <>
            <GateExemptionsField
              value={value}
              onChange={setValue}
              onMissingChange={onMissingChange}
              hint={t('workflow-gates:certifiedGuard.hint')}
            />
            <Button onClick={save} disabled={saving} size="sm">
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('common:actions.save')}
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
