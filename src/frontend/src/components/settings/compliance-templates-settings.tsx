import { useState, useEffect, useCallback, useRef } from 'react';
import { Plus, Trash2, Power, PowerOff, Loader2, X } from 'lucide-react';
import { ListItemSkeleton } from '@/components/common/list-view-skeleton';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';

interface ComplianceField {
  id?: string;
  group_title: string;
  key: string;
  label: string;
  reference_id: string;
  value_type: string;
  hint_text: string | null;
  is_mandatory: boolean;
  field_order: number;
  group_order: number;
}

interface ComplianceTemplate {
  id: string;
  name: string;
  description: string | null;
  entity_type: string;
  is_active: boolean;
  fields: ComplianceField[];
}

// Slice 1: Data Products is the only bound entity type exercised end-to-end.
const ENTITY_TYPE_OPTIONS = [
  { value: 'data_product', label: 'Data Products' },
];

interface DraftField {
  label: string;
  reference_id: string;
  group_title: string;
  value_type: string;
  possible_values: string; // comma-separated in the editor; split on save
  hint_text: string;
  default_value: string; // raw text; backend coerces to the field type
  is_mandatory: boolean;
}

const VALUE_TYPE_OPTIONS = [
  { value: 'string', label: 'Text' },
  { value: 'numeric', label: 'Number' },
  { value: 'boolean', label: 'Yes/No' },
  { value: 'date', label: 'Date' },
  { value: 'enum', label: 'Single choice' },
  { value: 'multi_enum', label: 'Multiple choice' },
  { value: 'range', label: 'Range (low–high)' },
];

const VOCAB_TYPES = new Set(['enum', 'multi_enum']);

/** Parse the admin's raw default text into the JSON shape for a field type.
 *  The backend re-validates/coerces, so this only needs to pick the right shape. */
function parseDefaultValue(valueType: string, raw: string): unknown {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  switch (valueType) {
    case 'numeric': {
      const n = Number(trimmed);
      return Number.isNaN(n) ? trimmed : n;
    }
    case 'boolean':
      return /^(true|yes|1)$/i.test(trimmed);
    case 'multi_enum':
      return trimmed.split(',').map((s) => s.trim()).filter(Boolean);
    case 'range': {
      // Accept "low-high" or "low,high".
      const parts = trimmed.split(/[,-]/).map((s) => s.trim());
      if (parts.length === 2) return { low: Number(parts[0]), high: Number(parts[1]) };
      return trimmed;
    }
    default:
      return trimmed; // string, enum, date
  }
}

export default function ComplianceTemplatesSettings() {
  const { toast } = useToast();
  const { get, post, delete: apiDelete } = useApi();

  const [templates, setTemplates] = useState<ComplianceTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deletingTemplate, setDeletingTemplate] = useState<ComplianceTemplate | null>(null);
  const [saving, setSaving] = useState(false);
  const [formData, setFormData] = useState({ name: '', description: '', entity_type: 'data_product' });
  const [draftFields, setDraftFields] = useState<DraftField[]>([]);
  const hasFetched = useRef(false);

  const fetchTemplates = useCallback(async () => {
    try {
      setLoading(true);
      const { data, error } = await get<ComplianceTemplate[]>('/api/compliance-templates');
      if (error) throw new Error(error);
      setTemplates(Array.isArray(data) ? data : []);
    } catch {
      // Silent on initial load to avoid flash.
    } finally {
      setLoading(false);
    }
  }, [get]);

  useEffect(() => {
    if (!hasFetched.current) {
      hasFetched.current = true;
      fetchTemplates();
    }
  }, [fetchTemplates]);

  const handleOpenCreate = () => {
    setFormData({ name: '', description: '', entity_type: 'data_product' });
    setDraftFields([]);
    setDialogOpen(true);
  };

  const toSlug = (s: string) =>
    s.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');

  const handleAddDraftField = () => {
    setDraftFields((prev) => [
      ...prev,
      { label: '', reference_id: '', group_title: '', value_type: 'string', possible_values: '', hint_text: '', default_value: '', is_mandatory: false },
    ]);
  };

  const handleSave = async () => {
    if (!formData.name.trim()) return;
    setSaving(true);
    try {
      const fields = draftFields
        .filter((f) => f.label.trim())
        .map((f, idx) => {
          const possibleValues = VOCAB_TYPES.has(f.value_type)
            ? f.possible_values.split(',').map((s) => s.trim()).filter(Boolean)
            : null;
          return {
            group_title: f.group_title.trim(),
            group_order: 0,
            key: toSlug(f.label) || `field-${idx + 1}`,
            label: f.label.trim(),
            reference_id: (f.reference_id.trim() && toSlug(f.reference_id)) || toSlug(f.label) || `field-${idx + 1}`,
            value_type: f.value_type,
            possible_values: possibleValues,
            default_value: parseDefaultValue(f.value_type, f.default_value),
            hint_text: f.hint_text.trim() || null,
            is_mandatory: f.is_mandatory,
            field_order: idx,
          };
        });
      const { error } = await post('/api/compliance-templates', {
        name: formData.name,
        description: formData.description || null,
        entity_type: formData.entity_type,
        fields,
      });
      if (error) throw new Error(error);
      toast({ title: 'Created', description: `Template "${formData.name}" created.` });
      setDialogOpen(false);
      fetchTemplates();
    } catch (err: any) {
      toast({ title: 'Error', description: err?.message || 'Failed to save', variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  const handleToggleActive = async (template: ComplianceTemplate) => {
    const action = template.is_active ? 'deactivate' : 'activate';
    const { error } = await post<ComplianceTemplate>(
      `/api/compliance-templates/${template.id}/${action}`,
      {},
    );
    if (error) {
      toast({ title: 'Error', description: error, variant: 'destructive' });
    } else {
      toast({
        title: template.is_active ? 'Deactivated' : 'Activated',
        description: `Template "${template.name}" ${template.is_active ? 'deactivated' : 'is now active'}.`,
      });
      fetchTemplates();
    }
  };

  const handleDelete = async () => {
    if (!deletingTemplate) return;
    const { error } = await apiDelete(`/api/compliance-templates/${deletingTemplate.id}`);
    if (error) {
      toast({ title: 'Cannot delete', description: error, variant: 'destructive' });
    } else {
      toast({ title: 'Deleted', description: `Template "${deletingTemplate.name}" deleted.` });
      setDeletingTemplate(null);
      fetchTemplates();
    }
    setDeleteDialogOpen(false);
  };

  const entityLabel = (value: string) =>
    ENTITY_TYPE_OPTIONS.find((o) => o.value === value)?.label || value;

  if (loading) {
    return <ListItemSkeleton count={3} height="h-16" className="space-y-2" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Compliance Templates</h2>
          <p className="text-sm text-muted-foreground">
            Define typed, grouped governance fields bound to an entity type. Exactly one template
            can be active per entity type.
          </p>
        </div>
        <Button onClick={handleOpenCreate} size="sm">
          <Plus className="mr-1 h-4 w-4" /> Add Template
        </Button>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Entity Type</TableHead>
            <TableHead>Fields</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-32">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {templates.map((template) => (
            <TableRow key={template.id}>
              <TableCell className="font-medium">
                {template.name}
                {template.description && (
                  <div className="text-xs text-muted-foreground">{template.description}</div>
                )}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">{entityLabel(template.entity_type)}</TableCell>
              <TableCell className="text-sm text-muted-foreground">{template.fields?.length ?? 0}</TableCell>
              <TableCell>
                {template.is_active ? (
                  <Badge className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">Active</Badge>
                ) : (
                  <Badge variant="outline">Inactive</Badge>
                )}
              </TableCell>
              <TableCell>
                <div className="flex gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    title={template.is_active ? 'Deactivate' : 'Activate'}
                    onClick={() => handleToggleActive(template)}
                  >
                    {template.is_active ? <PowerOff className="h-3.5 w-3.5" /> : <Power className="h-3.5 w-3.5" />}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-destructive"
                    onClick={() => { setDeletingTemplate(template); setDeleteDialogOpen(true); }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
          {templates.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                No compliance templates configured. Click "Add Template" to create one.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      {/* Create Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Add Compliance Template</DialogTitle>
            <DialogDescription>
              Create a template and optionally add text fields. Activate it to make it available on
              the bound entity type.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="ct-name">Name</Label>
              <Input
                id="ct-name"
                value={formData.name}
                onChange={(e) => setFormData((prev) => ({ ...prev, name: e.target.value }))}
                placeholder="e.g., Terms of Use"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ct-desc">Description</Label>
              <Textarea
                id="ct-desc"
                value={formData.description}
                onChange={(e) => setFormData((prev) => ({ ...prev, description: e.target.value }))}
                placeholder="What this template captures..."
                rows={2}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ct-entity">Entity Type</Label>
              <select
                id="ct-entity"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={formData.entity_type}
                onChange={(e) => setFormData((prev) => ({ ...prev, entity_type: e.target.value }))}
              >
                {ENTITY_TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>Text Fields</Label>
                <Button variant="outline" size="sm" onClick={handleAddDraftField}>
                  <Plus className="mr-1 h-3.5 w-3.5" /> Add Field
                </Button>
              </div>
              {draftFields.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No fields yet. Additional value types are added in later releases.
                </p>
              )}
              {draftFields.map((field, idx) => (
                <div key={idx} className="space-y-2 rounded-md border p-2">
                  <div className="flex items-center gap-2">
                    <Input
                      value={field.label}
                      onChange={(e) =>
                        setDraftFields((prev) => prev.map((f, i) => (i === idx ? { ...f, label: e.target.value } : f)))
                      }
                      placeholder="Field label"
                    />
                    <Input
                      value={field.group_title}
                      onChange={(e) =>
                        setDraftFields((prev) => prev.map((f, i) => (i === idx ? { ...f, group_title: e.target.value } : f)))
                      }
                      placeholder="Group (optional)"
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0"
                      onClick={() => setDraftFields((prev) => prev.filter((_, i) => i !== idx))}
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                  <div className="flex items-center gap-2">
                    <select
                      className="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                      value={field.value_type}
                      onChange={(e) =>
                        setDraftFields((prev) => prev.map((f, i) => (i === idx ? { ...f, value_type: e.target.value } : f)))
                      }
                    >
                      {VALUE_TYPE_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                    {VOCAB_TYPES.has(field.value_type) && (
                      <Input
                        value={field.possible_values}
                        onChange={(e) =>
                          setDraftFields((prev) => prev.map((f, i) => (i === idx ? { ...f, possible_values: e.target.value } : f)))
                        }
                        placeholder="Options (comma-separated)"
                      />
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <Input
                      value={field.hint_text}
                      onChange={(e) =>
                        setDraftFields((prev) => prev.map((f, i) => (i === idx ? { ...f, hint_text: e.target.value } : f)))
                      }
                      placeholder="Hint text (optional)"
                    />
                    <Input
                      value={field.default_value}
                      onChange={(e) =>
                        setDraftFields((prev) => prev.map((f, i) => (i === idx ? { ...f, default_value: e.target.value } : f)))
                      }
                      placeholder="Default (optional)"
                    />
                    <Input
                      value={field.reference_id}
                      onChange={(e) =>
                        setDraftFields((prev) => prev.map((f, i) => (i === idx ? { ...f, reference_id: e.target.value } : f)))
                      }
                      placeholder="Reference id (auto)"
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id={`mandatory-${idx}`}
                      checked={field.is_mandatory}
                      onCheckedChange={(checked) =>
                        setDraftFields((prev) => prev.map((f, i) => (i === idx ? { ...f, is_mandatory: checked === true } : f)))
                      }
                    />
                    <label htmlFor={`mandatory-${idx}`} className="text-sm">Mandatory</label>
                  </div>
                  {field.is_mandatory && field.default_value.trim() && (
                    <p className="text-xs text-amber-600 dark:text-amber-500">
                      This field is mandatory but has a default — the default will satisfy the
                      requirement, so owners can publish without changing it.
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving || !formData.name.trim()}>
              {saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete compliance template?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete "{deletingTemplate?.name}"? Its fields and any stored
              values will be removed. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
