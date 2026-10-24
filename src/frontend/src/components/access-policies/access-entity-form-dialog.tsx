import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import DomainMultiSelector from '@/components/ui/domain-multi-selector';
import TagSelector from '@/components/ui/tag-selector';
import type { AssignedTag } from '@/components/ui/tag-chip';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { useTeams } from '@/hooks/use-teams';
import { useProjectContext } from '@/stores/project-store';
import { useAccessCollections, useOdrlProfile } from '@/hooks/use-access-policies';
import type {
  AccessCollection,
  AccessEntity,
  AccessKind,
  AccessPolicy,
  AccessTarget,
  DeliveryModeKey,
  OdrlConflict,
  OdrlPolicyType,
  OdrlRules,
  PolicyValidation,
  ReleaseTargets,
  TargetSystem,
} from '@/types/access-policy';
import { KIND_SEGMENT } from '@/types/access-policy';
import ConstraintEditor from './constraint-editor';
import RuleBuilder from './rule-builder';
import { constraintToForm, formRuleProblems, formToConstraint, formToRules, rulesToForm, type FormConstraint, type FormRule } from './odrl-helpers';

interface Props {
  kind: AccessKind;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Existing entity → edit mode; absent → create mode. */
  entity?: AccessEntity | null;
  onSaved: (entity: AccessEntity) => void;
}

const NONE = '__none__';
const DELIVERY_MODES: DeliveryModeKey[] = ['direct', 'indirect', 'manual'];

function normalizeTags(tags: (string | AssignedTag)[]) {
  return tags.map((tag) =>
    typeof tag === 'string' ? tag : tag.fully_qualified_name || { tag_id: tag.tag_id, assigned_value: tag.assigned_value },
  );
}

export default function AccessEntityFormDialog({ kind, open, onOpenChange, entity, onSaved }: Props) {
  const { t } = useTranslation(['access-policies', 'common']);
  const { get, post, put } = useApi();
  const { toast } = useToast();
  const { teams } = useTeams();
  const { availableProjects, fetchUserProjects } = useProjectContext();
  const profile = useOdrlProfile();
  const { audiences, assetCollections } = useAccessCollections();
  const isEdit = !!entity;
  const contentLocked = isEdit && !entity!.editable;

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [version, setVersion] = useState('1.0.0');
  const [ownerTeamId, setOwnerTeamId] = useState('');
  const [projectId, setProjectId] = useState('');
  const [domainIds, setDomainIds] = useState<string[]>([]);
  const [primaryDomainId, setPrimaryDomainId] = useState<string | null>(null);
  const [tags, setTags] = useState<(string | AssignedTag)[]>([]);
  const [personalDraft, setPersonalDraft] = useState(false);
  // Policy
  const [policyType, setPolicyType] = useState<OdrlPolicyType>('Set');
  const [conflict, setConflict] = useState<OdrlConflict>('prohibit');
  const [inheritFrom, setInheritFrom] = useState('');
  // Offers: the Data Product whose terms of use this policy states.
  const [subjectProductId, setSubjectProductId] = useState('');
  const [products, setProducts] = useState<{ id: string; name: string }[]>([]);
  const [rules, setRules] = useState<FormRule[]>([]);
  const [rulesTab, setRulesTab] = useState<'builder' | 'json'>('builder');
  const [rulesJson, setRulesJson] = useState('{}');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [validation, setValidation] = useState<PolicyValidation | null>(null);
  // Collections
  const [members, setMembers] = useState('');
  const [refinement, setRefinement] = useState<FormConstraint[]>([]);
  const [refinementUnsupported, setRefinementUnsupported] = useState(false);
  // Targets
  const [targetKey, setTargetKey] = useState('');
  const [system, setSystem] = useState('uc');
  const [systems, setSystems] = useState<TargetSystem[]>([]);
  const [scope, setScope] = useState('');
  const [deliveryModes, setDeliveryModes] = useState<DeliveryModeKey[]>([]);
  const [schedule, setSchedule] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || kind !== 'target' || systems.length) return;
    get<ReleaseTargets>('/api/access-policies/compile-targets').then((res) => {
      if (res.data?.systems) setSystems(res.data.systems);
    });
  }, [open, kind, systems.length, get]);

  useEffect(() => {
    if (!open || kind !== 'policy' || policyType !== 'Offer' || products.length) return;
    get<{ id: string; name: string }[]>('/api/data-products').then((res) => {
      if (Array.isArray(res.data)) setProducts(res.data.map((p) => ({ id: p.id, name: p.name })));
    });
  }, [open, kind, policyType, products.length, get]);

  useEffect(() => {
    if (!open) return;
    fetchUserProjects();
    setValidation(null);
    setJsonError(null);
    setName(entity?.name || '');
    setDescription(entity?.description || '');
    setVersion(entity?.version || '1.0.0');
    setOwnerTeamId(entity?.owner_team_id || '');
    setProjectId(entity?.project_id || '');
    setDomainIds((entity?.domains || []).map((d) => String(d.domain_id)));
    setPrimaryDomainId(String((entity?.domains || []).find((d) => d.is_primary)?.domain_id ?? '') || null);
    setTags(entity?.tags || []);
    setPersonalDraft(false);
    if (kind === 'policy') {
      const p = entity as AccessPolicy | undefined;
      setPolicyType(p?.policy_type || 'Set');
      setConflict(p?.conflict || 'prohibit');
      setInheritFrom((p?.inherit_from || [])[0] || '');
      setSubjectProductId(p?.subject_entity_type === 'data_product' ? p.subject_entity_id || '' : '');
      const stored: OdrlRules = p?.rules || {};
      const form = rulesToForm(stored);
      setRules(form ?? []);
      setRulesJson(JSON.stringify(stored, null, 2));
      setRulesTab(form === null ? 'json' : 'builder');
    } else if (kind === 'target') {
      const tg = entity as AccessTarget | undefined;
      setTargetKey(tg?.key || '');
      setSystem(tg?.system || 'uc');
      setScope((tg?.scope || []).join('\n'));
      setDeliveryModes(tg?.delivery_modes || []);
      setSchedule(tg?.reconcile_schedule || '');
    } else {
      const c = entity as AccessCollection | undefined;
      setMembers((c?.members || []).join('\n'));
      const forms = (c?.refinement || []).map(constraintToForm);
      setRefinementUnsupported(forms.some((f) => f === null));
      setRefinement(forms.filter((f): f is FormConstraint => !!f));
    }
  }, [open, entity, kind, fetchUserProjects]);

  const currentRules = (): OdrlRules | null => {
    if (rulesTab === 'builder') return formToRules(rules);
    try {
      const parsed = JSON.parse(rulesJson || '{}');
      setJsonError(null);
      return parsed;
    } catch (e: any) {
      setJsonError(e.message);
      return null;
    }
  };

  const switchTab = (tab: string) => {
    if (tab === 'json') {
      setRulesJson(JSON.stringify(formToRules(rules), null, 2));
      setRulesTab('json');
      return;
    }
    const parsed = currentRules();
    if (!parsed) return;
    const form = rulesToForm(parsed);
    if (form === null) {
      toast({ title: t('access-policies:form.builderUnsupported'), variant: 'destructive' });
      return;
    }
    setRules(form);
    setRulesTab('builder');
  };

  const validate = async () => {
    const r = currentRules();
    if (!r) return;
    const res = await post<PolicyValidation>('/api/access-policies/validate', {
      policy_type: policyType,
      conflict,
      inherit_from: inheritFrom ? [inheritFrom] : [],
      rules: r,
    });
    if (res.data) setValidation(res.data);
  };

  const [policyParents, setPolicyParents] = useState<{ uid: string; name: string }[]>([]);
  useEffect(() => {
    if (!open || kind !== 'policy') return;
    get<AccessPolicy[]>('/api/access-policies/policies').then((res) => {
      const rows = Array.isArray(res.data) ? res.data : [];
      setPolicyParents(rows.filter((p) => p.uid !== entity?.uid).map((p) => ({ uid: p.uid, name: p.name })));
    });
  }, [open, kind, get, entity?.uid]);

  const save = async () => {
    if (!name.trim()) {
      toast({ title: t('access-policies:form.nameRequired'), variant: 'destructive' });
      return;
    }
    const base: Record<string, unknown> = {
      name: name.trim(),
      description: description.trim() || null,
      owner_team_id: ownerTeamId || null,
      project_id: projectId || null,
      domain_ids: domainIds,
      primary_domain_id: primaryDomainId,
      tags: normalizeTags(tags),
    };
    if (!isEdit) {
      base.version = version || '1.0.0';
      base.personal_draft = personalDraft;
    }
    if (!contentLocked) {
      if (kind === 'policy') {
        const problems = rulesTab === 'builder' ? formRuleProblems(rules) : [];
        if (problems.length) {
          toast({ title: t('access-policies:form.incompleteRules'), description: problems.join(' · '), variant: 'destructive' });
          return;
        }
        const r = currentRules();
        if (!r) return;
        Object.assign(base, {
          policy_type: policyType,
          conflict,
          inherit_from: inheritFrom ? [inheritFrom] : [],
          rules: r,
          subject_entity_type: policyType === 'Offer' && subjectProductId ? 'data_product' : null,
          subject_entity_id: policyType === 'Offer' && subjectProductId ? subjectProductId : null,
        });
      } else if (kind === 'target') {
        Object.assign(base, {
          key: targetKey.trim(),
          system,
          scope: scope.split(/[\n,]/).map((x) => x.trim()).filter(Boolean),
          delivery_modes: deliveryModes,
          reconcile_schedule: schedule.trim() || null,
        });
      } else {
        if (refinementUnsupported) {
          // Keep the stored (logical) refinement untouched; only members are editable in the form.
        } else {
          base.refinement = refinement.filter((c) => c.leftOperand && c.value.trim()).map(formToConstraint);
        }
        base.members = members.split(/[\n,]/).map((m) => m.trim()).filter(Boolean);
      }
    }
    setSaving(true);
    try {
      const url = `/api/access-policies/${KIND_SEGMENT[kind]}${isEdit ? `/${entity!.id}` : ''}`;
      const res = isEdit ? await put<AccessEntity>(url, base) : await post<AccessEntity>(url, base);
      if (res.error || !res.data) throw new Error(res.error || t('access-policies:form.saveFailed'));
      toast({ title: isEdit ? t('access-policies:form.updated') : t('access-policies:form.created') });
      onSaved(res.data);
      onOpenChange(false);
    } catch (e: any) {
      toast({ title: t('access-policies:form.saveFailed'), description: e.message, variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  const title = t(`access-policies:form.title.${isEdit ? 'edit' : 'create'}.${kind}`);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-5xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{t(`access-policies:form.description.${kind}`)}</DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {contentLocked && (
            <p className="rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
              {t('access-policies:form.contentLocked', { status: entity!.status })}
            </p>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1 md:col-span-2">
              <Label htmlFor="ap-name">{t('common:labels.name')}</Label>
              <Input id="ap-name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-1 md:col-span-2">
              <Label htmlFor="ap-description">{t('common:labels.description')}</Label>
              <Textarea id="ap-description" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>{t('access-policies:form.ownerTeam')}</Label>
              <Select value={ownerTeamId || NONE} onValueChange={(v) => setOwnerTeamId(v === NONE ? '' : v)}>
                <SelectTrigger aria-label={t('access-policies:form.ownerTeam')}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>{t('access-policies:form.none')}</SelectItem>
                  {teams.map((tm) => (
                    <SelectItem key={tm.id} value={tm.id}>
                      {tm.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>{t('access-policies:form.project')}</Label>
              <Select value={projectId || NONE} onValueChange={(v) => setProjectId(v === NONE ? '' : v)}>
                <SelectTrigger aria-label={t('access-policies:form.project')}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>{t('access-policies:form.none')}</SelectItem>
                  {availableProjects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <DomainMultiSelector
                label={t('access-policies:form.domains')}
                value={domainIds}
                primaryDomainId={primaryDomainId}
                onChange={(ids, primary) => {
                  setDomainIds(ids);
                  setPrimaryDomainId(primary);
                }}
              />
            </div>
            <div className="space-y-1">
              <TagSelector label={t('access-policies:form.tags')} value={tags} onChange={setTags} />
            </div>
            {!isEdit && (
              <>
                <div className="space-y-1">
                  <Label htmlFor="ap-version">{t('access-policies:form.version')}</Label>
                  <Input id="ap-version" value={version} onChange={(e) => setVersion(e.target.value)} />
                </div>
                <label className="mt-6 flex items-center gap-2 text-sm">
                  <Checkbox checked={personalDraft} onCheckedChange={(v) => setPersonalDraft(!!v)} />
                  {t('access-policies:form.personalDraft')}
                </label>
              </>
            )}
          </div>

          {kind === 'policy' ? (
            <div className="space-y-4">
              <div className="grid gap-4 md:grid-cols-3">
                <div className="space-y-1">
                  <Label>{t('access-policies:form.policyType')}</Label>
                  <Select value={policyType} disabled={contentLocked} onValueChange={(v) => setPolicyType(v as OdrlPolicyType)}>
                    <SelectTrigger aria-label={t('access-policies:form.policyType')}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(profile?.policy_types || ['Set', 'Offer', 'Agreement']).map((pt) => (
                        <SelectItem key={pt} value={pt}>
                          {t(`access-policies:policyTypes.${pt}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label>{t('access-policies:form.conflict')}</Label>
                  <Select value={conflict} disabled={contentLocked} onValueChange={(v) => setConflict(v as OdrlConflict)}>
                    <SelectTrigger aria-label={t('access-policies:form.conflict')}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(['prohibit', 'perm', 'invalid'] as OdrlConflict[]).map((c) => (
                        <SelectItem key={c} value={c}>
                          {t(`access-policies:conflicts.${c}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ap-inherit">{t('access-policies:form.inheritFrom')}</Label>
                  <Input
                    id="ap-inherit"
                    value={inheritFrom}
                    disabled={contentLocked}
                    placeholder="urn:ontos:policy:…"
                    onChange={(e) => setInheritFrom(e.target.value)}
                    list="ap-parent-policies"
                  />
                  <datalist id="ap-parent-policies">
                    {policyParents.map((p) => (
                      <option key={p.uid} value={p.uid}>
                        {p.name}
                      </option>
                    ))}
                  </datalist>
                </div>
              </div>

              {policyType === 'Offer' && (
                <div className="space-y-1">
                  <Label>{t('access-policies:form.offerFor')}</Label>
                  <Select
                    value={subjectProductId || '__none__'}
                    disabled={contentLocked}
                    onValueChange={(v) => setSubjectProductId(v === '__none__' ? '' : v)}
                  >
                    <SelectTrigger aria-label={t('access-policies:form.offerFor')}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none__">{t('access-policies:form.offerForNone')}</SelectItem>
                      {products.map((p) => (
                        <SelectItem key={p.id} value={p.id}>
                          {p.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">{t('access-policies:form.offerForHint')}</p>
                </div>
              )}

              <Tabs value={rulesTab} onValueChange={switchTab}>
                <div className="flex items-center justify-between">
                  <TabsList>
                    <TabsTrigger value="builder">{t('access-policies:form.builder')}</TabsTrigger>
                    <TabsTrigger value="json">{t('access-policies:form.json')}</TabsTrigger>
                  </TabsList>
                  <Button type="button" variant="outline" size="sm" onClick={validate}>
                    {t('access-policies:form.validate')}
                  </Button>
                </div>
                <TabsContent value="builder" className="pt-3">
                  <RuleBuilder
                    profile={profile}
                    audiences={audiences}
                    assetCollections={assetCollections}
                    value={rules}
                    onChange={setRules}
                    disabled={contentLocked}
                  />
                </TabsContent>
                <TabsContent value="json" className="space-y-2 pt-3">
                  <p className="text-xs text-muted-foreground">{t('access-policies:form.jsonHint')}</p>
                  <Textarea
                    className="min-h-[260px] font-mono text-xs"
                    value={rulesJson}
                    disabled={contentLocked}
                    aria-label={t('access-policies:form.json')}
                    onChange={(e) => setRulesJson(e.target.value)}
                  />
                  {jsonError && <p className="text-xs text-destructive">{jsonError}</p>}
                </TabsContent>
              </Tabs>

              {validation && (
                <div className="space-y-1 rounded-md border p-3 text-sm" data-testid="validation-result">
                  {validation.valid && validation.issues.length === 0 ? (
                    <p className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400">
                      <CheckCircle2 className="h-4 w-4" /> {t('access-policies:form.valid')}
                    </p>
                  ) : (
                    validation.issues.map((i, idx) => (
                      <p key={idx} className={i.severity === 'error' ? 'text-destructive' : 'text-amber-700 dark:text-amber-400'}>
                        <AlertTriangle className="mr-1 inline h-3 w-3" />
                        <code className="text-xs">{i.path || 'policy'}</code> — {i.message}
                      </p>
                    ))
                  )}
                </div>
              )}
            </div>
          ) : kind === 'target' ? (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1">
                <Label htmlFor="ap-target-key">{t('access-policies:targets.key')}</Label>
                <Input
                  id="ap-target-key"
                  value={targetKey}
                  disabled={contentLocked}
                  placeholder="uc-prod"
                  className="font-mono"
                  onChange={(e) => setTargetKey(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">{t('access-policies:targets.keyHint')}</p>
              </div>
              <div className="space-y-1">
                <Label>{t('access-policies:targets.system')}</Label>
                <Select value={system} disabled={contentLocked} onValueChange={setSystem}>
                  <SelectTrigger aria-label={t('access-policies:targets.system')}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(systems.length ? systems : [{ system: 'uc', label: 'Unity Catalog' } as TargetSystem]).map((sy) => (
                      <SelectItem key={sy.system} value={sy.system}>
                        {sy.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="ap-target-scope">{t('access-policies:targets.scope')}</Label>
                <Textarea
                  id="ap-target-scope"
                  rows={4}
                  disabled={contentLocked}
                  className="font-mono text-xs"
                  placeholder={'main.sales\nfinance'}
                  value={scope}
                  onChange={(e) => setScope(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">{t('access-policies:targets.scopeHint')}</p>
              </div>
              <div className="space-y-3">
                <div className="space-y-1">
                  <Label>{t('access-policies:targets.deliveryModes')}</Label>
                  <div className="flex flex-wrap gap-4">
                    {DELIVERY_MODES.map((m) => (
                      <label key={m} className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={deliveryModes.includes(m)}
                          disabled={contentLocked}
                          onCheckedChange={(v) =>
                            setDeliveryModes((cur) => (v ? [...cur, m] : cur.filter((x) => x !== m)))
                          }
                        />
                        {t(`access-policies:releases.modes.${m}`)}
                      </label>
                    ))}
                  </div>
                  <p className="text-xs text-muted-foreground">{t('access-policies:targets.deliveryModesHint')}</p>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ap-target-schedule">{t('access-policies:targets.schedule')}</Label>
                  <Input
                    id="ap-target-schedule"
                    value={schedule}
                    disabled={contentLocked}
                    placeholder="0 0 6 * * ?"
                    className="font-mono"
                    onChange={(e) => setSchedule(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">{t('access-policies:targets.scheduleHint')}</p>
                </div>
              </div>
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1">
                <Label htmlFor="ap-members">
                  {kind === 'audience' ? t('access-policies:form.principals') : t('access-policies:form.assets')}
                </Label>
                <Textarea
                  id="ap-members"
                  rows={6}
                  disabled={contentLocked}
                  className="font-mono text-xs"
                  placeholder={kind === 'audience' ? 'group:sales-analysts\nuser:jane@example.com' : 'uc:main.sales\nuc:main.finance.*'}
                  value={members}
                  onChange={(e) => setMembers(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  {kind === 'audience' ? t('access-policies:form.principalsHint') : t('access-policies:form.assetsHint')}
                </p>
              </div>
              <div className="space-y-1">
                <Label>{t('access-policies:form.refinement')}</Label>
                <p className="text-xs text-muted-foreground">
                  {kind === 'audience' ? t('access-policies:form.audienceRefinementHint') : t('access-policies:form.assetRefinementHint')}
                </p>
                {refinementUnsupported ? (
                  <p className="text-xs text-amber-700">{t('access-policies:form.refinementUnsupported')}</p>
                ) : (
                  <ConstraintEditor
                    profile={profile}
                    subjects={kind === 'audience' ? ['party'] : ['asset']}
                    value={refinement}
                    disabled={contentLocked}
                    onChange={setRefinement}
                  />
                )}
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={save} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {isEdit ? t('common:actions.save') : t('common:actions.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
