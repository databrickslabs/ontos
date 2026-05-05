import { useState, useEffect, useCallback, useRef } from 'react';
import { Plus, Pencil, Trash2, Shield, ShieldCheck, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
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

interface CertificationLevel {
  id: string;
  level_order: number;
  name: string;
  description: string | null;
  icon: string | null;
  color: string | null;
}

const ICON_MAP: Record<string, typeof Shield> = {
  shield: Shield,
  'shield-check': ShieldCheck,
};

const COLOR_OPTIONS = ['amber', 'slate', 'yellow', 'green', 'blue', 'purple', 'red', 'emerald'];

export default function CertificationLevelsSettings() {
  const { toast } = useToast();
  const { get, post, put, delete: apiDelete } = useApi();

  const [levels, setLevels] = useState<CertificationLevel[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [editingLevel, setEditingLevel] = useState<CertificationLevel | null>(null);
  const [deletingLevel, setDeletingLevel] = useState<CertificationLevel | null>(null);
  const [formData, setFormData] = useState({ name: '', description: '', icon: 'shield-check', color: 'amber' });
  const [saving, setSaving] = useState(false);
  const hasFetched = useRef(false);

  const fetchLevels = useCallback(async () => {
    try {
      setLoading(true);
      const { data, error } = await get<CertificationLevel[]>('/api/certification-levels');
      if (error) throw new Error(error);
      setLevels(Array.isArray(data) ? data : []);
    } catch {
      // Only toast on non-initial loads to avoid flash
    } finally {
      setLoading(false);
    }
  }, [get]);

  useEffect(() => {
    if (!hasFetched.current) {
      hasFetched.current = true;
      fetchLevels();
    }
  }, [fetchLevels]);

  const handleOpenCreate = () => {
    setEditingLevel(null);
    setFormData({ name: '', description: '', icon: 'shield-check', color: 'amber' });
    setDialogOpen(true);
  };

  const handleOpenEdit = (level: CertificationLevel) => {
    setEditingLevel(level);
    setFormData({
      name: level.name,
      description: level.description || '',
      icon: level.icon || 'shield-check',
      color: level.color || 'amber',
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!formData.name.trim()) return;
    setSaving(true);
    try {
      if (editingLevel) {
        const { error } = await put(`/api/certification-levels/${editingLevel.id}`, {
          name: formData.name,
          description: formData.description || null,
          icon: formData.icon,
          color: formData.color,
        });
        if (error) throw new Error(error);
        toast({ title: 'Updated', description: `Certification level "${formData.name}" updated.` });
      } else {
        const maxOrder = levels.length > 0 ? Math.max(...levels.map(l => l.level_order)) : 0;
        const { error } = await post('/api/certification-levels', {
          name: formData.name,
          description: formData.description || null,
          icon: formData.icon,
          color: formData.color,
          level_order: maxOrder + 1,
        });
        if (error) throw new Error(error);
        toast({ title: 'Created', description: `Certification level "${formData.name}" created.` });
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
    const { error } = await apiDelete(`/api/certification-levels/${deletingLevel.id}`);
    if (error) {
      toast({ title: 'Cannot delete', description: error, variant: 'destructive' });
    } else {
      toast({ title: 'Deleted', description: `Certification level "${deletingLevel.name}" deleted.` });
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
    const { error } = await put('/api/certification-levels/reorder', {
      levels: newLevels.map(l => ({ id: l.id, level_order: l.level_order })),
    });
    if (error) {
      toast({ title: 'Error', description: 'Failed to reorder', variant: 'destructive' });
    } else {
      fetchLevels();
    }
  };

  const handleMoveDown = async (index: number) => {
    if (index >= levels.length - 1) return;
    const newLevels = [...levels];
    const nextOrder = newLevels[index + 1].level_order;
    const currOrder = newLevels[index].level_order;
    newLevels[index + 1].level_order = currOrder;
    newLevels[index].level_order = nextOrder;
    const { error } = await put('/api/certification-levels/reorder', {
      levels: newLevels.map(l => ({ id: l.id, level_order: l.level_order })),
    });
    if (error) {
      toast({ title: 'Error', description: 'Failed to reorder', variant: 'destructive' });
    } else {
      fetchLevels();
    }
  };

  const getColorClass = (color: string | null) => {
    const map: Record<string, string> = {
      amber: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
      slate: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200',
      yellow: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
      green: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
      blue: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
      purple: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
      red: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
      emerald: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
    };
    return map[color || 'amber'] || map.amber;
  };

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
          <h2 className="text-lg font-semibold">Certification Levels</h2>
          <p className="text-sm text-muted-foreground">
            Define the certification levels available for data products, contracts, and assets.
          </p>
        </div>
        <Button onClick={handleOpenCreate} size="sm">
          <Plus className="h-4 w-4 mr-1" /> Add Level
        </Button>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-12"></TableHead>
            <TableHead className="w-16">Order</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>Description</TableHead>
            <TableHead>Preview</TableHead>
            <TableHead className="w-24">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {levels.map((level, index) => {
            const IconComponent = ICON_MAP[level.icon || 'shield-check'] || ShieldCheck;
            return (
              <TableRow key={level.id}>
                <TableCell>
                  <div className="flex flex-col gap-0.5">
                    <button
                      onClick={() => handleMoveUp(index)}
                      disabled={index === 0}
                      className="text-muted-foreground hover:text-foreground disabled:opacity-20 text-xs"
                    >
                      ▲
                    </button>
                    <button
                      onClick={() => handleMoveDown(index)}
                      disabled={index === levels.length - 1}
                      className="text-muted-foreground hover:text-foreground disabled:opacity-20 text-xs"
                    >
                      ▼
                    </button>
                  </div>
                </TableCell>
                <TableCell className="font-mono text-muted-foreground">{level.level_order}</TableCell>
                <TableCell className="font-medium">{level.name}</TableCell>
                <TableCell className="text-sm text-muted-foreground">{level.description || '—'}</TableCell>
                <TableCell>
                  <Badge variant="outline" className={getColorClass(level.color)}>
                    <IconComponent className="h-3 w-3 mr-1" />
                    {level.name}
                  </Badge>
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => handleOpenEdit(level)}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-destructive"
                      onClick={() => { setDeletingLevel(level); setDeleteDialogOpen(true); }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
          {levels.length === 0 && (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                No certification levels configured. Click "Add Level" to create one.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingLevel ? 'Edit' : 'Add'} Certification Level</DialogTitle>
            <DialogDescription>
              {editingLevel ? 'Update the certification level details.' : 'Create a new certification level.'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="cert-name">Name</Label>
              <Input
                id="cert-name"
                value={formData.name}
                onChange={e => setFormData(prev => ({ ...prev, name: e.target.value }))}
                placeholder="e.g., Gold"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cert-desc">Description</Label>
              <Textarea
                id="cert-desc"
                value={formData.description}
                onChange={e => setFormData(prev => ({ ...prev, description: e.target.value }))}
                placeholder="What this level represents..."
                rows={2}
              />
            </div>
            <div className="space-y-2">
              <Label>Color</Label>
              <div className="flex flex-wrap gap-2">
                {COLOR_OPTIONS.map(c => (
                  <button
                    key={c}
                    onClick={() => setFormData(prev => ({ ...prev, color: c }))}
                    className={`px-3 py-1 rounded text-xs font-medium border-2 transition-colors ${getColorClass(c)} ${formData.color === c ? 'border-foreground' : 'border-transparent'}`}
                  >
                    {c}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <Label>Preview</Label>
              <div>
                <Badge variant="outline" className={getColorClass(formData.color)}>
                  <ShieldCheck className="h-3 w-3 mr-1" />
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
            <AlertDialogTitle>Delete certification level?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete "{deletingLevel?.name}"? This cannot be undone.
              If entities are certified at this level, deletion will be blocked.
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
