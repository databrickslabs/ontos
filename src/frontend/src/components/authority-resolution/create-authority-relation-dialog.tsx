import { useState, useEffect } from 'react';
import { useTranslation, Trans } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import NativeSelect from '@/components/ui/native-select';
import DomainMultiSelector from '@/components/ui/domain-multi-selector';
import TagSelector from '@/components/ui/tag-selector';
import type { AssignedTag } from '@/components/ui/tag-chip';
import ClauseLabelsInput, { pruneClauseLabels } from '@/components/authority-resolution/clause-labels-input';
import ScheduleSelect from '@/components/authority-resolution/schedule-select';
import McpRefEditor from '@/components/authority-resolution/mcp-ref-editor';
import { InfoHint, SectionTitle } from '@/components/authority-resolution/info-hint';
import CriteriaBuilder, {
  hasInvalidWeight, rowsFromCriteria, rowsToPayload, type CriterionRow,
} from '@/components/authority-resolution/criteria-builder';
import DomainContextEditor, {
  paramRowsFrom, scopeRowsFrom, toDomainContext, type ParamRow, type ScopeRow,
} from '@/components/authority-resolution/domain-context-editor';
import RuleEditor, {
  itemsFromRule, ruleFromItems, type ItemDraft,
} from '@/components/authority-resolution/rule-editor';
import { authorityErrorMessage } from '@/components/authority-resolution/authority-errors';
import EvidenceSliceEditor from '@/components/authority-resolution/evidence-slice-editor';
import AdmFindingsList from '@/components/authority-resolution/adm-findings-list';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useApi } from '@/hooks/use-api';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { useTeams } from '@/hooks/use-teams';
import { useProjectContext } from '@/stores/project-store';
import { useToast } from '@/hooks/use-toast';
import { Plus, Trash2, Loader2 } from 'lucide-react';
import {
  ACTION_VOCAB, operandForKey, scopeKey,
  type AuthorityRelation, type AffirmationInput,
  type PrerequisiteInput, type AuthorityRelationSlug,
  type ResourceRefInput, type EntityRefCandidate, type ResolverAuth, type AuthorityPolicy,
  type AdmConformanceFinding, type AdmSchemaState, type EvidenceSliceDraft,
  ADM_SCHEMA_PATTERN, draftFromEvidenceSlice, evidenceSliceErrors, evidenceSliceFromDraft, newEvidenceSliceDraft,
} from '@/types/authority-resolution';
import type { BusinessRoleRead } from '@/types/business-role';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (created: AuthorityRelation) => void;
  /** When provided, the dialog edits this relation (PUT) instead of creating a new one. */
  relation?: AuthorityRelation | null;
  /** Opens the New Version action of the caller, offered when the definition is locked. */
  onNewVersion?: () => void;
}

// Participants start empty — the author adds them and picks an organizational
// Business Role (from Settings) per participant.
const DEFAULT_AFFIRMATIONS: AffirmationInput[] = [];

export default function CreateAuthorityRelationDialog({ open, onOpenChange, onCreated, relation, onNewVersion }: Props) {
  const { t } = useTranslation(['authority-resolution', 'common']);
  const { get, post, put } = useApi();
  const { toast } = useToast();
  const isEdit = !!relation;
  const [saving, setSaving] = useState(false);
  const [businessRoles, setBusinessRoles] = useState<BusinessRoleRead[]>([]);
  const [rolesLoading, setRolesLoading] = useState(false);
  const [slugsLoading, setSlugsLoading] = useState(false);
  // Keyed like refCandidates so one row's fetch doesn't skeleton the others.
  const [candidatesLoading, setCandidatesLoading] = useState<Record<string, boolean>>({});

  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [description, setDescription] = useState('');
  const [actorRole, setActorRole] = useState('');
  const [actorIdentity, setActorIdentity] = useState('');
  const [action, setAction] = useState('approve');
  const [objectType, setObjectType] = useState('data_product');
  const [objectId, setObjectId] = useState('');
  const [scopeRows, setScopeRows] = useState<ScopeRow[]>([]);
  const [paramRows, setParamRows] = useState<ParamRow[]>([]);
  const [ruleItems, setRuleItems] = useState<ItemDraft[]>([]);
  const [dnaMax, setDnaMax] = useState('0.3');
  const [criteriaRows, setCriteriaRows] = useState<CriterionRow[]>([]);
  const [evidenceDraft, setEvidenceDraft] = useState<EvidenceSliceDraft>(newEvidenceSliceDraft());
  // The per-AR ADM schema override (Admin-only to change), and the shared schema it falls back to.
  const [admOverride, setAdmOverride] = useState('');
  const [sharedAdmSchema, setSharedAdmSchema] = useState<string | null>(null);
  const [admFindings, setAdmFindings] = useState<AdmConformanceFinding[]>([]);
  const [domainIds, setDomainIds] = useState<string[]>([]);
  const [primaryDomainId, setPrimaryDomainId] = useState<string | null>(null);
  const [ownerTeamId, setOwnerTeamId] = useState('');
  const [projectId, setProjectId] = useState('');
  const { teams } = useTeams();
  const { currentProject, availableProjects, fetchUserProjects } = useProjectContext();
  const [affirmations, setAffirmations] = useState<AffirmationInput[]>(DEFAULT_AFFIRMATIONS);
  const [tags, setTags] = useState<(string | AssignedTag)[]>([]);
  const [scheduleCron, setScheduleCron] = useState<string | null>(null);
  const [prerequisites, setPrerequisites] = useState<PrerequisiteInput[]>([]);
  const [slugCatalog, setSlugCatalog] = useState<AuthorityRelationSlug[]>([]);
  const [resourceRefs, setResourceRefs] = useState<ResourceRefInput[]>([]);
  const [resolverAuth, setResolverAuth] = useState<ResolverAuth>('obo');
  const [policies, setPolicies] = useState<AuthorityPolicy[]>([]);
  const [policyId, setPolicyId] = useState('');
  const [clauseRefs, setClauseRefs] = useState<string[]>([]);
  // The DNA ceiling, the recompute schedule and the app service principal identity are Admin-only.
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const isAdmin = !permissionsLoading && hasPermission('authority-resolution', FeatureAccessLevel.ADMIN);
  // Active and earlier versions are immutable: the definition is read-only, metadata stays editable.
  const locked = isEdit && relation?.editable === false;
  // Empty keeps the 0.3 default; otherwise the ceiling must be within [0, 1].
  const [dnaServerError, setDnaServerError] = useState(false);
  const dnaMaxNumber = dnaMax.trim() === '' ? 0.3 : Number(dnaMax);
  const dnaMaxValid = Number.isFinite(dnaMaxNumber) && dnaMaxNumber >= 0 && dnaMaxNumber <= 1;
  const dnaMaxError = !dnaMaxValid || dnaServerError;
  // Picker catalog, keyed by (entity_type, search-term). The dialog debounces
  // searches per row so the picker stays cheap even with 100s of concepts.
  const [refCandidates, setRefCandidates] = useState<Record<string, EntityRefCandidate[]>>({});

  const reset = () => {
    setName(''); setSlug(''); setDescription(''); setActorRole(''); setActorIdentity('');
    setAction('approve'); setObjectType('data_product'); setObjectId('');
    setScopeRows([]); setParamRows([]); setRuleItems([]); setDnaMax('0.3'); setCriteriaRows([]);
    setEvidenceDraft(newEvidenceSliceDraft()); setAdmOverride(''); setAdmFindings([]);
    setDomainIds([]); setPrimaryDomainId(null);
    setOwnerTeamId(''); setProjectId(currentProject?.id || '');
    setAffirmations(DEFAULT_AFFIRMATIONS); setTags([]); setScheduleCron(null);
    setPrerequisites([]); setResourceRefs([]); setResolverAuth('obo');
    setPolicyId(''); setClauseRefs([]);
  };

  // Load active Business Roles for the participant role picker (Settings feature).
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      setRolesLoading(true);
      const { data } = await get<BusinessRoleRead[]>('/api/business-roles?role_status=active');
      if (!cancelled) {
        if (Array.isArray(data)) setBusinessRoles(data.filter((r) => r.status === 'active'));
        setRolesLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open, get]);

  // Load the catalog of AR family slugs for the Requires picker.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      setSlugsLoading(true);
      const { data } = await get<AuthorityRelationSlug[]>('/api/authority/relation-slugs');
      if (!cancelled) {
        if (Array.isArray(data)) setSlugCatalog(data);
        setSlugsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open, get]);

  // Every reference version (an AR cites an exact version), for the Justification picker.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      const { data } = await get<AuthorityPolicy[]>('/api/authority/policies?include_history=true');
      if (!cancelled && Array.isArray(data)) setPolicies(data);
    })();
    return () => { cancelled = true; };
  }, [open, get]);

  // The shared ADM schema: the default every AR reads unless it overrides it.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      const { data } = await get<AdmSchemaState>('/api/authority/adm-schema');
      if (!cancelled) setSharedAdmSchema(typeof data?.schema === 'string' ? data.schema : null);
    })();
    return () => { cancelled = true; };
  }, [open, get]);

  // Projects the user can assign (same source as the Data Product dialog).
  useEffect(() => {
    if (open) fetchUserProjects();
  }, [open, fetchUserProjects]);

  // Prefill from the relation when editing; reset to defaults when creating.
  // Keyed on `open` so reopening the dialog re-syncs from the latest data.
  useEffect(() => {
    if (!open) return;
    if (relation) {
      setName(relation.name || '');
      setSlug(relation.slug || '');
      setDescription(relation.description || '');
      setActorRole(relation.actor_role || '');
      setActorIdentity(relation.actor_identity || '');
      setAction(relation.action || 'approve');
      setObjectType(relation.object_type || 'data_product');
      setObjectId(relation.object_id || '');
      setScopeRows(scopeRowsFrom(relation.domain_context));
      setParamRows(paramRowsFrom(relation.domain_context));
      setRuleItems(itemsFromRule(relation.rule));
      setDnaMax(relation.dna_max_threshold != null ? String(relation.dna_max_threshold) : '0.3');
      setCriteriaRows(rowsFromCriteria(relation.criteria));
      setEvidenceDraft(relation.evidence_slice
        ? draftFromEvidenceSlice(relation.evidence_slice)
        : newEvidenceSliceDraft(relation.action || 'approve'));
      setAdmOverride(relation.adm_schema_override || '');
      setAdmFindings([]);
      setDomainIds((relation.domains || []).map((d) => d.domain_id));
      setPrimaryDomainId((relation.domains || []).find((d) => d.is_primary)?.domain_id ?? null);
      setOwnerTeamId(relation.owner_team_id || '');
      setProjectId(relation.project_id || '');
      setAffirmations(
        (relation.affirmations || []).length
          ? (relation.affirmations || []).map((a) => ({
              role: a.role,
              business_role_id: a.business_role_id ?? undefined,
              role_category: a.role_category ?? undefined,
              principal: a.principal,
              principal_type: a.principal_type,
              required: a.required,
              is_approver: a.is_approver ?? true,
              is_reviewer: a.is_reviewer ?? false,
            }))
          : DEFAULT_AFFIRMATIONS,
      );
      setTags((relation.tags || []).map((t) => t.fully_qualified_name).filter(Boolean) as string[]);
      setScheduleCron(relation.schedule_cron ?? null);
      setResolverAuth(relation.resolver_auth ?? 'obo');
      setPolicyId(relation.authority_policy_id || '');
      setClauseRefs(relation.policy_clause_refs || []);
      setPrerequisites(
        (relation.prerequisites || []).map((p) => ({
          prerequisite_family_slug: p.prerequisite_family_slug,
          required: p.required,
          display_order: p.display_order,
          notes: p.notes ?? null,
        })),
      );
      setResourceRefs(
        (relation.resource_refs || []).map((r) => ({
          field_path: r.field_path,
          ref_type: r.ref_type,
          literal_value: r.literal_value ?? null,
          entity_type: r.entity_type ?? null,
          entity_id: r.entity_id ?? null,
          mcp_service_name: r.mcp_service_name ?? null,
          mcp_tool_name: r.mcp_tool_name ?? null,
          mcp_params: r.mcp_params ?? null,
          mcp_result_pointer: r.mcp_result_pointer ?? null,
        })),
      );
    } else {
      reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, relation]);

  // The context as authored so far (for the rule editor's validation and the
  // checks' variables); invalid rows leave it undefined until fixed.
  const draftContext = toDomainContext(scopeRows, paramRows);
  const citedPolicy = policies.find((p) => p.id === policyId);
  // The reference's clause labels are suggestions only: a clause is free text on the AR.
  const policyClauses = citedPolicy?.clauses || [];
  const policyOptions = [...policies].sort((a, b) =>
    a.policy_key.localeCompare(b.policy_key) || b.version.localeCompare(a.version, undefined, { numeric: true }));
  // Choosing another reference (or none) prunes the clause labels it doesn't suggest, from the
  // AR, its rule items and its checks: a label is only meaningful against the reference it was chosen for.
  const choosePolicy = (id: string) => {
    setPolicyId(id);
    const refs = (policies.find((p) => p.id === id)?.clauses || []).map((c) => c.ref);
    setClauseRefs((prev) => pruneClauseLabels(prev, refs));
    setRuleItems((prev) => prev.map((it) => (it.clause && !refs.includes(it.clause) ? { ...it, clause: '' } : it)));
    setCriteriaRows((prev) => prev.map((r) => (r.clauseRef && !refs.includes(r.clauseRef) ? { ...r, clauseRef: '' } : r)));
  };

  const updateAffirmation = (idx: number, patch: Partial<AffirmationInput>) => {
    setAffirmations((prev) => prev.map((a, i) => (i === idx ? { ...a, ...patch } : a)));
  };

  const handleSubmit = async () => {
    if (!name.trim()) {
      toast({ title: t('editor.validation.nameRequired'), variant: 'destructive' });
      return;
    }

    // Incomplete participant rows (one field filled, the other blank) used to
    // be silently filtered out — the dialog closed with a success toast while
    // the half-authored affirmation was dropped. Surface it instead; a fully
    // empty row still drops silently (it's the "I added a row by accident"
    // escape hatch).
    for (let i = 0; i < affirmations.length; i++) {
      const a = affirmations[i];
      const hasPrincipal = !!a.principal.trim();
      const hasRole = !!a.role;
      if (hasPrincipal && !hasRole) {
        toast({
          title: t('editor.affirmations.validation.roleRequired', { index: i + 1 }),
          description: t('editor.affirmations.validation.roleRequiredDescription'),
          variant: 'destructive',
        });
        return;
      }
      if (hasRole && !hasPrincipal) {
        toast({
          title: t('editor.affirmations.validation.principalRequired', { index: i + 1 }),
          description: t('editor.affirmations.validation.principalRequiredDescription'),
          variant: 'destructive',
        });
        return;
      }
    }

    if (hasInvalidWeight(criteriaRows)) {
      toast({ title: t('criteria.errors.weightInvalid'), variant: 'destructive' });
      return;
    }
    if (!dnaMaxValid) {
      toast({ title: t('errors.dnaMaxRange'), variant: 'destructive' });
      return;
    }

    if (evidenceSliceErrors(evidenceDraft).length > 0) {
      toast({ title: t('editor.evidenceSlice.invalidToast'), variant: 'destructive' });
      return;
    }
    const override = admOverride.trim();
    if (override && !ADM_SCHEMA_PATTERN.test(override)) {
      toast({ title: t('editor.admSchema.invalidFormat'), variant: 'destructive' });
      return;
    }
    // The override is Admin-only on the server: a non-admin sends the stored value back unchanged.
    const admOverridePayload = isAdmin ? (override || null) : (relation?.adm_schema_override ?? null);

    const dc = toDomainContext(scopeRows, paramRows);
    if (dc.error) {
      toast({ title: t('domainContext.validation.title'), description: t(dc.error.key, { key: dc.error.field }), variant: 'destructive' });
      return;
    }
    let rule;
    try {
      rule = ruleFromItems(ruleItems);
    } catch {
      toast({ title: t('rule.validation.title'), description: t('rule.validation.badJson'), variant: 'destructive' });
      return;
    }

    const payload = {
      name: name.trim(),
      slug: slug.trim() || undefined,
      description: description.trim() || undefined,
      actor_role: actorRole.trim() || undefined,
      actor_identity: actorIdentity.trim() || undefined,
      action,
      object_type: objectType.trim() || undefined,
      object_id: objectId.trim() || undefined,
      domain_context: dc.value,
      rule,
      authority_policy_id: policyId || null,
      policy_clause_refs: policyId ? clauseRefs : [],
      criteria: rowsToPayload(criteriaRows),
      evidence_slice: evidenceSliceFromDraft(evidenceDraft),
      adm_schema_override: admOverridePayload,
      dna_max_threshold: dnaMaxNumber,
      domain_ids: domainIds,
      primary_domain_id: primaryDomainId,
      owner_team_id: ownerTeamId,
      project_id: projectId,
      affirmations: affirmations.filter((a) => a.principal.trim() && a.role),
      tags: tags.map((t) => ({ tag_fqn: typeof t === 'string' ? t : t.fully_qualified_name })),
      schedule_cron: scheduleCron,
      resolver_auth: resolverAuth,
      prerequisites: prerequisites
        .filter((p) => p.prerequisite_family_slug.trim())
        .map((p, idx) => ({ ...p, display_order: idx })),
      // Typed resource refs. Drop rows whose field_path is empty or whose
      // chosen branch is incomplete; the backend validates the rest and
      // raises a 400 the toast will surface.
      resource_refs: resourceRefs
        .filter((r) => r.field_path.trim())
        .filter((r) =>
          r.ref_type === 'literal'
            ? (r.literal_value ?? '').length > 0
            : r.ref_type === 'ontos_entity'
            ? !!r.entity_type && !!r.entity_id
            : r.ref_type === 'mcp_tool'
            ? !!r.mcp_service_name && !!r.mcp_tool_name
            : false,
        ),
    };

    setSaving(true);
    const { data, error, errorCode, errorParams, status } = isEdit
      ? await put<AuthorityRelation>(`/api/authority/relations/${relation!.id}`, payload)
      : await post<AuthorityRelation>('/api/authority/relations', payload);
    setSaving(false);
    if (error) {
      // Pydantic bounds error on dna_max_threshold: show it on the field.
      if (status === 422 && /dna_max_threshold/.test(error)) setDnaServerError(true);
      // A non-conformant ADM schema override is refused with its findings: list them under the field.
      if (errorCode === 'adm_nonconformant') {
        const findings = errorParams?.findings;
        setAdmFindings(Array.isArray(findings) ? findings as AdmConformanceFinding[] : []);
      }
      toast({ title: t('common:toast.failed'), description: authorityErrorMessage(t, error, errorCode, errorParams), variant: 'destructive' });
      return;
    }
    if (!isEdit) reset();
    onCreated(data);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEdit ? t('editor.title.edit') : t('editor.title.new')}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {locked && (
            <Alert>
              <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                <span>{t('editor.immutableNotice')}</span>
                {onNewVersion && (
                  <Button variant="outline" size="sm" onClick={onNewVersion}>{t('details.buttonNewVersion')}</Button>
                )}
              </AlertDescription>
            </Alert>
          )}
          <fieldset disabled={locked} className="min-w-0 border-0 p-0 m-0">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('editor.labels.name')} *</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('editor.fields.name.placeholder')} />
            </div>
            <div className="space-y-1">
              <Label className="flex items-center gap-1.5">{t('editor.labels.slug')} <InfoHint>{t('editor.hints.slug')}</InfoHint></Label>
              <Input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder={t('editor.fields.slug.placeholder')} />
            </div>
          </div>
          </fieldset>

          <div className="space-y-1">
            <Label>{t('editor.labels.description')}</Label>
            <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
          </div>

          <fieldset disabled={locked} className="min-w-0 space-y-4 border-0 p-0 m-0">
          <SectionTitle title={t('editor.sections.authorityRelation')} info={<Trans i18nKey="editor.hints.authorityRelation" ns="authority-resolution" components={{ strong: <strong />, }} />} />
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('editor.labels.actorRole')}</Label>
              <Input value={actorRole} onChange={(e) => setActorRole(e.target.value)} placeholder={t('editor.fields.actorRole.placeholder')} />
            </div>
            <div className="space-y-1">
              <Label>{t('editor.labels.actorIdentity')}</Label>
              <Input value={actorIdentity} onChange={(e) => setActorIdentity(e.target.value)} placeholder={t('editor.fields.actorIdentity.placeholder')} />
            </div>
            <div className="space-y-1">
              <Label>{t('editor.labels.action')}</Label>
              <NativeSelect value={action} onChange={(e) => setAction(e.target.value)}>
                {ACTION_VOCAB.map((a) => <option key={a} value={a}>{t(`editor.actions.${a}`, { defaultValue: a })}</option>)}
              </NativeSelect>
            </div>
            <div className="space-y-1">
              <Label>{t('editor.labels.objectType')}</Label>
              <Input value={objectType} onChange={(e) => setObjectType(e.target.value)} placeholder={t('editor.fields.objectType.placeholder')} />
            </div>
            <div className="space-y-1">
              <Label>{t('editor.labels.objectId')}</Label>
              <Input value={objectId} onChange={(e) => setObjectId(e.target.value)} placeholder={t('editor.fields.objectId.placeholder')} />
            </div>
          </div>

          <SectionTitle title={t('editor.sections.domainContext')} info={t('editor.sectionDescriptions.domainContext')} />
          <DomainContextEditor scope={scopeRows} params={paramRows} onScopeChange={setScopeRows} onParamsChange={setParamRows} />

          <SectionTitle title={t('editor.sections.justification')} info={t('editor.sectionDescriptions.justification')} />
          <div className="space-y-2">
            <NativeSelect value={policyId} onChange={(e) => choosePolicy(e.target.value)}>
              <option value="">{t('policy.citation.nonePicker')}</option>
              {policyOptions.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.policy_key} v{p.version} — {p.title}{p.expired ? ` (${t('policy.validity.expired')})` : ''}
                </option>
              ))}
            </NativeSelect>
            {citedPolicy?.expired && (
              <p className="text-xs text-amber-600">{t('policy.citation.expiredHint')}</p>
            )}
            {policyId && (
              <ClauseLabelsInput value={clauseRefs} onChange={setClauseRefs} suggestions={policyClauses} />
            )}
          </div>

          <SectionTitle
            title={t('editor.sections.rule')}
            info={<Trans i18nKey="editor.sectionDescriptions.rule" ns="authority-resolution" components={{ strong: <strong />, code: <code /> }} />}
          />
          <RuleEditor
            items={ruleItems}
            onChange={setRuleItems}
            paramKeys={paramRows.map((p) => p.key.trim())}
            scopeKeys={scopeRows.map((r) => scopeKey(operandForKey(r.key)))}
            domainContext={draftContext.value}
            clauses={policyClauses}
            citable={!!policyId}
          />

          <SectionTitle
            title={t('editor.sections.decisionCriteria')}
            info={<Trans i18nKey="editor.sectionDescriptions.decisionCriteria" ns="authority-resolution" components={{ strong: <strong />, }} />}
          />
          <CriteriaBuilder
            rows={criteriaRows}
            onChange={setCriteriaRows}
            params={draftContext.value?.params}
            scopeKeys={scopeRows.map((r) => scopeKey(operandForKey(r.key)))}
            clauses={policyClauses}
            citable={!!policyId}
            readOnly={locked}
          />
          </fieldset>

          <div className="text-sm font-semibold text-muted-foreground pt-2">{t('editor.sections.domains')}</div>
          <DomainMultiSelector
            value={domainIds}
            primaryDomainId={primaryDomainId}
            onChange={(ids, primary) => { setDomainIds(ids); setPrimaryDomainId(primary); }}
          />

          <div className="text-sm font-semibold text-muted-foreground pt-2">{t('editor.sections.ownership')}</div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('editor.fields.ownerTeam')}</Label>
              <NativeSelect value={ownerTeamId} onChange={(e) => setOwnerTeamId(e.target.value)}>
                <option value="">{t('editor.fields.noTeam')}</option>
                {teams.map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}
              </NativeSelect>
            </div>
            <div className="space-y-1">
              <Label>{t('editor.fields.project')}</Label>
              <NativeSelect value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                <option value="">{t('editor.fields.noProject')}</option>
                {availableProjects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </NativeSelect>
            </div>
          </div>

          <fieldset disabled={locked} className="min-w-0 space-y-4 border-0 p-0 m-0">
          <SectionTitle
            title={t('editor.sections.evidenceSlice')}
            info={<Trans i18nKey="editor.sectionDescriptions.evidenceSlice" ns="authority-resolution" components={{ strong: <strong />, }} />}
          />
          <EvidenceSliceEditor value={evidenceDraft} onChange={setEvidenceDraft} />

          <SectionTitle
            title={t('editor.sections.admSchema')}
            info={<Trans i18nKey="editor.sectionDescriptions.admSchema" ns="authority-resolution" components={{ strong: <strong />, }} />}
          />
          <div className="space-y-1">
            <Label htmlFor="adm-schema-override">{t('editor.labels.admSchemaOverride')}</Label>
            <Input
              id="adm-schema-override"
              className="max-w-md font-mono"
              value={isAdmin ? admOverride : (relation?.adm_schema ?? sharedAdmSchema ?? '')}
              disabled={!isAdmin}
              aria-invalid={(isAdmin && admOverride.trim() !== '' && !ADM_SCHEMA_PATTERN.test(admOverride.trim())) || undefined}
              placeholder={t('editor.admSchema.placeholder')}
              onChange={(e) => { setAdmOverride(e.target.value); setAdmFindings([]); }}
            />
            <p className="text-xs text-muted-foreground">
              {sharedAdmSchema
                ? t('editor.admSchema.shared', { schema: sharedAdmSchema })
                : t('editor.admSchema.sharedNotConfigured')}
            </p>
            {!isAdmin && <p className="text-xs text-muted-foreground">{t('editor.admSchema.adminOnly')}</p>}
            {isAdmin && admOverride.trim() !== '' && !ADM_SCHEMA_PATTERN.test(admOverride.trim()) && (
              <p className="text-xs text-destructive">{t('editor.admSchema.invalidFormat')}</p>
            )}
            {admFindings.length > 0 && (
              <div className="space-y-2 pt-1">
                <p className="text-xs text-destructive">{t('editor.admSchema.nonconformant')}</p>
                <AdmFindingsList findings={admFindings} />
              </div>
            )}
          </div>

          <SectionTitle
            title={t('editor.sections.participants')}
            info={<Trans i18nKey="editor.sectionDescriptions.participants" ns="authority-resolution" components={{ strong: <strong />, }} />}
          />
          {rolesLoading ? (
            <Skeleton className="h-9 w-full" />
          ) : null}
          {affirmations.map((a, idx) => {
            // Flag the empty field on a half-authored row so the author sees
            // *which* field is missing without having to re-read the toast.
            const hasPrincipal = !!a.principal.trim();
            const hasRole = !!a.role;
            const roleMissing = hasPrincipal && !hasRole;
            const principalMissing = hasRole && !hasPrincipal;
            return (
            <div key={idx} className="grid grid-cols-[1fr_1.5fr_auto] gap-2 items-center">
              <NativeSelect
                value={a.business_role_id || ''}
                aria-invalid={roleMissing || undefined}
                selectClassName={roleMissing ? 'border-destructive focus:ring-destructive' : undefined}
                onChange={(e) => {
                  const br = businessRoles.find((r) => r.id === e.target.value);
                  updateAffirmation(idx, {
                    business_role_id: br?.id,
                    role: br?.name || '',
                    role_category: br?.category || undefined,
                  });
                }}
              >
                <option value="">{t('editor.affirmations.selectRoleLabel')}</option>
                {businessRoles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                {a.business_role_id && !businessRoles.some((r) => r.id === a.business_role_id) && (
                  <option value={a.business_role_id}>{a.role || a.business_role_id}</option>
                )}
              </NativeSelect>
              <Input
                value={a.principal}
                aria-invalid={principalMissing || undefined}
                className={principalMissing ? 'border-destructive focus-visible:ring-destructive' : undefined}
                onChange={(e) => updateAffirmation(idx, { principal: e.target.value })}
                placeholder={t('editor.affirmations.principalPlaceholder')}
              />
              <div className="flex items-center gap-3">
                <NativeSelect
                  className="w-28"
                  value={a.principal_type}
                  onChange={(e) => updateAffirmation(idx, { principal_type: e.target.value })}
                >
                  <option value="user">{t('editor.affirmations.principalTypeUser')}</option>
                  <option value="group">{t('editor.affirmations.principalTypeGroup')}</option>
                </NativeSelect>
                <label className="flex items-center gap-1 text-xs whitespace-nowrap">
                  <input type="checkbox" checked={a.is_approver ?? true}
                    onChange={(e) => updateAffirmation(idx, { is_approver: e.target.checked })} /> {t('editor.affirmations.approverLabel')}
                </label>
                <label className="flex items-center gap-1 text-xs whitespace-nowrap">
                  <input type="checkbox" checked={a.is_reviewer ?? false}
                    onChange={(e) => updateAffirmation(idx, { is_reviewer: e.target.checked })} /> {t('editor.affirmations.reviewerLabel')}
                </label>
                <Button variant="ghost" size="icon" onClick={() => setAffirmations((prev) => prev.filter((_, i) => i !== idx))}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
            );
          })}
          <Button
            variant="outline" size="sm"
            onClick={() => setAffirmations((prev) => [...prev, { role: '', principal: '', principal_type: 'user', required: true, is_approver: true, is_reviewer: false }])}
          >
            <Plus className="h-4 w-4 mr-1" /> {t('editor.buttons.addParticipant')}
          </Button>

          <SectionTitle
            title={t('editor.sections.requires')}
            info={<Trans i18nKey="editor.sectionDescriptions.requires" ns="authority-resolution" components={{ strong: <strong />, }} />}
          />
          {slugsLoading ? (
            <Skeleton className="h-9 w-full" />
          ) : null}
          {prerequisites.map((p, idx) => {
            // Avoid offering the current AR (edit mode) or any already-picked slug.
            const takenSlugs = new Set(prerequisites.filter((_, j) => j !== idx).map((q) => q.prerequisite_family_slug));
            const selfSlug = relation?.family_slug || relation?.slug || slug.trim();
            if (selfSlug) takenSlugs.add(selfSlug);
            return (
              <div key={idx} className="grid grid-cols-[1.5fr_auto_1fr_auto] gap-2 items-center">
                <NativeSelect
                  value={p.prerequisite_family_slug}
                  onChange={(e) =>
                    setPrerequisites((prev) => prev.map((x, i) => (i === idx ? { ...x, prerequisite_family_slug: e.target.value } : x)))
                  }
                >
                  <option value="">{t('editor.prerequisites.selectPrerequisiteLabel')}</option>
                  {slugCatalog
                    .filter((s) => !takenSlugs.has(s.family_slug) || s.family_slug === p.prerequisite_family_slug)
                    .map((s) => (
                      <option key={s.family_slug} value={s.family_slug}>
                        {s.name} ({s.family_slug}) — {t(`status.${s.status}`, { defaultValue: s.status })}
                      </option>
                    ))}
                </NativeSelect>
                <label className="flex items-center gap-1 text-xs whitespace-nowrap">
                  <input
                    type="checkbox"
                    checked={p.required}
                    onChange={(e) =>
                      setPrerequisites((prev) => prev.map((x, i) => (i === idx ? { ...x, required: e.target.checked } : x)))
                    }
                  />
                  {t('editor.prerequisites.requiredLabel')}
                </label>
                <Input
                  value={p.notes || ''}
                  onChange={(e) =>
                    setPrerequisites((prev) => prev.map((x, i) => (i === idx ? { ...x, notes: e.target.value } : x)))
                  }
                  placeholder={t('editor.prerequisites.notePlaceholder')}
                />
                <Button variant="ghost" size="icon" onClick={() => setPrerequisites((prev) => prev.filter((_, i) => i !== idx))}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            );
          })}
          <Button
            variant="outline" size="sm"
            onClick={() =>
              setPrerequisites((prev) => [
                ...prev,
                { prerequisite_family_slug: '', required: true, display_order: prev.length, notes: null },
              ])
            }
          >
            <Plus className="h-4 w-4 mr-1" /> {t('editor.buttons.addPrerequisite')}
          </Button>

          <SectionTitle
            title={t('editor.sections.resourceRefs')}
            info={<Trans i18nKey="editor.sectionDescriptions.resourceRefs" ns="authority-resolution" values={{ keyPlaceholder: '<key>', fieldPlaceholder: '<field_path>' }} shouldUnescape components={{ strong: <strong />, code: <code /> }} />}
          />
          {resourceRefs.map((r, idx) => {
            const candidateKey = `${r.entity_type || ''}::${idx}`;
            const candidates = refCandidates[candidateKey] || [];
            return (
              <div key={idx} className="rounded-md border p-3 space-y-2">
                <div className="grid grid-cols-[1fr_auto_auto] gap-2 items-center">
                  <Input
                    value={r.field_path}
                    onChange={(e) =>
                      setResourceRefs((prev) =>
                        prev.map((x, i) => (i === idx ? { ...x, field_path: e.target.value } : x)),
                      )
                    }
                    placeholder={t('editor.resourceRefs.fieldPathPlaceholder')}
                  />
                  <NativeSelect
                    className="w-44"
                    value={r.ref_type}
                    onChange={(e) =>
                      setResourceRefs((prev) =>
                        prev.map((x, i) =>
                          i === idx
                            ? {
                                ...x,
                                ref_type: e.target.value as ResourceRefInput['ref_type'],
                                // Reset branch-specific fields on type switch so stale
                                // state doesn't travel across changes.
                                literal_value: null,
                                entity_type: null,
                                entity_id: null,
                                mcp_service_name: null,
                                mcp_tool_name: null,
                                mcp_params: null,
                                mcp_result_pointer: null,
                              }
                            : x,
                        ),
                      )
                    }
                  >
                    <option value="literal">{t('editor.resourceRefs.refType.literal')}</option>
                    <option value="ontos_entity">{t('editor.resourceRefs.refType.ontosEntity')}</option>
                    <option value="mcp_tool">{t('editor.resourceRefs.refType.mcpTool')}</option>
                  </NativeSelect>
                  <Button
                    variant="ghost" size="icon"
                    onClick={() => setResourceRefs((prev) => prev.filter((_, i) => i !== idx))}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
                {r.ref_type === 'literal' && (
                  <Input
                    value={r.literal_value || ''}
                    onChange={(e) =>
                      setResourceRefs((prev) =>
                        prev.map((x, i) => (i === idx ? { ...x, literal_value: e.target.value } : x)),
                      )
                    }
                    placeholder={t('editor.resourceRefs.literalPlaceholder')}
                  />
                )}
                {r.ref_type === 'mcp_tool' && (
                  <McpRefEditor
                    value={r}
                    onChange={(patch) =>
                      setResourceRefs((prev) => prev.map((x, i) => (i === idx ? { ...x, ...patch } : x)))
                    }
                  />
                )}
                {r.ref_type === 'ontos_entity' && (
                  <div className="grid grid-cols-[auto_1fr] gap-2 items-center">
                    {candidatesLoading[candidateKey] ? (
                      <Skeleton className="h-9 w-full" />
                    ) : (
                      <NativeSelect
                        className="w-40"
                        value={r.entity_type || ''}
                        onChange={async (e) => {
                          const entity_type = e.target.value || null;
                          setResourceRefs((prev) =>
                            prev.map((x, i) =>
                              i === idx ? { ...x, entity_type, entity_id: null } : x,
                            ),
                          );
                          if (entity_type) {
                            const key = `${entity_type}::${idx}`;
                            setCandidatesLoading((prev) => ({ ...prev, [key]: true }));
                            try {
                              const { data } = await get<EntityRefCandidate[]>(
                                `/api/authority/entity-ref-candidates?entity_type=${entity_type}&limit=100`,
                              );
                              if (Array.isArray(data)) {
                                setRefCandidates((prev) => ({ ...prev, [key]: data }));
                              }
                            } finally {
                              setCandidatesLoading((prev) => ({ ...prev, [key]: false }));
                            }
                          }
                        }}
                      >
                        <option value="">{t('editor.resourceRefs.entityTypePlaceholder')}</option>
                        <option value="business_concept">{t('editor.resourceRefs.entityType.businessConcept')}</option>
                        <option value="data_product">{t('editor.resourceRefs.entityType.dataProduct')}</option>
                        <option value="data_domain">{t('editor.resourceRefs.entityType.dataDomain')}</option>
                      </NativeSelect>
                    )}
                    {candidatesLoading[candidateKey] ? (
                      <Skeleton className="h-9 w-full" />
                    ) : (
                      <NativeSelect
                        value={r.entity_id || ''}
                        onChange={(e) =>
                          setResourceRefs((prev) =>
                            prev.map((x, i) => (i === idx ? { ...x, entity_id: e.target.value } : x)),
                          )
                        }
                        disabled={!r.entity_type}
                      >
                        <option value="">
                          {r.entity_type ? t('editor.resourceRefs.entityIdPlaceholder') : t('editor.resourceRefs.entityIdDisabledPlaceholder')}
                        </option>
                        {candidates.map((c) => (
                          <option key={c.entity_id} value={c.entity_id}>
                            {c.label}
                          </option>
                        ))}
                        {/* Preserve the current pick when it isn't in the fetched slice. */}
                        {r.entity_id && !candidates.some((c) => c.entity_id === r.entity_id) && (
                          <option value={r.entity_id}>{r.entity_id}</option>
                        )}
                      </NativeSelect>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          <Button
            variant="outline" size="sm"
            onClick={() =>
              setResourceRefs((prev) => [
                ...prev,
                { field_path: '', ref_type: 'literal', literal_value: '' },
              ])
            }
          >
            <Plus className="h-4 w-4 mr-1" /> {t('editor.buttons.addResourceRef')}
          </Button>
          {resourceRefs.some((r) => r.ref_type === 'mcp_tool') && (
            <div className="space-y-1">
              <Label className="flex items-center gap-1.5">
                {t('editor.sections.mcpResolverCredentials')}
                <InfoHint>
                  <Trans i18nKey="editor.hints.mcpResolverCredentials" ns="authority-resolution" components={{ strong: <strong />, }} />
                </InfoHint>
              </Label>
              <NativeSelect
                className="max-w-sm"
                value={resolverAuth}
                onChange={(e) => setResolverAuth(e.target.value as ResolverAuth)}
              >
                <option value="obo">{t('editor.mcpResolverAuth.obo')}</option>
                <option value="app_sp" disabled={!isAdmin}>{t('editor.mcpResolverAuth.appServicePrincipal')}</option>
              </NativeSelect>
            </div>
          )}

          <SectionTitle title={t('editor.sections.dnaSchedule')} info={t('editor.sectionDescriptions.dnaSchedule')} />
          <fieldset disabled={!isAdmin} className="contents">
            <ScheduleSelect value={scheduleCron} onChange={setScheduleCron} />
          </fieldset>
          </fieldset>

          <SectionTitle title={t('editor.sections.tags')} />
          <TagSelector value={tags} onChange={setTags} placeholder={t('common:actions.search')} />

          <div className="space-y-1 pt-2">
            <Label className="flex items-center gap-1.5">
              {t('editor.labels.dnaMaxThreshold')}
              <InfoHint>
                <Trans i18nKey="editor.hints.dnaMaxThreshold" ns="authority-resolution" components={{ strong: <strong />, }} />
              </InfoHint>
            </Label>
            <Input
              value={dnaMax}
              onChange={(e) => { setDnaMax(e.target.value); setDnaServerError(false); }}
              disabled={!isAdmin || locked}
              aria-invalid={dnaMaxError || undefined}
              placeholder={t('editor.fields.dnaMaxThreshold.placeholder')}
              className="max-w-[200px]"
            />
            {dnaMaxError && <p className="text-xs text-destructive">{t('errors.dnaMaxRange')}</p>}
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>{t('common:actions.cancel')}</Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            {isEdit ? t('common:actions.save') : t('common:actions.create')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
