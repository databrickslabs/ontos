import { useTranslation } from 'react-i18next';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { AccessCollection, OdrlProfile, RuleKind } from '@/types/access-policy';
import ConstraintEditor from './constraint-editor';
import { DUTY_ACTIONS, REMEDY_ACTIONS, RULE_KINDS, emptyRule, type FormRule } from './odrl-helpers';

interface RuleBuilderProps {
  profile: OdrlProfile | null;
  audiences: AccessCollection[];
  assetCollections: AccessCollection[];
  value: FormRule[];
  onChange: (next: FormRule[]) => void;
  disabled?: boolean;
}

const KIND_STYLE: Record<RuleKind, string> = {
  permission: 'border-l-4 border-l-emerald-500',
  prohibition: 'border-l-4 border-l-red-500',
  obligation: 'border-l-4 border-l-amber-500',
};

/** Form-based editor for atomic ODRL rules (permissions, prohibitions, obligations). */
export default function RuleBuilder({ profile, audiences, assetCollections, value, onChange, disabled }: RuleBuilderProps) {
  const { t } = useTranslation(['access-policies']);
  const actions = profile?.actions || [];
  const dataActions = actions.filter((a) => !DUTY_ACTIONS.includes(a.key));
  const labelFor = (key: string) => actions.find((a) => a.key === key)?.label || key;

  const update = (key: string, patch: Partial<FormRule>) =>
    onChange(value.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  return (
    <div className="space-y-3">
      {value.length === 0 && <p className="text-sm text-muted-foreground">{t('access-policies:rules.empty')}</p>}
      {value.map((r, idx) => {
        const actionChoices = r.kind === 'obligation' ? actions.filter((a) => DUTY_ACTIONS.includes(a.key)) : dataActions;
        const subChoices = r.kind === 'prohibition' ? REMEDY_ACTIONS : r.kind === 'permission' ? DUTY_ACTIONS.slice(0, 3) : [];
        return (
          <Card key={r.key} className={KIND_STYLE[r.kind]} data-testid={`rule-${idx}`}>
            <CardContent className="space-y-3 p-4">
              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">{t('access-policies:rules.kind')}</Label>
                  <Select
                    value={r.kind}
                    disabled={disabled}
                    onValueChange={(v) => {
                      const kind = v as RuleKind;
                      update(r.key, {
                        kind,
                        duties: [],
                        action: kind === 'obligation' ? 'ontos:recertify' : DUTY_ACTIONS.includes(r.action) ? 'read' : r.action,
                      });
                    }}
                  >
                    <SelectTrigger className="h-8 w-36" aria-label={t('access-policies:rules.kind')}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {RULE_KINDS.map((k) => (
                        <SelectItem key={k} value={k}>
                          {t(`access-policies:ruleKinds.${k}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">{t('access-policies:rules.action')}</Label>
                  <Select value={r.action} disabled={disabled} onValueChange={(v) => update(r.key, { action: v })}>
                    <SelectTrigger className="h-8 w-44" aria-label={t('access-policies:rules.action')}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {actionChoices.map((a) => (
                        <SelectItem key={a.key} value={a.key}>
                          {a.label}
                          {a.included_in ? <span className="ml-1 text-xs text-muted-foreground">⊂ {labelFor(a.included_in)}</span> : null}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="ml-auto">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={disabled}
                    onClick={() => onChange(value.filter((x) => x.key !== r.key))}
                    aria-label={t('access-policies:rules.remove')}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>

              {/* Target */}
              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">{t('access-policies:rules.target')}</Label>
                  <Select
                    value={r.targetMode}
                    disabled={disabled}
                    onValueChange={(v) => update(r.key, { targetMode: v as FormRule['targetMode'], target: '' })}
                  >
                    <SelectTrigger className="h-8 w-40" aria-label={t('access-policies:rules.targetMode')}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="asset">{t('access-policies:rules.targetAsset')}</SelectItem>
                      <SelectItem value="collection">{t('access-policies:rules.targetCollection')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {r.targetMode === 'asset' ? (
                  <Input
                    className="h-8 w-80"
                    value={r.target}
                    disabled={disabled}
                    placeholder="uc:catalog.schema.table"
                    aria-label={t('access-policies:rules.targetRef')}
                    onChange={(e) => update(r.key, { target: e.target.value })}
                  />
                ) : (
                  <Select value={r.target} disabled={disabled} onValueChange={(v) => update(r.key, { target: v })}>
                    <SelectTrigger className="h-8 w-80" aria-label={t('access-policies:rules.targetRef')}>
                      <SelectValue placeholder={t('access-policies:rules.pickCollection')} />
                    </SelectTrigger>
                    <SelectContent>
                      {assetCollections.map((c) => (
                        <SelectItem key={c.uid} value={c.uid}>
                          {c.name} <span className="text-xs text-muted-foreground">({c.status})</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>

              {/* Assignee */}
              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">{t('access-policies:rules.assignee')}</Label>
                  <Select
                    value={r.assigneeMode}
                    disabled={disabled}
                    onValueChange={(v) => update(r.key, { assigneeMode: v as FormRule['assigneeMode'], assignee: '' })}
                  >
                    <SelectTrigger className="h-8 w-40" aria-label={t('access-policies:rules.assigneeMode')}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="audience">{t('access-policies:rules.assigneeAudience')}</SelectItem>
                      <SelectItem value="principal">{t('access-policies:rules.assigneePrincipal')}</SelectItem>
                      <SelectItem value="everyone">{t('access-policies:rules.assigneeEveryone')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {r.assigneeMode === 'audience' && (
                  <Select value={r.assignee} disabled={disabled} onValueChange={(v) => update(r.key, { assignee: v })}>
                    <SelectTrigger className="h-8 w-80" aria-label={t('access-policies:rules.assigneeRef')}>
                      <SelectValue placeholder={t('access-policies:rules.pickAudience')} />
                    </SelectTrigger>
                    <SelectContent>
                      {audiences.map((a) => (
                        <SelectItem key={a.uid} value={a.uid}>
                          {a.name} <span className="text-xs text-muted-foreground">({a.status})</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
                {r.assigneeMode === 'principal' && (
                  <Input
                    className="h-8 w-80"
                    value={r.assignee}
                    disabled={disabled}
                    placeholder="group:data-analysts | user:jane@example.com"
                    aria-label={t('access-policies:rules.assigneeRef')}
                    onChange={(e) => update(r.key, { assignee: e.target.value })}
                  />
                )}
              </div>

              {/* Constraints */}
              {r.kind !== 'obligation' && (
                <div className="space-y-1">
                  <Label className="text-xs">{t('access-policies:rules.constraints')}</Label>
                  <ConstraintEditor
                    profile={profile}
                    subjects={['context', 'asset']}
                    value={r.constraints}
                    disabled={disabled}
                    onChange={(constraints) => update(r.key, { constraints })}
                  />
                </div>
              )}

              {/* Duties / remedies */}
              {subChoices.length > 0 && (
                <div className="space-y-1">
                  <Label className="text-xs">
                    {r.kind === 'prohibition' ? t('access-policies:rules.remedies') : t('access-policies:rules.duties')}
                  </Label>
                  <div className="flex flex-wrap gap-4">
                    {subChoices.map((a) => (
                      <label key={a} className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={r.duties.includes(a)}
                          disabled={disabled}
                          onCheckedChange={(on) =>
                            update(r.key, { duties: on ? [...r.duties, a] : r.duties.filter((d) => d !== a) })
                          }
                        />
                        {labelFor(a)}
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}
      <div className="flex gap-2">
        {RULE_KINDS.map((k) => (
          <Button key={k} type="button" variant="outline" size="sm" disabled={disabled} onClick={() => onChange([...value, emptyRule(k)])}>
            <Plus className="mr-1 h-3 w-3" /> {t(`access-policies:ruleKinds.${k}`)}
          </Button>
        ))}
      </div>
    </div>
  );
}
