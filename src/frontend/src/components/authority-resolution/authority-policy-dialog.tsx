import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import NativeSelect from '@/components/ui/native-select';
import { InfoHint, SectionTitle } from '@/components/authority-resolution/info-hint';
import { useApi } from '@/hooks/use-api';
import { useTeams } from '@/hooks/use-teams';
import { useToast } from '@/hooks/use-toast';
import { Loader2, Plus, Trash2 } from 'lucide-react';
import { POLICY_TYPES, type AuthorityPolicy, type PolicyClause, type PolicyType } from '@/types/authority-resolution';

/**
 * Create a policy, or edit a draft one. An approved policy is immutable: it
 * changes through a new version (the detail view's New version action).
 */

export interface ClauseDraft {
  ref: string;
  title: string;
  text: string;
  amount: string;
  currency: string;
  conditions: string;   // one per line
}

const emptyClause = (): ClauseDraft => ({ ref: '', title: '', text: '', amount: '', currency: '', conditions: '' });

export const clauseDraftsFrom = (clauses?: PolicyClause[] | null): ClauseDraft[] =>
  (clauses || []).map((c) => ({
    ref: c.ref, title: c.title || '', text: c.text || '',
    amount: c.limits?.amount != null ? String(c.limits.amount) : '',
    currency: c.limits?.currency || '',
    conditions: (c.conditions || []).join('\n'),
  }));

/** Clauses for the API, or an i18n error key. Rows without a ref and text are dropped. */
export function clausesFromDrafts(drafts: ClauseDraft[]): { value?: PolicyClause[]; error?: string } {
  const out: PolicyClause[] = [];
  const seen = new Set<string>();
  for (const d of drafts) {
    const ref = d.ref.trim();
    if (!ref && !d.text.trim() && !d.title.trim()) continue;
    if (!ref) return { error: 'policy.editor.validation.clauseRef' };
    if (seen.has(ref.toLowerCase())) return { error: 'policy.editor.validation.clauseDuplicate' };
    seen.add(ref.toLowerCase());
    const clause: PolicyClause = { ref };
    if (d.title.trim()) clause.title = d.title.trim();
    if (d.text.trim()) clause.text = d.text.trim();
    if (d.amount.trim()) {
      const n = Number(d.amount);
      if (!Number.isFinite(n)) return { error: 'policy.editor.validation.amount' };
      clause.limits = { amount: n, ...(d.currency.trim() ? { currency: d.currency.trim().toUpperCase() } : {}) };
    } else if (d.currency.trim()) {
      clause.limits = { currency: d.currency.trim().toUpperCase() };
    }
    const conditions = d.conditions.split('\n').map((c) => c.trim()).filter(Boolean);
    if (conditions.length) clause.conditions = conditions;
    out.push(clause);
  }
  return { value: out };
}

const dateInput = (iso?: string | null) => (iso ? iso.slice(0, 10) : '');
const isoDate = (d: string) => (d ? `${d}T00:00:00Z` : null);

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (policy: AuthorityPolicy) => void;
  policy?: AuthorityPolicy | null;
}

export default function AuthorityPolicyDialog({ open, onOpenChange, onSaved, policy }: Props) {
  const { t } = useTranslation(['authority-resolution']);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{policy ? t('policy.editor.titleEdit', { key: policy.policy_key, version: policy.version }) : t('policy.editor.titleNew')}</DialogTitle>
        </DialogHeader>
        {/* Mounted per open, so the form starts from the policy as it is now. */}
        {open && <PolicyForm policy={policy} onSaved={onSaved} onCancel={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

function PolicyForm({ policy, onSaved, onCancel }: { policy?: AuthorityPolicy | null; onSaved: (p: AuthorityPolicy) => void; onCancel: () => void }) {
  const { t } = useTranslation(['authority-resolution', 'common']);
  const { post, put } = useApi();
  const { toast } = useToast();
  const { teams } = useTeams();
  const isEdit = !!policy;

  const [key, setKey] = useState(policy?.policy_key || '');
  const [version, setVersion] = useState(policy?.version || '1');
  const [title, setTitle] = useState(policy?.title || '');
  const [type, setType] = useState<PolicyType>(policy?.policy_type || 'DOA');
  const [summary, setSummary] = useState(policy?.summary || '');
  const [ownerTeamId, setOwnerTeamId] = useState(policy?.owner_team_id || '');
  const [jurisdiction, setJurisdiction] = useState(policy?.jurisdiction ? JSON.stringify(policy.jurisdiction) : '');
  const [from, setFrom] = useState(dateInput(policy?.effective_from));
  const [to, setTo] = useState(dateInput(policy?.effective_to));
  const [clauses, setClauses] = useState<ClauseDraft[]>(() => (policy?.clauses?.length ? clauseDraftsFrom(policy.clauses) : [emptyClause()]));
  const [saving, setSaving] = useState(false);

  const patch = (i: number, p: Partial<ClauseDraft>) => setClauses((cs) => cs.map((c, j) => (j === i ? { ...c, ...p } : c)));

  const save = async () => {
    if (!title.trim() || (!isEdit && !key.trim())) {
      toast({ title: t('policy.editor.validation.required'), variant: 'destructive' });
      return;
    }
    const cl = clausesFromDrafts(clauses);
    if (cl.error) {
      toast({ title: t('policy.editor.validation.title'), description: t(cl.error), variant: 'destructive' });
      return;
    }
    let juris: Record<string, any> | null = null;
    if (jurisdiction.trim()) {
      try {
        juris = JSON.parse(jurisdiction);
      } catch {
        toast({ title: t('policy.editor.validation.title'), description: t('policy.editor.validation.jurisdiction'), variant: 'destructive' });
        return;
      }
    }
    const body = {
      title: title.trim(), policy_type: type, summary: summary.trim() || null,
      owner_team_id: ownerTeamId || null, jurisdiction: juris,
      effective_from: isoDate(from), effective_to: isoDate(to), clauses: cl.value,
      ...(isEdit ? {} : { policy_key: key.trim(), version: version.trim() || '1' }),
    };
    setSaving(true);
    const { data, error } = isEdit
      ? await put<AuthorityPolicy>(`/api/authority/policies/${policy!.id}`, body)
      : await post<AuthorityPolicy>('/api/authority/policies', body);
    setSaving(false);
    if (error) {
      toast({ title: t('common:toast.failed'), description: error, variant: 'destructive' });
      return;
    }
    onSaved(data);
  };

  return (
      <>
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label className="flex items-center gap-1.5">{t('policy.fields.key')} * <InfoHint>{t('policy.editor.keyHint')}</InfoHint></Label>
              <Input value={key} onChange={(e) => setKey(e.target.value)} disabled={isEdit} placeholder="POL-DOA" className="font-mono" />
            </div>
            <div className="space-y-1">
              <Label>{t('policy.fields.version')}</Label>
              <Input value={version} onChange={(e) => setVersion(e.target.value)} disabled={isEdit} />
            </div>
            <div className="space-y-1">
              <Label>{t('policy.fields.type')}</Label>
              <NativeSelect value={type} onChange={(e) => setType(e.target.value as PolicyType)}>
                {POLICY_TYPES.map((p) => <option key={p} value={p}>{t(`policy.type.${p}`)}</option>)}
              </NativeSelect>
            </div>
          </div>
          <div className="space-y-1">
            <Label>{t('policy.fields.title')} *</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>{t('policy.fields.summary')}</Label>
            <Textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={2} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('policy.fields.owner')}</Label>
              <NativeSelect value={ownerTeamId} onChange={(e) => setOwnerTeamId(e.target.value)}>
                <option value="">{t('editor.fields.noTeam')}</option>
                {teams.map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}
              </NativeSelect>
            </div>
            <div className="space-y-1">
              <Label className="flex items-center gap-1.5">{t('policy.fields.jurisdiction')} <InfoHint>{t('policy.editor.jurisdictionHint')}</InfoHint></Label>
              <Input value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} className="font-mono text-xs"
                     placeholder='{"market": ["DE", "AT"]}' />
            </div>
            <div className="space-y-1">
              <Label>{t('policy.fields.effectiveFrom')}</Label>
              <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>{t('policy.fields.effectiveTo')}</Label>
              <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </div>
          </div>

          <SectionTitle title={t('policy.clauses.title')} info={t('policy.clauses.hint')} />
          <div className="space-y-3">
            {clauses.map((c, i) => (
              <div key={i} className="rounded-md border p-3 space-y-2">
                <div className="grid grid-cols-[7rem_1fr_auto] gap-2 items-center">
                  <Input value={c.ref} onChange={(e) => patch(i, { ref: e.target.value })} placeholder="§7.1" className="h-8 font-mono text-xs" />
                  <Input value={c.title} onChange={(e) => patch(i, { title: e.target.value })} placeholder={t('policy.clauses.titlePlaceholder')} className="h-8 text-xs" />
                  <Button variant="ghost" size="icon" className="h-8 w-8" aria-label={t('policy.clauses.remove')}
                          onClick={() => setClauses((cs) => cs.filter((_, j) => j !== i))}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
                <Textarea value={c.text} onChange={(e) => patch(i, { text: e.target.value })} rows={2}
                          placeholder={t('policy.clauses.textPlaceholder')} className="text-xs" />
                <div className="grid grid-cols-[8rem_6rem_1fr] gap-2">
                  <Input value={c.amount} onChange={(e) => patch(i, { amount: e.target.value })} placeholder={t('policy.clauses.amount')} className="h-8 text-xs" />
                  <Input value={c.currency} onChange={(e) => patch(i, { currency: e.target.value })} placeholder={t('policy.clauses.currency')} className="h-8 text-xs" />
                  <Textarea value={c.conditions} onChange={(e) => patch(i, { conditions: e.target.value })} rows={1}
                            placeholder={t('policy.clauses.conditionsPlaceholder')} className="text-xs min-h-8" />
                </div>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={() => setClauses((cs) => [...cs, emptyClause()])}>
              <Plus className="h-4 w-4 mr-1" /> {t('policy.clauses.add')}
            </Button>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>{t('common:actions.cancel')}</Button>
          <Button onClick={save} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
            {isEdit ? t('common:actions.save') : t('common:actions.create')}
          </Button>
        </DialogFooter>
      </>
  );
}
