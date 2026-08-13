import { useState, useEffect, useCallback } from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';

// Mirrors the backend Pydantic models (models/compliance_templates.py).
export interface ComplianceField {
  id: string;
  template_id: string;
  group_title: string;
  group_order: number;
  key: string;
  label: string;
  reference_id: string;
  value_type: string; // slice 1 handles "string"; others rendered as text for now
  possible_values: string[] | null;
  default_value: unknown | null;
  hint_text: string | null;
  is_mandatory: boolean;
  field_order: number;
}

export interface ComplianceTemplate {
  id: string;
  name: string;
  description: string | null;
  entity_type: string;
  is_active: boolean;
  fields: ComplianceField[];
}

export interface ComplianceValue {
  field_id: string;
  reference_id: string;
  entity_type: string;
  entity_id: string;
  value: unknown | null;
  filled_by: string | null;
  filled_at: string | null;
}

export interface EntityCompliance {
  template: ComplianceTemplate | null;
  fields: ComplianceField[];
  values: ComplianceValue[];
}

interface ComplianceModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entityType: string;
  entityId: string;
  /** When false, inputs and save are disabled (read-only users). */
  canWrite: boolean;
  /** Called after a successful save so the host can refresh any indicators. */
  onSaved?: () => void;
}

/** Group fields by their denormalized group title, preserving order. */
function groupFields(fields: ComplianceField[]): { title: string; fields: ComplianceField[] }[] {
  const sorted = [...fields].sort(
    (a, b) => a.group_order - b.group_order || a.field_order - b.field_order,
  );
  const groups: { title: string; fields: ComplianceField[] }[] = [];
  for (const f of sorted) {
    const title = f.group_title || '';
    let g = groups.find((x) => x.title === title);
    if (!g) {
      g = { title, fields: [] };
      groups.push(g);
    }
    g.fields.push(f);
  }
  return groups;
}

interface RangeValue {
  low: number | string | null;
  high: number | string | null;
}

/** Type-aware input for a single compliance field. */
function FieldInput({
  field,
  value,
  disabled,
  onChange,
}: {
  field: ComplianceField;
  value: unknown;
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  const id = `cf-${field.id}`;

  switch (field.value_type) {
    case 'numeric':
      return (
        <Input
          id={id}
          type="number"
          value={value == null ? '' : String(value)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
          placeholder={field.hint_text || ''}
        />
      );

    case 'boolean':
      return (
        <div className="flex items-center gap-2">
          <Checkbox
            id={id}
            checked={value === true}
            disabled={disabled}
            onCheckedChange={(checked) => onChange(checked === true)}
          />
          <label htmlFor={id} className="text-sm text-muted-foreground">
            {value === true ? 'Yes' : 'No'}
          </label>
        </div>
      );

    case 'date':
      return (
        <Input
          id={id}
          type="date"
          value={typeof value === 'string' ? value : ''}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value || null)}
        />
      );

    case 'enum':
      return (
        <Select
          value={typeof value === 'string' && value ? value : undefined}
          disabled={disabled}
          onValueChange={(v) => onChange(v)}
        >
          <SelectTrigger id={id}>
            <SelectValue placeholder={field.hint_text || 'Select…'} />
          </SelectTrigger>
          <SelectContent>
            {(field.possible_values || []).map((opt) => (
              <SelectItem key={opt} value={opt}>
                {opt}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      );

    case 'multi_enum': {
      const selected: string[] = Array.isArray(value) ? (value as string[]) : [];
      const toggle = (opt: string, checked: boolean) => {
        const next = checked ? [...selected, opt] : selected.filter((s) => s !== opt);
        onChange(next);
      };
      return (
        <div className="space-y-1.5 rounded-md border p-2">
          {(field.possible_values || []).map((opt) => (
            <div key={opt} className="flex items-center gap-2">
              <Checkbox
                id={`${id}-${opt}`}
                checked={selected.includes(opt)}
                disabled={disabled}
                onCheckedChange={(checked) => toggle(opt, checked === true)}
              />
              <label htmlFor={`${id}-${opt}`} className="text-sm">
                {opt}
              </label>
            </div>
          ))}
          {(field.possible_values || []).length === 0 && (
            <p className="text-xs text-muted-foreground">No options defined.</p>
          )}
        </div>
      );
    }

    case 'range': {
      const range: RangeValue =
        value && typeof value === 'object' ? (value as RangeValue) : { low: null, high: null };
      const update = (key: 'low' | 'high', raw: string) => {
        const next = { ...range, [key]: raw === '' ? null : Number(raw) };
        onChange(next.low == null && next.high == null ? null : next);
      };
      return (
        <div className="flex items-center gap-2">
          <Input
            id={`${id}-low`}
            type="number"
            aria-label={`${field.label} low`}
            value={range.low == null ? '' : String(range.low)}
            disabled={disabled}
            onChange={(e) => update('low', e.target.value)}
            placeholder="Low"
          />
          <span className="text-muted-foreground">–</span>
          <Input
            id={`${id}-high`}
            type="number"
            aria-label={`${field.label} high`}
            value={range.high == null ? '' : String(range.high)}
            disabled={disabled}
            onChange={(e) => update('high', e.target.value)}
            placeholder="High"
          />
        </div>
      );
    }

    case 'string':
    default:
      return (
        <Input
          id={id}
          value={typeof value === 'string' ? value : ''}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.hint_text || ''}
        />
      );
  }
}

/** Shared fill-out / read-only modal for an entity's compliance template values. */
export default function ComplianceModal({
  open,
  onOpenChange,
  entityType,
  entityId,
  canWrite,
  onSaved,
}: ComplianceModalProps) {
  const { toast } = useToast();
  const { get, put } = useApi();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [data, setData] = useState<EntityCompliance | null>(null);
  // Local edit buffer keyed by field id; holds typed values per field type.
  const [draft, setDraft] = useState<Record<string, unknown>>({});

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const { data: resp, error } = await get<EntityCompliance>(
        `/api/compliance-templates/entities/${entityType}/${entityId}`,
      );
      if (error) throw new Error(error);
      setData(resp);
      // Seed the draft: stored value if present, else the field default.
      const valueByField = new Map((resp?.values || []).map((v) => [v.field_id, v.value]));
      const seeded: Record<string, unknown> = {};
      for (const f of resp?.fields || []) {
        const stored = valueByField.has(f.id) ? valueByField.get(f.id) : f.default_value;
        seeded[f.id] = stored ?? null;
      }
      setDraft(seeded);
    } catch (err: any) {
      toast({ title: 'Error', description: err?.message || 'Failed to load compliance data', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [get, entityType, entityId, toast]);

  useEffect(() => {
    if (open) fetchData();
  }, [open, fetchData]);

  const handleSave = async () => {
    if (!data?.template) return;
    setSaving(true);
    try {
      // Replace-all write: send every shown field (including untouched defaults).
      // Empty strings and empty multi-selects are normalized to null (unset).
      const values = data.fields.map((f) => {
        let value = draft[f.id];
        if (value === '' || value === undefined) value = null;
        if (Array.isArray(value) && value.length === 0) value = null;
        return { field_id: f.id, value };
      });
      const { error } = await put(
        `/api/compliance-templates/entities/${entityType}/${entityId}/values`,
        { values },
      );
      if (error) throw new Error(error);
      toast({ title: 'Saved', description: 'Compliance information updated.' });
      onOpenChange(false);
      onSaved?.();
    } catch (err: any) {
      toast({ title: 'Error', description: err?.message || 'Failed to save', variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  const groups = data ? groupFields(data.fields) : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{data?.template?.name || 'Compliance'}</DialogTitle>
          <DialogDescription>
            {canWrite
              ? 'Complete the compliance information for this item.'
              : 'Compliance information for this item (read-only).'}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : !data?.template ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No active compliance template for this item.
          </p>
        ) : (
          <div className="space-y-6 py-2">
            {groups.map((group) => (
              <div key={group.title || '__default__'} className="space-y-4">
                {group.title && (
                  <h3 className="text-sm font-semibold text-foreground border-b pb-1">{group.title}</h3>
                )}
                {group.fields.map((field) => (
                  <div key={field.id} className="space-y-1.5">
                    <Label htmlFor={`cf-${field.id}`} className="flex items-center gap-1">
                      {field.label}
                      {field.is_mandatory && <span className="text-destructive">*</span>}
                    </Label>
                    <FieldInput
                      field={field}
                      value={draft[field.id]}
                      disabled={!canWrite}
                      onChange={(v) => setDraft((prev) => ({ ...prev, [field.id]: v }))}
                    />
                    {field.hint_text && (
                      <p className="text-xs text-muted-foreground">{field.hint_text}</p>
                    )}
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {canWrite ? 'Cancel' : 'Close'}
          </Button>
          {canWrite && data?.template && (
            <Button onClick={handleSave} disabled={saving || loading}>
              {saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
              Save
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
