import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Plus, Pencil, Trash2, Loader2, ChevronDown, ChevronRight,
  LockKeyhole, FileText, BookOpen, Activity, ShieldCheck, ExternalLink, Info,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { HoverCard, HoverCardTrigger, HoverCardContent } from '@/components/ui/hover-card';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import type { MaturityLevel, MaturityGate } from '@/types/maturity';

interface CompliancePolicy {
  id: string;
  name: string;
  category: string | null;
  rule: string | null;
  severity: string | null;
  description: string | null;
}

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  'lock-keyhole': LockKeyhole,
  'file-text': FileText,
  'book-open': BookOpen,
  'activity': Activity,
  'shield-check': ShieldCheck,
};
const ICON_OPTIONS = Object.keys(ICON_MAP);

const COLOR_OPTIONS = ['blue', 'cyan', 'green', 'amber', 'purple', 'red', 'emerald', 'slate'];

const ENTITY_TYPE_OPTIONS = [
  { value: 'all', label: 'All Entity Types' },
  { value: 'DataProduct', label: 'Data Products' },
  { value: 'DataContract', label: 'Data Contracts' },
];

const COLOR_CLASSES: Record<string, string> = {
  blue: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  cyan: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200',
  green: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  amber: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
  purple: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
  red: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  emerald: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
  slate: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200',
};

export default function MaturityLevelsSettings() {
  const { toast } = useToast();
  const { get, post, put, delete: apiDelete } = useApi();

  const [levels, setLevels] = useState<MaturityLevel[]>([]);
  const [policies, setPolicies] = useState<CompliancePolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [editingLevel, setEditingLevel] = useState<MaturityLevel | null>(null);
  const [deletingLevel, setDeletingLevel] = useState<MaturityLevel | null>(null);
  const [expandedLevel, setExpandedLevel] = useState<string | null>(null);
  const [addingGateToLevel, setAddingGateToLevel] = useState<string | null>(null);
  const [selectedPolicyId, setSelectedPolicyId] = useState('');
  const [gateRequired, setGateRequired] = useState(true);
  const [formData, setFormData] = useState({
    name: '', description: '', icon: 'shield-check', color: 'blue', entity_type: 'all',
  });
  const [saving, setSaving] = useState(false);
  const hasFetched = useRef(false);

  const fetchLevels = useCallback(async () => {
    try {
      setLoading(true);
      const { data, error } = await get<MaturityLevel[]>('/api/maturity-levels');
      if (error) throw new Error(error);
      const sorted = Array.isArray(data) ? [...data].sort((a, b) => b.level_order - a.level_order) : [];
      setLevels(sorted);
    } catch {
      // silent on initial
    } finally {
      setLoading(false);
    }
  }, [get]);

  const fetchPolicies = useCallback(async () => {
    try {
      const { data } = await get<any>('/api/compliance/policies');
      const list = Array.isArray(data) ? data : (data?.policies ?? data?.items ?? []);
      setPolicies(list);
    } catch { /* non-critical */ }
  }, [get]);

  useEffect(() => {
    if (!hasFetched.current) {
      hasFetched.current = true;
      fetchLevels();
      fetchPolicies();
    }
  }, [fetchLevels, fetchPolicies]);

  const handleOpenCreate = () => {
    setEditingLevel(null);
    setFormData({ name: '', description: '', icon: 'shield-check', color: 'blue', entity_type: 'all' });
    setDialogOpen(true);
  };

  const handleOpenEdit = (level: MaturityLevel) => {
    setEditingLevel(level);
    setFormData({
      name: level.name,
      description: level.description || '',
      icon: level.icon || 'shield-check',
      color: level.color || 'blue',
      entity_type: level.entity_type || 'all',
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!formData.name.trim()) return;
    setSaving(true);
    try {
      if (editingLevel) {
        const { error } = await put(`/api/maturity-levels/${editingLevel.id}`, {
          name: formData.name,
          description: formData.description || null,
          icon: formData.icon,
          color: formData.color,
          entity_type: formData.entity_type,
        });
        if (error) throw new Error(error);
        toast({ title: 'Updated', description: `Maturity level "${formData.name}" updated.` });
      } else {
        const maxOrder = levels.length > 0 ? Math.max(...levels.map(l => l.level_order)) : 0;
        const { error } = await post('/api/maturity-levels', {
          name: formData.name,
          description: formData.description || null,
          icon: formData.icon,
          color: formData.color,
          entity_type: formData.entity_type,
          level_order: maxOrder + 1,
        });
        if (error) throw new Error(error);
        toast({ title: 'Created', description: `Maturity level "${formData.name}" created.` });
      }
      setDialogOpen(false);
      fetchLevels();
    } catch (err: any) {
      toast({ title: 'Error', description: err?.message || 'Failed to save', variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deletingLevel) return;
    const { error } = await apiDelete(`/api/maturity-levels/${deletingLevel.id}`);
    if (error) {
      toast({ title: 'Cannot delete', description: error, variant: 'destructive' });
    } else {
      toast({ title: 'Deleted', description: `Maturity level "${deletingLevel.name}" deleted.` });
      setDeletingLevel(null);
      fetchLevels();
    }
    setDeleteDialogOpen(false);
  };

  const handleMoveUp = async (index: number) => {
    if (index <= 0) return;
    const newLevels = [...levels];
    const prevOrder = newLevels[index - 1].level_order;
    const currOrder = newLevels[index].level_order;
    newLevels[index - 1].level_order = currOrder;
    newLevels[index].level_order = prevOrder;
    const { error } = await put('/api/maturity-levels/reorder', {
      levels: newLevels.map(l => ({ id: l.id, level_order: l.level_order })),
    });
    if (!error) fetchLevels();
  };

  const handleMoveDown = async (index: number) => {
    if (index >= levels.length - 1) return;
    const newLevels = [...levels];
    const nextOrder = newLevels[index + 1].level_order;
    const currOrder = newLevels[index].level_order;
    newLevels[index + 1].level_order = currOrder;
    newLevels[index].level_order = nextOrder;
    const { error } = await put('/api/maturity-levels/reorder', {
      levels: newLevels.map(l => ({ id: l.id, level_order: l.level_order })),
    });
    if (!error) fetchLevels();
  };

  const handleAddGate = async (levelId: string) => {
    if (!selectedPolicyId) return;
    const level = levels.find(l => l.id === levelId);
    const maxOrder = level?.gates?.length ? Math.max(...level.gates.map(g => g.display_order)) + 1 : 0;
    const { error } = await post(`/api/maturity-levels/${levelId}/gates`, {
      compliance_policy_id: selectedPolicyId,
      required: gateRequired,
      display_order: maxOrder,
    });
    if (error) {
      toast({ title: 'Error', description: error, variant: 'destructive' });
    } else {
      setAddingGateToLevel(null);
      setSelectedPolicyId('');
      setGateRequired(true);
      fetchLevels();
    }
  };

  const handleRemoveGate = async (levelId: string, gateId: string) => {
    const { error } = await apiDelete(`/api/maturity-levels/${levelId}/gates/${gateId}`);
    if (!error) fetchLevels();
  };

  const getColorClass = (color: string | null) => COLOR_CLASSES[color || 'blue'] || COLOR_CLASSES.blue;
  const getIcon = (iconName: string | null) => ICON_MAP[iconName || 'shield-check'] || ShieldCheck;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[200px]">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Maturity Levels</h2>
          <p className="text-sm text-muted-foreground">
            Define the maturity ladder for data products and contracts. Each level is gated by compliance policies.
          </p>
        </div>
        <Button onClick={handleOpenCreate} size="sm">
          <Plus className="h-4 w-4 mr-1" /> Add Level
        </Button>
      </div>

      <div className="space-y-2">
        {levels.map((level, index) => {
          const IconComponent = getIcon(level.icon);
          const isExpanded = expandedLevel === level.id;
          return (
            <div key={level.id} className="border rounded-lg">
              <div className="flex items-center gap-3 px-4 py-3">
                <div className="flex flex-col gap-0.5">
                  <button onClick={() => handleMoveUp(index)} disabled={index === 0}
                    className="text-muted-foreground hover:text-foreground disabled:opacity-20 text-xs">▲</button>
                  <button onClick={() => handleMoveDown(index)} disabled={index === levels.length - 1}
                    className="text-muted-foreground hover:text-foreground disabled:opacity-20 text-xs">▼</button>
                </div>
                <button onClick={() => setExpandedLevel(isExpanded ? null : level.id)}
                  className="flex items-center gap-2 flex-1 text-left">
                  {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  <span className="font-mono text-sm text-muted-foreground w-6">{level.level_order}</span>
                  <Badge variant="outline" className={getColorClass(level.color)}>
                    <IconComponent className="h-3 w-3 mr-1" />
                    {level.name}
                  </Badge>
                  <span className="text-sm text-muted-foreground flex-1">{level.description || ''}</span>
                  <Badge variant="secondary" className="text-xs">
                    {level.entity_type === 'all' ? 'All types' : level.entity_type}
                  </Badge>
                  <span className="text-xs text-muted-foreground">{level.gates?.length || 0} gate(s)</span>
                </button>
                <div className="flex gap-1">
                  <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => handleOpenEdit(level)}>
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive"
                    onClick={() => { setDeletingLevel(level); setDeleteDialogOpen(true); }}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>

              {isExpanded && (
                <div className="border-t px-4 py-3 bg-muted/30 space-y-2">
                  <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    Compliance Policy Gates
                  </div>
                  {(level.gates || []).map((gate: MaturityGate) => {
                    const policy = policies.find(p => p.id === gate.compliance_policy_id);
                    return (
                      <div key={gate.id} className="flex items-center gap-3 pl-4 py-1.5 border-b last:border-b-0 border-border/40">
                        <span className={`h-2 w-2 rounded-full shrink-0 ${gate.required ? 'bg-red-500' : 'bg-amber-500'}`} />
                        <HoverCard openDelay={200}>
                          <HoverCardTrigger asChild>
                            <button className="text-sm font-medium flex-1 text-left hover:underline underline-offset-2 decoration-dashed inline-flex items-center gap-1.5">
                              {gate.compliance_policy_name || gate.compliance_policy_id}
                              <Info className="h-3 w-3 text-muted-foreground" />
                            </button>
                          </HoverCardTrigger>
                          <HoverCardContent className="w-80" side="right" align="start">
                            <div className="space-y-2">
                              <p className="text-sm font-semibold">{gate.compliance_policy_name}</p>
                              {(policy?.description || gate.compliance_policy_rule) && (
                                <p className="text-xs text-muted-foreground">
                                  {policy?.description || 'No description'}
                                </p>
                              )}
                              {gate.compliance_policy_rule && (
                                <code className="block text-xs bg-muted px-2 py-1.5 rounded font-mono whitespace-pre-wrap">
                                  {gate.compliance_policy_rule}
                                </code>
                              )}
                              <div className="flex items-center gap-2 pt-1">
                                {policy?.severity && (
                                  <Badge variant="outline" className="text-xs capitalize">{policy.severity}</Badge>
                                )}
                                <Badge variant="outline" className="text-xs">
                                  {gate.required ? 'Required' : 'Advisory'}
                                </Badge>
                              </div>
                              <a href={`/compliance?policy=${gate.compliance_policy_id}`}
                                className="inline-flex items-center gap-1 text-xs text-primary hover:underline pt-1">
                                <ExternalLink className="h-3 w-3" />
                                View in Compliance
                              </a>
                            </div>
                          </HoverCardContent>
                        </HoverCard>
                        <Badge variant="outline" className="text-xs shrink-0">
                          {gate.required ? 'Required' : 'Advisory'}
                        </Badge>
                        <Button variant="ghost" size="icon" className="h-6 w-6 text-destructive shrink-0"
                          onClick={() => handleRemoveGate(level.id, gate.id)}>
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    );
                  })}

                  {addingGateToLevel === level.id ? (
                    <div className="flex items-center gap-2 pl-4 pt-2">
                      <Select value={selectedPolicyId} onValueChange={setSelectedPolicyId}>
                        <SelectTrigger className="flex-1 h-8 text-sm">
                          <SelectValue placeholder="Select compliance policy..." />
                        </SelectTrigger>
                        <SelectContent>
                          {policies.map(p => (
                            <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <div className="flex items-center gap-1.5">
                        <Switch checked={gateRequired} onCheckedChange={setGateRequired} id="gate-req" />
                        <Label htmlFor="gate-req" className="text-xs">Required</Label>
                      </div>
                      <Button size="sm" variant="outline" className="h-8"
                        onClick={() => handleAddGate(level.id)} disabled={!selectedPolicyId}>Add</Button>
                      <Button size="sm" variant="ghost" className="h-8"
                        onClick={() => { setAddingGateToLevel(null); setSelectedPolicyId(''); }}>Cancel</Button>
                    </div>
                  ) : (
                    <Button variant="ghost" size="sm" className="ml-4 text-xs"
                      onClick={() => { setAddingGateToLevel(level.id); setSelectedPolicyId(''); setGateRequired(true); }}>
                      <Plus className="h-3 w-3 mr-1" /> Add Gate
                    </Button>
                  )}
                </div>
              )}
            </div>
          );
        })}
        {levels.length === 0 && (
          <div className="text-center text-muted-foreground py-8 border rounded-lg">
            No maturity levels configured. Click "Add Level" to create one.
          </div>
        )}
      </div>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingLevel ? 'Edit' : 'Add'} Maturity Level</DialogTitle>
            <DialogDescription>
              {editingLevel ? 'Update the maturity level details.' : 'Create a new maturity level.'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="mat-name">Name</Label>
              <Input id="mat-name" value={formData.name}
                onChange={e => setFormData(prev => ({ ...prev, name: e.target.value }))}
                placeholder="e.g., Trusted" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="mat-desc">Description</Label>
              <Textarea id="mat-desc" value={formData.description}
                onChange={e => setFormData(prev => ({ ...prev, description: e.target.value }))}
                placeholder="What this level represents..." rows={2} />
            </div>
            <div className="space-y-2">
              <Label>Entity Type</Label>
              <Select value={formData.entity_type}
                onValueChange={v => setFormData(prev => ({ ...prev, entity_type: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {ENTITY_TYPE_OPTIONS.map(o => (
                    <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Icon</Label>
              <div className="flex flex-wrap gap-2">
                {ICON_OPTIONS.map(ic => {
                  const Ic = ICON_MAP[ic];
                  return (
                    <button key={ic}
                      onClick={() => setFormData(prev => ({ ...prev, icon: ic }))}
                      className={`p-2 rounded border-2 transition-colors ${formData.icon === ic ? 'border-foreground bg-muted' : 'border-transparent'}`}>
                      <Ic className="h-4 w-4" />
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="space-y-2">
              <Label>Color</Label>
              <div className="flex flex-wrap gap-2">
                {COLOR_OPTIONS.map(c => (
                  <button key={c}
                    onClick={() => setFormData(prev => ({ ...prev, color: c }))}
                    className={`px-3 py-1 rounded text-xs font-medium border-2 transition-colors ${getColorClass(c)} ${formData.color === c ? 'border-foreground' : 'border-transparent'}`}>
                    {c}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <Label>Preview</Label>
              <div>
                <Badge variant="outline" className={getColorClass(formData.color)}>
                  {(() => { const Ic = getIcon(formData.icon); return <Ic className="h-3 w-3 mr-1" />; })()}
                  {formData.name || 'Level Name'}
                </Badge>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving || !formData.name.trim()}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
              {editingLevel ? 'Update' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete maturity level?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete "{deletingLevel?.name}"? This cannot be undone.
              If snapshots reference this level, deletion will be blocked.
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
