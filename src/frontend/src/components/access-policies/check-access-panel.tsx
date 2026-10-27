import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, ShieldCheck, ShieldAlert, ShieldQuestion, ShieldX } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { useApi } from '@/hooks/use-api';
import { useOdrlProfile } from '@/hooks/use-access-policies';
import type { AccessDecision } from '@/types/access-policy';
import { DUTY_ACTIONS } from './odrl-helpers';

interface Props {
  /** When set, evaluate only this policy (what-if, any status) instead of all active policies. */
  policyId?: string;
  defaultAsset?: string;
}

const VERDICT_STYLE: Record<AccessDecision['verdict'], { icon: typeof ShieldCheck; cls: string }> = {
  allow: { icon: ShieldCheck, cls: 'text-emerald-600' },
  deny: { icon: ShieldX, cls: 'text-red-600' },
  conditional: { icon: ShieldAlert, cls: 'text-amber-600' },
  not_applicable: { icon: ShieldQuestion, cls: 'text-muted-foreground' },
};

function parseKv(text: string): Record<string, string[] | string> {
  // "ontos:domain=Sales, Marketing; purpose=analytics"
  const out: Record<string, string[] | string> = {};
  for (const part of text.split(';')) {
    const [k, ...rest] = part.split('=');
    if (!k?.trim() || rest.length === 0) continue;
    const vals = rest.join('=').split(',').map((v) => v.trim()).filter(Boolean);
    out[k.trim()] = vals.length === 1 ? vals[0] : vals;
  }
  return out;
}

/** "Can principal P do action A on asset T?" — deterministic evaluation with an explanation. */
export default function CheckAccessPanel({ policyId, defaultAsset }: Props) {
  const { t } = useTranslation(['access-policies']);
  const { post } = useApi();
  const profile = useOdrlProfile();
  const [principal, setPrincipal] = useState('');
  const [groups, setGroups] = useState('');
  const [action, setAction] = useState('read');
  const [asset, setAsset] = useState(defaultAsset || '');
  const [assetAttrs, setAssetAttrs] = useState('');
  const [context, setContext] = useState('');
  const [duties, setDuties] = useState<string[]>([]);
  const [onlyThis, setOnlyThis] = useState(!!policyId);
  const [loading, setLoading] = useState(false);
  const [decision, setDecision] = useState<AccessDecision | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    const res = await post<AccessDecision>('/api/access-policies/check-access', {
      principal: principal.trim(),
      action,
      asset: asset.trim(),
      principal_groups: groups.split(',').map((g) => g.trim()).filter(Boolean),
      asset_attributes: parseKv(assetAttrs),
      context: parseKv(context),
      fulfilled_duties: duties,
      policy_ids: policyId && onlyThis ? [policyId] : undefined,
    });
    setLoading(false);
    if (res.error || !res.data) {
      setError(res.error || t('access-policies:check.failed'));
      setDecision(null);
      return;
    }
    setDecision(res.data);
  };

  const V = decision ? VERDICT_STYLE[decision.verdict] : null;
  const dataActions = (profile?.actions || []).filter((a) => !DUTY_ACTIONS.includes(a.key));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t('access-policies:check.title')}</CardTitle>
        <CardDescription>
          {policyId ? t('access-policies:check.descriptionPolicy') : t('access-policies:check.descriptionAll')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="space-y-1">
            <Label htmlFor="ca-principal">{t('access-policies:check.principal')}</Label>
            <Input id="ca-principal" value={principal} placeholder="jane@example.com" onChange={(e) => setPrincipal(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ca-groups">{t('access-policies:check.groups')}</Label>
            <Input id="ca-groups" value={groups} placeholder="sales-analysts, emea" onChange={(e) => setGroups(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>{t('access-policies:check.action')}</Label>
            <Select value={action} onValueChange={setAction}>
              <SelectTrigger aria-label={t('access-policies:check.action')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {dataActions.map((a) => (
                  <SelectItem key={a.key} value={a.key}>
                    {a.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="ca-asset">{t('access-policies:check.asset')}</Label>
            <Input id="ca-asset" value={asset} placeholder="uc:main.sales.orders" onChange={(e) => setAsset(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ca-asset-attrs">{t('access-policies:check.assetAttributes')}</Label>
            <Input
              id="ca-asset-attrs"
              value={assetAttrs}
              placeholder="ontos:classification=pii; ontos:domain=Sales"
              onChange={(e) => setAssetAttrs(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ca-context">{t('access-policies:check.context')}</Label>
            <Input id="ca-context" value={context} placeholder="purpose=analytics; spatial=EU" onChange={(e) => setContext(e.target.value)} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <span className="text-sm text-muted-foreground">{t('access-policies:check.fulfilledDuties')}</span>
          {DUTY_ACTIONS.slice(0, 3).map((d) => (
            <label key={d} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={duties.includes(d)}
                onChange={(e) => setDuties(e.target.checked ? [...duties, d] : duties.filter((x) => x !== d))}
              />
              {profile?.actions.find((a) => a.key === d)?.label || d}
            </label>
          ))}
          {policyId && (
            <label className="ml-auto flex items-center gap-2 text-sm">
              <Switch checked={onlyThis} onCheckedChange={setOnlyThis} />
              {t('access-policies:check.onlyThisPolicy')}
            </label>
          )}
          <Button onClick={run} disabled={loading || !principal.trim() || !asset.trim()} size="sm">
            {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('access-policies:check.run')}
          </Button>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}
        {decision && V && (
          <div className="space-y-3 rounded-md border p-4" data-testid="access-decision">
            <div className="flex items-center gap-2">
              <V.icon className={`h-6 w-6 ${V.cls}`} />
              <span className={`text-lg font-semibold ${V.cls}`}>{t(`access-policies:verdict.${decision.verdict}`)}</span>
              <Badge variant="outline" className="ml-2">
                {decision.mode === 'what_if' ? t('access-policies:check.modeWhatIf') : t('access-policies:check.modeActive')}
              </Badge>
              <span className="text-xs text-muted-foreground">
                {t('access-policies:check.evaluated', { count: decision.evaluated_policies.length })}
              </span>
            </div>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {decision.explanation.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
            {Object.keys(decision.resolved_principal_attributes || {}).length > 0 && (
              <p className="text-xs text-muted-foreground">
                {t('access-policies:check.resolvedAttributes')}{' '}
                {Object.entries(decision.resolved_principal_attributes)
                  .map(([k, v]) => `${k}=${v.join(', ') || '∅'}`)
                  .join('; ')}
              </p>
            )}
            {decision.matches.length > 0 && (
              <div className="space-y-2">
                <p className="text-sm font-medium">{t('access-policies:check.matchedRules')}</p>
                {decision.matches.map((m, i) => (
                  <div key={i} className="rounded border bg-muted/40 p-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={m.kind === 'prohibition' ? 'destructive' : 'secondary'}>
                        {t(`access-policies:ruleKinds.${m.kind}`)}
                      </Badge>
                      <span className="font-medium">{m.policy_name}</span>
                      <span>#{m.index + 1}</span>
                      <Badge variant="outline">{t(`access-policies:effect.${m.effect}`)}</Badge>
                      {m.unenforceable.length > 0 && (
                        <Badge variant="outline" className="border-amber-400 text-amber-700">
                          {t('access-policies:check.notPlatformEnforced')}: {m.unenforceable.join(', ')}
                        </Badge>
                      )}
                    </div>
                    {m.reasons.length > 0 && (
                      <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                        {m.reasons.map((r, j) => (
                          <li key={j}>{r}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            )}
            {decision.warnings.length > 0 && (
              <p className="text-xs text-amber-700">{decision.warnings.join(' · ')}</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
