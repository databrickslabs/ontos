import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, Download, Loader2, Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import {
  ADM_SCHEMA_PATTERN, type AdmConformanceFinding, type AdmSchemaState,
} from '@/types/authority-resolution';
import { authorityErrorMessage } from '@/components/authority-resolution/authority-errors';
import AdmFindingsList from '@/components/authority-resolution/adm-findings-list';

const FEATURE_ID = 'authority-resolution';

/**
 * The shared ADM schema (`catalog.schema`) every Authority Relation reads its evidence from,
 * with its conformance to the pinned ADM subset. Admins set it; others see it read-only.
 */
export default function AdmSchemaSettings() {
  const { t } = useTranslation(['authority-resolution', 'common']);
  const { get, put } = useApi();
  const { toast } = useToast();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const isAdmin = !permissionsLoading && hasPermission(FEATURE_ID, FeatureAccessLevel.ADMIN);

  const [state, setState] = useState<AdmSchemaState | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [ddlBusy, setDdlBusy] = useState(false);
  // Findings of the last refused (422) save: the schema is not conformant, nothing changed.
  const [refusal, setRefusal] = useState<AdmConformanceFinding[] | null>(null);

  // The initial state is loading; the request settles it after the await (no synchronous set in the effect).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { data, error, errorCode } = await get<AdmSchemaState>('/api/authority/adm-schema');
      if (cancelled) return;
      if (error) {
        setLoadError(authorityErrorMessage(t, error, errorCode));
      } else {
        setState(data);
        setDraft(data.schema ?? '');
        setLoadError(null);
      }
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [get, t]);

  const trimmed = draft.trim();
  const formatInvalid = trimmed !== '' && !ADM_SCHEMA_PATTERN.test(trimmed);
  const unchanged = trimmed === (state?.schema ?? '');

  const save = async () => {
    if (formatInvalid) {
      toast({ title: t('adm.settings.invalidFormat'), variant: 'destructive' });
      return;
    }
    setSaving(true);
    const { data, error, errorCode, errorParams, status } = await put<AdmSchemaState>(
      '/api/authority/adm-schema',
      { adm_schema: trimmed || null },
    );
    setSaving(false);
    if (error) {
      if (status === 422 && errorCode === 'adm_nonconformant') {
        const findings = errorParams?.findings;
        setRefusal(Array.isArray(findings) ? findings as AdmConformanceFinding[] : []);
      }
      toast({
        title: t('common:toast.failed'),
        description: authorityErrorMessage(t, error, errorCode, errorParams),
        variant: 'destructive',
      });
      return;
    }
    setRefusal(null);
    setState(data);
    setDraft(data.schema ?? '');
    toast({ title: t('adm.settings.saved') });
  };

  const fetchDdl = async (): Promise<string | null> => {
    if (!state?.schema) return null;
    setDdlBusy(true);
    const { data, error, errorCode } = await get<string>(
      `/api/authority/adm-schema/ddl?schema=${encodeURIComponent(state.schema)}`,
    );
    setDdlBusy(false);
    if (error || typeof data !== 'string') {
      toast({ title: t('common:toast.failed'), description: authorityErrorMessage(t, error, errorCode), variant: 'destructive' });
      return null;
    }
    return data;
  };

  const copyDdl = async () => {
    const ddl = await fetchDdl();
    if (ddl === null) return;
    await navigator.clipboard.writeText(ddl);
    toast({ title: t('adm.settings.ddlCopied') });
  };

  const downloadDdl = async () => {
    const ddl = await fetchDdl();
    if (ddl === null || !state?.schema) return;
    const url = URL.createObjectURL(new Blob([ddl], { type: 'text/plain' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${state.schema.replace(/\./g, '_')}_adm.sql`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  if (loading) {
    return (
      <section className="space-y-3 border-t pt-6" aria-busy="true">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-9 w-full max-w-md" />
        <Skeleton className="h-16 w-full" />
      </section>
    );
  }

  if (loadError || !state) {
    return (
      <section className="space-y-3 border-t pt-6">
        <h2 className="text-base font-semibold">{t('adm.settings.title')}</h2>
        <Alert variant="destructive">
          <AlertDescription>{loadError || t('errors.generic')}</AlertDescription>
        </Alert>
      </section>
    );
  }

  const conformance = state.conformance;

  return (
    <section className="space-y-4 border-t pt-6">
      <div className="space-y-1">
        <h2 className="text-base font-semibold">{t('adm.settings.title')}</h2>
        <p className="text-sm text-muted-foreground">{t('adm.settings.description')}</p>
      </div>

      <div className="space-y-1">
        <Label htmlFor="adm-schema-setting">{t('adm.settings.schemaLabel')}</Label>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            id="adm-schema-setting"
            className="max-w-md font-mono"
            value={draft}
            disabled={!isAdmin || saving}
            placeholder={t('adm.settings.schemaPlaceholder')}
            aria-invalid={formatInvalid || undefined}
            onChange={(e) => setDraft(e.target.value)}
          />
          {isAdmin && (
            <Button size="sm" onClick={save} disabled={saving || unchanged || formatInvalid}>
              {saving ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Save className="h-4 w-4 mr-1" />}
              {t('common:actions.save')}
            </Button>
          )}
        </div>
        {formatInvalid && <p className="text-xs text-destructive">{t('adm.settings.invalidFormat')}</p>}
        <p className="text-xs text-muted-foreground">
          {isAdmin ? t('adm.settings.clearHint') : t('adm.settings.readOnly')}
        </p>
      </div>

      {refusal && (
        <Alert variant="destructive">
          <AlertTitle>{t('adm.errors.nonconformant')}</AlertTitle>
          <AlertDescription className="space-y-2">
            <p>{t('adm.settings.refusedHint')}</p>
            <AdmFindingsList findings={refusal} />
          </AlertDescription>
        </Alert>
      )}

      <div className="space-y-2">
        <div className="text-xs uppercase text-muted-foreground">{t('adm.settings.conformanceLabel')}</div>
        {!state.schema && <p className="text-sm text-muted-foreground">{t('adm.settings.notConfigured')}</p>}
        {state.schema && !conformance && <p className="text-sm text-muted-foreground">{t('adm.settings.notChecked')}</p>}
        {state.schema && conformance?.status === 'conformant' && (
          <div className="space-y-1">
            <Badge variant="default">{t('adm.settings.conformant', { version: state.adm_version })}</Badge>
            {conformance.checked_tables.length > 0 && (
              <p className="text-xs text-muted-foreground font-mono">{conformance.checked_tables.join(', ')}</p>
            )}
          </div>
        )}
        {state.schema && conformance?.status === 'nonconformant' && (
          <div className="space-y-2">
            <Badge variant="destructive">{t('adm.settings.nonconformant', { version: state.adm_version })}</Badge>
            <AdmFindingsList findings={conformance.findings} />
          </div>
        )}
        {state.schema && conformance?.status === 'unavailable' && (
          <div className="space-y-1">
            <Badge variant="secondary">{t('adm.settings.unavailable')}</Badge>
            <p className="text-xs text-muted-foreground">
              {authorityErrorMessage(t, null, conformance.error_code)}
            </p>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={copyDdl} disabled={!state.schema || ddlBusy}>
          <Copy className="h-4 w-4 mr-1" /> {t('adm.settings.copyDdl')}
        </Button>
        <Button variant="outline" size="sm" onClick={downloadDdl} disabled={!state.schema || ddlBusy}>
          <Download className="h-4 w-4 mr-1" /> {t('adm.settings.downloadDdl')}
        </Button>
      </div>
    </section>
  );
}
