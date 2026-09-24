import { useState, useEffect } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import DomainMultiSelector from '@/components/ui/domain-multi-selector';
import TagSelector from '@/components/ui/tag-selector';
import type { AssignedTag } from '@/components/ui/tag-chip';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { Plus, Trash2, Loader2 } from 'lucide-react';
import {
  ACTION_VOCAB, AFFIRMATION_ROLES,
  type AuthorityRelation, type AffirmationInput,
} from '@/types/authority-resolution';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (created: AuthorityRelation) => void;
  /** When provided, the dialog edits this relation (PUT) instead of creating a new one. */
  relation?: AuthorityRelation | null;
}

const DEFAULT_COLUMN_MAP = `{
  "actual_approver": "approver",
  "documented_approver": "documented_approver",
  "value": "discount",
  "escalated": "escalated",
  "cosign_present": "cosign",
  "action": "action",
  "object_id": "promo_id"
}`;

const DEFAULT_AFFIRMATIONS: AffirmationInput[] = AFFIRMATION_ROLES.map((role) => ({
  role, principal: '', principal_type: 'user', required: true, is_approver: true, is_reviewer: false,
}));

export default function CreateAuthorityRelationDialog({ open, onOpenChange, onCreated, relation }: Props) {
  const { post, put } = useApi();
  const { toast } = useToast();
  const isEdit = !!relation;
  const [saving, setSaving] = useState(false);

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
  const [requiredCosign, setRequiredCosign] = useState(false);
  const [sourceTable, setSourceTable] = useState('');
  const [columnMap, setColumnMap] = useState(DEFAULT_COLUMN_MAP);
  const [domainIds, setDomainIds] = useState<string[]>([]);
  const [primaryDomainId, setPrimaryDomainId] = useState<string | null>(null);
  const [affirmations, setAffirmations] = useState<AffirmationInput[]>(DEFAULT_AFFIRMATIONS);
  const [tags, setTags] = useState<(string | AssignedTag)[]>([]);

  const reset = () => {
    setName(''); setSlug(''); setDescription(''); setActorRole(''); setActorIdentity('');
    setAction('approve'); setObjectType('data_product'); setObjectId(''); setThreshold('');
    setCurrency(''); setMarket(''); setDnaMax('0.3'); setRequiredCosign(false);
    setSourceTable(''); setColumnMap(DEFAULT_COLUMN_MAP); setDomainIds([]); setPrimaryDomainId(null);
    setAffirmations(DEFAULT_AFFIRMATIONS); setTags([]);
  };

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
      setRequiredCosign(!!(relation.decision_logic && relation.decision_logic.required_cosign));
      setSourceTable(eb?.source_table_fqn || '');
      setColumnMap(eb?.column_map ? JSON.stringify(eb.column_map, null, 2) : DEFAULT_COLUMN_MAP);
      setDomainIds((relation.domains || []).map((d) => d.domain_id));
      setPrimaryDomainId((relation.domains || []).find((d) => d.is_primary)?.domain_id ?? null);
      setAffirmations(
        (relation.affirmations || []).length
          ? (relation.affirmations || []).map((a) => ({
              role: a.role,
              principal: a.principal,
              principal_type: a.principal_type,
              required: a.required,
              is_approver: a.is_approver ?? true,
              is_reviewer: a.is_reviewer ?? false,
            }))
          : DEFAULT_AFFIRMATIONS,
      );
      setTags((relation.tags || []).map((t) => t.fully_qualified_name).filter(Boolean) as string[]);
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

    let evidence_binding: any = undefined;
    if (sourceTable.trim()) {
      let parsedMap: Record<string, string>;
      try {
        parsedMap = JSON.parse(columnMap);
      } catch (e) {
        toast({ title: 'Invalid column map', description: 'Evidence column map must be valid JSON.', variant: 'destructive' });
        return;
      }
      evidence_binding = { source_table_fqn: sourceTable.trim(), column_map: parsedMap };
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
      decision_logic: requiredCosign ? { required_cosign: true } : undefined,
      evidence_binding,
      dna_max_threshold: parseFloat(dnaMax) || 0.3,
      domain_ids: domainIds,
      primary_domain_id: primaryDomainId,
      affirmations: affirmations.filter((a) => a.principal.trim()),
      tags: tags.map((t) => ({ tag_fqn: typeof t === 'string' ? t : t.fully_qualified_name })),
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
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
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
              <select
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
                value={action}
                onChange={(e) => setAction(e.target.value)}
              >
                {ACTION_VOCAB.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
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
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={requiredCosign} onChange={(e) => setRequiredCosign(e.target.checked)} />
            Require a co-sign for this decision
          </label>

          <div className="text-sm font-semibold text-muted-foreground pt-2">Domains</div>
          <DomainMultiSelector
            value={domainIds}
            primaryDomainId={primaryDomainId}
            onChange={(ids, primary) => { setDomainIds(ids); setPrimaryDomainId(primary); }}
          />

          <div className="text-sm font-semibold text-muted-foreground pt-2">Evidence binding (v1: a Delta table)</div>
          <div className="space-y-1">
            <Label>Source table (FQN)</Label>
            <Input value={sourceTable} onChange={(e) => setSourceTable(e.target.value)} placeholder="catalog.schema.promotion_decisions" />
          </div>
          <div className="space-y-1">
            <Label>Column map (JSON)</Label>
            <Textarea value={columnMap} onChange={(e) => setColumnMap(e.target.value)} rows={8} className="font-mono text-xs" />
          </div>

          <div className="text-sm font-semibold text-muted-foreground pt-2">Participants (N-functional gate & review)</div>
          <p className="text-xs text-muted-foreground -mt-2">
            <strong>Approvers</strong> count toward the affirmation gate. <strong>Reviewers</strong> are
            interviewed during the review process to confirm the relation reflects reality. A principal can be both.
          </p>
          {affirmations.map((a, idx) => (
            <div key={idx} className="grid grid-cols-[1fr_1.5fr_auto] gap-2 items-center">
              <select
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm"
                value={a.role}
                onChange={(e) => updateAffirmation(idx, { role: e.target.value })}
              >
                {AFFIRMATION_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                {!AFFIRMATION_ROLES.includes(a.role) && <option value={a.role}>{a.role}</option>}
              </select>
              <Input
                value={a.principal}
                onChange={(e) => updateAffirmation(idx, { principal: e.target.value })}
                placeholder="principal (email or group)"
              />
              <div className="flex items-center gap-3">
                <select
                  className="flex h-9 rounded-md border border-input bg-transparent px-2 text-sm"
                  value={a.principal_type}
                  onChange={(e) => updateAffirmation(idx, { principal_type: e.target.value })}
                >
                  <option value="user">user</option>
                  <option value="group">group</option>
                </select>
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
            onClick={() => setAffirmations((prev) => [...prev, { role: 'business', principal: '', principal_type: 'user', required: true, is_approver: true, is_reviewer: false }])}
          >
            <Plus className="h-4 w-4 mr-1" /> Add participant
          </Button>

          <div className="text-sm font-semibold text-muted-foreground pt-2">Tags</div>
          <TagSelector value={tags} onChange={setTags} placeholder="Search and select tags…" />

          <div className="grid grid-cols-2 gap-3 pt-2">
            <div className="space-y-1">
              <Label>DNAco max (activation ceiling)</Label>
              <Input value={dnaMax} onChange={(e) => setDnaMax(e.target.value)} placeholder="0.3" />
            </div>
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
