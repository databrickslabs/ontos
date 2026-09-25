import { useState, useEffect } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import NativeSelect from '@/components/ui/native-select';
import DomainMultiSelector from '@/components/ui/domain-multi-selector';
import TagSelector from '@/components/ui/tag-selector';
import type { AssignedTag } from '@/components/ui/tag-chip';
import ScheduleSelect from '@/components/authority-resolution/schedule-select';
import CriteriaBuilder, {
  rowsFromCriteria, rowsToPayload, type CriterionRow,
} from '@/components/authority-resolution/criteria-builder';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { Plus, Trash2, Loader2 } from 'lucide-react';
import {
  ACTION_VOCAB,
  type AuthorityRelation, type AffirmationInput,
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
  const { get, post, put } = useApi();
  const { toast } = useToast();
  const isEdit = !!relation;
  const [saving, setSaving] = useState(false);
  const [businessRoles, setBusinessRoles] = useState<BusinessRoleRead[]>([]);

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
  const [affirmations, setAffirmations] = useState<AffirmationInput[]>(DEFAULT_AFFIRMATIONS);
  const [tags, setTags] = useState<(string | AssignedTag)[]>([]);
  const [scheduleCron, setScheduleCron] = useState<string | null>(null);

  const reset = () => {
    setName(''); setSlug(''); setDescription(''); setActorRole(''); setActorIdentity('');
    setAction('approve'); setObjectType('data_product'); setObjectId(''); setThreshold('');
    setCurrency(''); setMarket(''); setDnaMax('0.3'); setCriteriaRows([]);
    setEvidenceSources([]); setDomainIds([]); setPrimaryDomainId(null);
    setAffirmations(DEFAULT_AFFIRMATIONS); setTags([]); setScheduleCron(null);
  };

  // Load active Business Roles for the participant role picker (Settings feature).
  useEffect(() => {
    if (!open) return;
    (async () => {
      const { data } = await get<BusinessRoleRead[]>('/api/business-roles?role_status=active');
      if (Array.isArray(data)) setBusinessRoles(data.filter((r) => r.status === 'active'));
    })();
  }, [open, get]);

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
      toast({ title: 'Name is required', variant: 'destructive' });
      return;
    }

    const evidence_sources: any[] = [];
    for (const s of evidenceSources) {
      if (!s.ref.trim()) continue;
      let parsedMap: Record<string, string> = {};
      if (s.columnMap.trim()) {
        try {
          parsedMap = JSON.parse(s.columnMap);
        } catch (e) {
          toast({ title: 'Invalid column map', description: `Column map for "${s.ref}" must be valid JSON.`, variant: 'destructive' });
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
      dna_max_threshold: parseFloat(dnaMax) || 0.3,
      domain_ids: domainIds,
      primary_domain_id: primaryDomainId,
      affirmations: affirmations.filter((a) => a.principal.trim() && a.role),
      tags: tags.map((t) => ({ tag_fqn: typeof t === 'string' ? t : t.fully_qualified_name })),
      schedule_cron: scheduleCron,
    };

    setSaving(true);
    const { data, error } = isEdit
      ? await put<AuthorityRelation>(`/api/authority/relations/${relation!.id}`, payload)
      : await post<AuthorityRelation>('/api/authority/relations', payload);
    setSaving(false);
    if (error) {
      toast({ title: isEdit ? 'Failed to save' : 'Failed to create', description: error, variant: 'destructive' });
      return;
    }
    if (!isEdit) reset();
    onCreated(data);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit Authority Relation' : 'New Authority Relation'}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Name *</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="EMEA-North discount approval" />
            </div>
            <div className="space-y-1">
              <Label>Slug (agent key)</Label>
              <Input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="ar-disc-emea-north" />
            </div>
          </div>

          <div className="space-y-1">
            <Label>Description</Label>
            <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
          </div>

          <div className="text-sm font-semibold text-muted-foreground pt-2">Authority Relation (ARF tuple)</div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Actor role</Label>
              <Input value={actorRole} onChange={(e) => setActorRole(e.target.value)} placeholder="Regional Sales Manager – East" />
            </div>
            <div className="space-y-1">
              <Label>Actor identity (signer)</Label>
              <Input value={actorIdentity} onChange={(e) => setActorIdentity(e.target.value)} placeholder="rsm-east@example.com" />
            </div>
            <div className="space-y-1">
              <Label>Action</Label>
              <NativeSelect value={action} onChange={(e) => setAction(e.target.value)}>
                {ACTION_VOCAB.map((a) => <option key={a} value={a}>{a}</option>)}
              </NativeSelect>
            </div>
            <div className="space-y-1">
              <Label>Object type</Label>
              <Input value={objectType} onChange={(e) => setObjectType(e.target.value)} placeholder="data_product | data_contract" />
            </div>
            <div className="space-y-1">
              <Label>Object id</Label>
              <Input value={objectId} onChange={(e) => setObjectId(e.target.value)} placeholder="dp-1234" />
            </div>
          </div>

          <div className="text-sm font-semibold text-muted-foreground pt-2">Domain-Context (evaluable predicate)</div>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label>Threshold</Label>
              <Input value={threshold} onChange={(e) => setThreshold(e.target.value)} placeholder="0.15" />
            </div>
            <div className="space-y-1">
              <Label>Currency</Label>
              <Input value={currency} onChange={(e) => setCurrency(e.target.value)} placeholder="EUR" />
            </div>
            <div className="space-y-1">
              <Label>Market</Label>
              <Input value={market} onChange={(e) => setMarket(e.target.value)} placeholder="emea-north" />
            </div>
          </div>
          <div className="text-sm font-semibold text-muted-foreground pt-2">Decision criteria</div>
          <p className="text-xs text-muted-foreground -mt-2">
            Author the rules the resolution gate enforces (and the DNA-Coefficient measures divergence
            against). Each criterion is a reusable <strong>Compliance Check</strong>.
          </p>
          <CriteriaBuilder rows={criteriaRows} onChange={setCriteriaRows} />

          <div className="text-sm font-semibold text-muted-foreground pt-2">Domains</div>
          <DomainMultiSelector
            value={domainIds}
            primaryDomainId={primaryDomainId}
            onChange={(ids, primary) => { setDomainIds(ids); setPrimaryDomainId(primary); }}
          />

          <div className="text-sm font-semibold text-muted-foreground pt-2">Evidence sources</div>
          <p className="text-xs text-muted-foreground -mt-2">
            Bind the past decisions the DNA-Coefficient is measured against. Add one or more sources —
            a <strong>Delta table</strong>, a <strong>Data Product</strong>, or an <strong>Asset</strong>
            (volume file, table, or view). Each maps its columns to the canonical AR elements.
          </p>
          {evidenceSources.map((s, idx) => (
            <div key={idx} className="rounded-md border p-3 space-y-2">
              <div className="grid grid-cols-[auto_1fr_auto] gap-2 items-center">
                <NativeSelect
                  className="w-40"
                  value={s.type}
                  onChange={(e) => setEvidenceSources((prev) => prev.map((x, i) => i === idx ? { ...x, type: e.target.value } : x))}
                >
                  <option value="delta_table">Delta table</option>
                  <option value="data_product">Data Product</option>
                  <option value="asset">Asset</option>
                </NativeSelect>
                <Input
                  value={s.ref}
                  onChange={(e) => setEvidenceSources((prev) => prev.map((x, i) => i === idx ? { ...x, ref: e.target.value } : x))}
                  placeholder={s.type === 'delta_table' ? 'catalog.schema.promotion_decisions' : s.type === 'data_product' ? 'data product id' : 'asset FQN (table/view/volume)'}
                />
                <Button variant="ghost" size="icon" onClick={() => setEvidenceSources((prev) => prev.filter((_, i) => i !== idx))}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
              <Input
                value={s.label}
                onChange={(e) => setEvidenceSources((prev) => prev.map((x, i) => i === idx ? { ...x, label: e.target.value } : x))}
                placeholder="Optional label"
              />
              <div className="space-y-1">
                <Label className="text-xs">Column map (JSON)</Label>
                <Textarea
                  value={s.columnMap}
                  onChange={(e) => setEvidenceSources((prev) => prev.map((x, i) => i === idx ? { ...x, columnMap: e.target.value } : x))}
                  rows={6}
                  className="font-mono text-xs"
                />
              </div>
              {s.type === 'data_product' && (
                <p className="text-xs text-muted-foreground">Data Product sources are recorded but not yet read for DNAco (v1).</p>
              )}
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={() => setEvidenceSources((prev) => [...prev, newEvidenceSource()])}>
            <Plus className="h-4 w-4 mr-1" /> Add evidence source
          </Button>

          <div className="text-sm font-semibold text-muted-foreground pt-2">Participants (N-functional gate & review)</div>
          <p className="text-xs text-muted-foreground -mt-2">
            <strong>Approvers</strong> count toward the affirmation gate. <strong>Reviewers</strong> are
            interviewed during the review process to confirm the relation reflects reality. A principal can be both.
          </p>
          {affirmations.map((a, idx) => (
            <div key={idx} className="grid grid-cols-[1fr_1.5fr_auto] gap-2 items-center">
              <NativeSelect
                value={a.business_role_id || ''}
                onChange={(e) => {
                  const br = businessRoles.find((r) => r.id === e.target.value);
                  updateAffirmation(idx, {
                    business_role_id: br?.id,
                    role: br?.name || '',
                    role_category: br?.category || undefined,
                  });
                }}
              >
                <option value="">Select a role…</option>
                {businessRoles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                {a.business_role_id && !businessRoles.some((r) => r.id === a.business_role_id) && (
                  <option value={a.business_role_id}>{a.role || a.business_role_id}</option>
                )}
              </NativeSelect>
              <Input
                value={a.principal}
                onChange={(e) => updateAffirmation(idx, { principal: e.target.value })}
                placeholder="principal (email or group)"
              />
              <div className="flex items-center gap-3">
                <NativeSelect
                  className="w-28"
                  value={a.principal_type}
                  onChange={(e) => updateAffirmation(idx, { principal_type: e.target.value })}
                >
                  <option value="user">user</option>
                  <option value="group">group</option>
                </NativeSelect>
                <label className="flex items-center gap-1 text-xs whitespace-nowrap">
                  <input type="checkbox" checked={a.is_approver ?? true}
                    onChange={(e) => updateAffirmation(idx, { is_approver: e.target.checked })} /> approver
                </label>
                <label className="flex items-center gap-1 text-xs whitespace-nowrap">
                  <input type="checkbox" checked={a.is_reviewer ?? false}
                    onChange={(e) => updateAffirmation(idx, { is_reviewer: e.target.checked })} /> reviewer
                </label>
                <Button variant="ghost" size="icon" onClick={() => setAffirmations((prev) => prev.filter((_, i) => i !== idx))}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
          <Button
            variant="outline" size="sm"
            onClick={() => setAffirmations((prev) => [...prev, { role: '', principal: '', principal_type: 'user', required: true, is_approver: true, is_reviewer: false }])}
          >
            <Plus className="h-4 w-4 mr-1" /> Add participant
          </Button>

          <div className="text-sm font-semibold text-muted-foreground pt-2">DNA-Coefficient schedule</div>
          <ScheduleSelect value={scheduleCron} onChange={setScheduleCron} />

          <div className="text-sm font-semibold text-muted-foreground pt-2">Tags</div>
          <TagSelector value={tags} onChange={setTags} placeholder="Search and select tags…" />

          <div className="space-y-1 pt-2">
            <Label>Max DNA-Coefficient to activate (divergence ceiling)</Label>
            <Input value={dnaMax} onChange={(e) => setDnaMax(e.target.value)} placeholder="0.3" className="max-w-[200px]" />
            <p className="text-xs text-muted-foreground">
              The DNA-Coefficient measures how far past decisions <strong>diverge</strong> from this rule
              (0.0 = perfect match, higher = worse). The AR can be activated only while its measured value
              stays at or below this ceiling; an active AR that later drifts above it is auto-flagged <strong>Needs Review</strong>.
            </p>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            {isEdit ? 'Save' : 'Create'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
