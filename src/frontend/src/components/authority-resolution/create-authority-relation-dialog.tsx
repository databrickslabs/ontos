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
import ScheduleSelect from '@/components/authority-resolution/schedule-select';
import McpRefEditor from '@/components/authority-resolution/mcp-ref-editor';
import { InfoHint, SectionTitle } from '@/components/authority-resolution/info-hint';
import CriteriaBuilder, {
  rowsFromCriteria, rowsToPayload, type CriterionRow,
} from '@/components/authority-resolution/criteria-builder';
import { useApi } from '@/hooks/use-api';
import { useTeams } from '@/hooks/use-teams';
import { useProjectContext } from '@/stores/project-store';
import { useToast } from '@/hooks/use-toast';
import { Plus, Trash2, Loader2 } from 'lucide-react';
import {
  ACTION_VOCAB,
  type AuthorityRelation, type AffirmationInput,
  type PrerequisiteInput, type AuthorityRelationSlug,
  type ResourceRefInput, type EntityRefCandidate, type ResolverAuth,
} from '@/types/authority-resolution';
import type { BusinessRoleRead } from '@/types/business-role';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (created: AuthorityRelation) => void;
  /** When provided, the dialog edits this relation (PUT) instead of creating a new one. */
  relation?: AuthorityRelation | null;
}

const DEFAULT_COLUMN_MAP = `{
  "actor_identity": "approver",
  "action": "action",
  "value": "discount",
  "escalated": "escalated",
  "cosign_present": "cosign",
  "object_id": "promo_id"
}`;

// Participants start empty — the author adds them and picks an organizational
// Business Role (from Settings) per participant.
const DEFAULT_AFFIRMATIONS: AffirmationInput[] = [];

interface EvidenceSourceInput {
  type: string;      // delta_table | data_product | asset
  ref: string;       // table FQN / data product id / asset FQN
  label: string;
  columnMap: string; // JSON text
}

const newEvidenceSource = (): EvidenceSourceInput => ({
  type: 'delta_table', ref: '', label: '', columnMap: DEFAULT_COLUMN_MAP,
});

export default function CreateAuthorityRelationDialog({ open, onOpenChange, onCreated, relation }: Props) {
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
  const [threshold, setThreshold] = useState('');
  const [currency, setCurrency] = useState('');
  const [market, setMarket] = useState('');
  const [dnaMax, setDnaMax] = useState('0.3');
  const [criteriaRows, setCriteriaRows] = useState<CriterionRow[]>([]);
  const [evidenceSources, setEvidenceSources] = useState<EvidenceSourceInput[]>([]);
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
  // Picker catalog, keyed by (entity_type, search-term). The dialog debounces
  // searches per row so the picker stays cheap even with 100s of concepts.
  const [refCandidates, setRefCandidates] = useState<Record<string, EntityRefCandidate[]>>({});

  const reset = () => {
    setName(''); setSlug(''); setDescription(''); setActorRole(''); setActorIdentity('');
    setAction('approve'); setObjectType('data_product'); setObjectId(''); setThreshold('');
    setCurrency(''); setMarket(''); setDnaMax('0.3'); setCriteriaRows([]);
    setEvidenceSources([]); setDomainIds([]); setPrimaryDomainId(null);
    setOwnerTeamId(''); setProjectId(currentProject?.id || '');
    setAffirmations(DEFAULT_AFFIRMATIONS); setTags([]); setScheduleCron(null);
    setPrerequisites([]); setResourceRefs([]); setResolverAuth('obo');
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

  // Projects the user can assign (same source as the Data Product dialog).
  useEffect(() => {
    if (open) fetchUserProjects();
  }, [open, fetchUserProjects]);

  // Prefill from the relation when editing; reset to defaults when creating.
  // Keyed on `open` so reopening the dialog re-syncs from the latest data.
  useEffect(() => {
    if (!open) return;
    if (relation) {
      const dc = relation.domain_context || {};
      const eb = relation.evidence_binding || null;
      setName(relation.name || '');
      setSlug(relation.slug || '');
      setDescription(relation.description || '');
      setActorRole(relation.actor_role || '');
      setActorIdentity(relation.actor_identity || '');
      setAction(relation.action || 'approve');
      setObjectType(relation.object_type || 'data_product');
      setObjectId(relation.object_id || '');
      setThreshold(dc.threshold != null ? String(dc.threshold) : '');
      setCurrency(dc.currency || '');
      setMarket(dc.market || '');
      setDnaMax(relation.dna_max_threshold != null ? String(relation.dna_max_threshold) : '0.3');
      setCriteriaRows(rowsFromCriteria(relation.criteria));
      const srcs = relation.evidence_sources || [];
      if (srcs.length > 0) {
        setEvidenceSources(srcs.map((s) => ({
          type: s.type || 'delta_table',
          ref: s.ref || '',
          label: s.label || '',
          columnMap: JSON.stringify(s.column_map || {}, null, 2),
        })));
      } else if (eb?.source_table_fqn) {
        // Migrate a legacy single binding into the multi-source editor.
        setEvidenceSources([{
          type: 'delta_table', ref: eb.source_table_fqn, label: '',
          columnMap: JSON.stringify(eb.column_map || {}, null, 2),
        }]);
      } else {
        setEvidenceSources([]);
      }
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

    const evidence_sources: any[] = [];
    for (const s of evidenceSources) {
      if (!s.ref.trim()) continue;
      let parsedMap: Record<string, string> = {};
      if (s.columnMap.trim()) {
        try {
          parsedMap = JSON.parse(s.columnMap);
        } catch (e) {
          toast({ title: t('editor.validation.invalidColumnMap'), description: t('editor.validation.columnMapError', { ref: s.ref }), variant: 'destructive' });
          return;
        }
      }
      evidence_sources.push({ type: s.type, ref: s.ref.trim(), label: s.label.trim() || undefined, column_map: parsedMap });
    }

    const domain_context: Record<string, any> = {};
    if (threshold.trim()) domain_context.threshold = threshold.trim();
    if (currency.trim()) domain_context.currency = currency.trim();
    if (market.trim()) domain_context.market = market.trim();

    const payload = {
      name: name.trim(),
      slug: slug.trim() || undefined,
      description: description.trim() || undefined,
      actor_role: actorRole.trim() || undefined,
      actor_identity: actorIdentity.trim() || undefined,
      action,
      object_type: objectType.trim() || undefined,
      object_id: objectId.trim() || undefined,
      domain_context: Object.keys(domain_context).length ? domain_context : undefined,
      criteria: rowsToPayload(criteriaRows),
      evidence_sources,
      dna_max_threshold: Number.isFinite(parseFloat(dnaMax)) ? parseFloat(dnaMax) : 0.3,
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
    const { data, error } = isEdit
      ? await put<AuthorityRelation>(`/api/authority/relations/${relation!.id}`, payload)
      : await post<AuthorityRelation>('/api/authority/relations', payload);
    setSaving(false);
    if (error) {
      toast({ title: t('common:toast.failed'), description: error, variant: 'destructive' });
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

          <div className="space-y-1">
            <Label>{t('editor.labels.description')}</Label>
            <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
          </div>

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
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label>{t('editor.labels.threshold')}</Label>
              <Input value={threshold} onChange={(e) => setThreshold(e.target.value)} placeholder={t('editor.fields.threshold.placeholder')} />
            </div>
            <div className="space-y-1">
              <Label>{t('editor.labels.currency')}</Label>
              <Input value={currency} onChange={(e) => setCurrency(e.target.value)} placeholder={t('editor.fields.currency.placeholder')} />
            </div>
            <div className="space-y-1">
              <Label>{t('editor.labels.market')}</Label>
              <Input value={market} onChange={(e) => setMarket(e.target.value)} placeholder={t('editor.fields.market.placeholder')} />
            </div>
          </div>
          <SectionTitle
            title={t('editor.sections.decisionCriteria')}
            info={<Trans i18nKey="editor.sectionDescriptions.decisionCriteria" ns="authority-resolution" components={{ strong: <strong />, }} />}
          />
          <CriteriaBuilder rows={criteriaRows} onChange={setCriteriaRows} />

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

          <SectionTitle
            title={t('editor.sections.evidenceSources')}
            info={<Trans i18nKey="editor.sectionDescriptions.evidenceSources" ns="authority-resolution" components={{ strong: <strong />, }} />}
          />
          {evidenceSources.map((s, idx) => (
            <div key={idx} className="rounded-md border p-3 space-y-2">
              <div className="grid grid-cols-[auto_1fr_auto] gap-2 items-center">
                <NativeSelect
                  className="w-40"
                  value={s.type}
                  onChange={(e) => setEvidenceSources((prev) => prev.map((x, i) => i === idx ? { ...x, type: e.target.value } : x))}
                >
                  <option value="delta_table">{t('editor.evidenceSources.type.deltaTable')}</option>
                  <option value="data_product">{t('editor.evidenceSources.type.dataProduct')}</option>
                  <option value="asset">{t('editor.evidenceSources.type.asset')}</option>
                </NativeSelect>
                <Input
                  value={s.ref}
                  onChange={(e) => setEvidenceSources((prev) => prev.map((x, i) => i === idx ? { ...x, ref: e.target.value } : x))}
                  placeholder={s.type === 'delta_table' ? t('editor.evidenceSources.placeholders.deltaTable') : s.type === 'data_product' ? t('editor.evidenceSources.placeholders.dataProduct') : t('editor.evidenceSources.placeholders.asset')}
                />
                <Button variant="ghost" size="icon" onClick={() => setEvidenceSources((prev) => prev.filter((_, i) => i !== idx))}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
              <Input
                value={s.label}
                onChange={(e) => setEvidenceSources((prev) => prev.map((x, i) => i === idx ? { ...x, label: e.target.value } : x))}
                placeholder={t('editor.evidenceSources.placeholders.label')}
              />
              <div className="space-y-1">
                <Label className="text-xs">{t('editor.evidenceSources.placeholders.columnMap')}</Label>
                <Textarea
                  value={s.columnMap}
                  onChange={(e) => setEvidenceSources((prev) => prev.map((x, i) => i === idx ? { ...x, columnMap: e.target.value } : x))}
                  rows={6}
                  className="font-mono text-xs"
                />
              </div>
              {s.type === 'data_product' && (
                <p className="text-xs text-muted-foreground">{t('editor.evidenceSources.messages.dataProductNotYetSupported')}</p>
              )}
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={() => setEvidenceSources((prev) => [...prev, newEvidenceSource()])}>
            <Plus className="h-4 w-4 mr-1" /> {t('editor.buttons.addEvidenceSource')}
          </Button>

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
                <option value="app_sp">{t('editor.mcpResolverAuth.appServicePrincipal')}</option>
              </NativeSelect>
            </div>
          )}

          <SectionTitle title={t('editor.sections.dnaSchedule')} info={t('editor.sectionDescriptions.dnaSchedule')} />
          <ScheduleSelect value={scheduleCron} onChange={setScheduleCron} />

          <SectionTitle title={t('editor.sections.tags')} />
          <TagSelector value={tags} onChange={setTags} placeholder={t('common:actions.search')} />

          <div className="space-y-1 pt-2">
            <Label className="flex items-center gap-1.5">
              {t('editor.labels.dnaMaxThreshold')}
              <InfoHint>
                <Trans i18nKey="editor.hints.dnaMaxThreshold" ns="authority-resolution" components={{ strong: <strong />, }} />
              </InfoHint>
            </Label>
            <Input value={dnaMax} onChange={(e) => setDnaMax(e.target.value)} placeholder={t('editor.fields.dnaMaxThreshold.placeholder')} className="max-w-[200px]" />
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
