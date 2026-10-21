import { useState, useEffect, useCallback } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { ColumnDef } from '@tanstack/react-table';
import { MoreHorizontal, Plus, Trash2, Edit, Settings, Tag, Hash, Users, Loader2, AlertCircle, Eye } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { DataTable } from '@/components/ui/data-table';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { PrincipalPicker } from '@/components/common/principal-picker';
import { RelativeDate } from '@/components/common/relative-date';
import { useAppSettingsStore } from '@/stores/app-settings-store';

// Types based on backend models
interface TagNamespace {
  id: string;
  name: string;
  description?: string;
  created_by?: string;
  created_at: string;
  updated_at: string;
}

interface Tag {
  id: string;
  name: string;
  description?: string;
  possible_values?: string[];
  status: 'active' | 'draft' | 'candidate' | 'deprecated' | 'inactive' | 'retired';
  version?: string;
  namespace_id: string;
  namespace_name?: string;
  parent_id?: string;
  fully_qualified_name: string;
  created_by?: string;
  created_at: string;
  updated_at: string;
}

interface TagNamespacePermission {
  id: string;
  namespace_id: string;
  group_id: string;
  access_level: 'read_only' | 'read_write' | 'admin';
  created_by?: string;
  created_at: string;
  updated_at: string;
}

// Form interfaces
interface NamespaceFormData {
  name: string;
  description: string;
}

interface TagFormData {
  name: string;
  description: string;
  possible_values: string;
  status: string;
  version: string;
  parent_id?: string;
}

interface PermissionFormData {
  group_id: string;
  access_level: string;
}

export default function TagsSettings() {
  const { get, post, put, delete: deleteApi, loading } = useApi();
  const { t } = useTranslation(['settings', 'common']);
  const { toast } = useToast();
  const { setTagDisplayFormat: setGlobalTagDisplayFormat } = useAppSettingsStore();

  // State
  const [namespaces, setNamespaces] = useState<TagNamespace[]>([]);
  const [selectedNamespace, setSelectedNamespace] = useState<string>('');
  const [tags, setTags] = useState<Tag[]>([]);
  const [permissions, setPermissions] = useState<TagNamespacePermission[]>([]);
  
  // Tag display format setting
  const [tagDisplayFormat, setTagDisplayFormat] = useState<'short' | 'long'>('short');
  const [isLoadingDisplayFormat, setIsLoadingDisplayFormat] = useState(false);
  const [isSavingDisplayFormat, setIsSavingDisplayFormat] = useState(false);

  // Dialog states
  const [isNamespaceDialogOpen, setIsNamespaceDialogOpen] = useState(false);
  const [isTagDialogOpen, setIsTagDialogOpen] = useState(false);
  const [isPermissionDialogOpen, setIsPermissionDialogOpen] = useState(false);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);

  // Form states
  const [editingNamespace, setEditingNamespace] = useState<TagNamespace | null>(null);
  const [editingTag, setEditingTag] = useState<Tag | null>(null);
  const [editingPermission, setEditingPermission] = useState<TagNamespacePermission | null>(null);
  const [deletingItem, setDeletingItem] = useState<{ type: string; id: string; name: string } | null>(null);

  const [namespaceForm, setNamespaceForm] = useState<NamespaceFormData>({ name: '', description: '' });
  const [tagForm, setTagForm] = useState<TagFormData>({
    name: '',
    description: '',
    possible_values: '',
    status: 'active',
    version: '',
    parent_id: undefined,
  });
  const [permissionForm, setPermissionForm] = useState<PermissionFormData>({ group_id: '', access_level: 'read_only' });

  const [error, setError] = useState<string | null>(null);

  // Fetch data
  const fetchNamespaces = useCallback(async () => {
    try {
      const response = await get<TagNamespace[]>('/api/tags/namespaces');
      if (response.data) {
        setNamespaces(response.data);
        if (response.data.length > 0 && !selectedNamespace) {
          setSelectedNamespace(response.data[0].id);
        }
      }
    } catch (err: any) {
      setError(err.message);
      toast({ variant: 'destructive', title: t('settings:tags.toasts.fetchNamespacesError'), description: err.message });
    }
  }, [get, toast, selectedNamespace]);

  const fetchTags = useCallback(async () => {
    if (!selectedNamespace) return;
    try {
      const response = await get<Tag[]>(`/api/tags?namespace_id=${selectedNamespace}&limit=1000`);
      if (response.data) {
        setTags(response.data);
      }
    } catch (err: any) {
      setError(err.message);
      toast({ variant: 'destructive', title: t('settings:tags.toasts.fetchTagsError'), description: err.message });
    }
  }, [get, toast, selectedNamespace]);

  const fetchPermissions = useCallback(async () => {
    if (!selectedNamespace) return;
    try {
      const response = await get<TagNamespacePermission[]>(`/api/tags/namespaces/${selectedNamespace}/permissions`);
      if (response.data) {
        setPermissions(response.data);
      }
    } catch (err: any) {
      setError(err.message);
      toast({ variant: 'destructive', title: t('settings:tags.toasts.fetchPermissionsError'), description: err.message });
    }
  }, [get, toast, selectedNamespace]);

  // Fetch tag display format setting
  const fetchDisplayFormat = useCallback(async () => {
    setIsLoadingDisplayFormat(true);
    try {
      const response = await get<{ tag_display_format?: string }>('/api/settings');
      if (response.data?.tag_display_format) {
        setTagDisplayFormat(response.data.tag_display_format as 'short' | 'long');
      }
    } catch (err: any) {
      console.error('Error fetching display format:', err);
    } finally {
      setIsLoadingDisplayFormat(false);
    }
  }, [get]);

  // Save tag display format setting
  const saveDisplayFormat = async (format: 'short' | 'long') => {
    setIsSavingDisplayFormat(true);
    try {
      await put('/api/settings', { tag_display_format: format });
      setTagDisplayFormat(format);
      // Also update the global store so all TagChips update immediately
      setGlobalTagDisplayFormat(format);
      toast({ title: t('settings:tags.toasts.displayFormatUpdated') });
    } catch (err: any) {
      toast({ variant: 'destructive', title: t('settings:tags.toasts.displayFormatError'), description: err.message });
    } finally {
      setIsSavingDisplayFormat(false);
    }
  };

  useEffect(() => {
    fetchNamespaces();
    fetchDisplayFormat();
  }, [fetchNamespaces, fetchDisplayFormat]);

  useEffect(() => {
    if (selectedNamespace) {
      fetchTags();
      fetchPermissions();
    }
  }, [selectedNamespace, fetchTags, fetchPermissions]);

  // Namespace operations
  const openNamespaceDialog = (namespace?: TagNamespace) => {
    setEditingNamespace(namespace || null);
    setNamespaceForm({
      name: namespace?.name || '',
      description: namespace?.description || '',
    });
    setIsNamespaceDialogOpen(true);
  };

  const handleNamespaceSubmit = async () => {
    try {
      if (editingNamespace) {
        await put(`/api/tags/namespaces/${editingNamespace.id}`, namespaceForm);
        toast({ title: t('settings:tags.toasts.namespaceUpdated') });
      } else {
        await post('/api/tags/namespaces', namespaceForm);
        toast({ title: t('settings:tags.toasts.namespaceCreated') });
      }
      setIsNamespaceDialogOpen(false);
      fetchNamespaces();
    } catch (err: any) {
      toast({ variant: 'destructive', title: t('settings:tags.toasts.namespaceSaveError'), description: err.message });
    }
  };

  // Tag operations
  const openTagDialog = (tag?: Tag) => {
    setEditingTag(tag || null);
    setTagForm({
      name: tag?.name || '',
      description: tag?.description || '',
      possible_values: tag?.possible_values ? JSON.stringify(tag.possible_values) : '',
      status: tag?.status || 'active',
      version: tag?.version || '',
      parent_id: tag?.parent_id,
    });
    setIsTagDialogOpen(true);
  };

  const handleTagSubmit = async () => {
    try {
      const payload = {
        ...tagForm,
        namespace_id: selectedNamespace,
        possible_values: tagForm.possible_values ? JSON.parse(tagForm.possible_values) : undefined,
      };

      if (editingTag) {
        await put(`/api/tags/${editingTag.id}`, payload);
        toast({ title: t('settings:tags.toasts.tagUpdated') });
      } else {
        await post('/api/tags', payload);
        toast({ title: t('settings:tags.toasts.tagCreated') });
      }
      setIsTagDialogOpen(false);
      fetchTags();
    } catch (err: any) {
      toast({ variant: 'destructive', title: t('settings:tags.toasts.tagSaveError'), description: err.message });
    }
  };

  // Permission operations
  const openPermissionDialog = (permission?: TagNamespacePermission) => {
    setEditingPermission(permission || null);
    setPermissionForm({
      group_id: permission?.group_id || '',
      access_level: permission?.access_level || 'read_only',
    });
    setIsPermissionDialogOpen(true);
  };

  const handlePermissionSubmit = async () => {
    try {
      if (editingPermission) {
        await put(`/api/tags/namespaces/${selectedNamespace}/permissions/${editingPermission.id}`, permissionForm);
        toast({ title: t('settings:tags.toasts.permissionUpdated') });
      } else {
        await post(`/api/tags/namespaces/${selectedNamespace}/permissions`, permissionForm);
        toast({ title: t('settings:tags.toasts.permissionCreated') });
      }
      setIsPermissionDialogOpen(false);
      fetchPermissions();
    } catch (err: any) {
      toast({ variant: 'destructive', title: t('settings:tags.toasts.permissionSaveError'), description: err.message });
    }
  };

  // Delete operations
  const openDeleteDialog = (type: string, id: string, name: string) => {
    setDeletingItem({ type, id, name });
    setIsDeleteDialogOpen(true);
  };

  const handleDelete = async () => {
    if (!deletingItem) return;

    try {
      if (deletingItem.type === 'namespace') {
        await deleteApi(`/api/tags/namespaces/${deletingItem.id}`);
        fetchNamespaces();
        setSelectedNamespace('');
      } else if (deletingItem.type === 'tag') {
        await deleteApi(`/api/tags/${deletingItem.id}`);
        fetchTags();
      } else if (deletingItem.type === 'permission') {
        await deleteApi(`/api/tags/namespaces/${selectedNamespace}/permissions/${deletingItem.id}`);
        fetchPermissions();
      }
      toast({ title: t('settings:tags.toasts.deleteSuccess', { type: deletingItem.type }) });
      setIsDeleteDialogOpen(false);
      setDeletingItem(null);
    } catch (err: any) {
      toast({ variant: 'destructive', title: t('settings:tags.toasts.deleteError'), description: err.message });
    }
  };

  // Table columns
  const tagColumns: ColumnDef<Tag>[] = [
    {
      accessorKey: 'name',
      header: t('common:labels.name'),
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <Tag className="h-4 w-4" />
          <span className="font-medium">{row.original.name}</span>
        </div>
      ),
    },
    {
      accessorKey: 'description',
      header: t('common:labels.description'),
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">{row.original.description || '—'}</span>
      ),
    },
    {
      accessorKey: 'status',
      header: t('common:labels.status'),
      cell: ({ row }) => (
        <Badge variant={row.original.status === 'active' ? 'default' : 'secondary'}>
          {row.original.status}
        </Badge>
      ),
    },
    {
      accessorKey: 'version',
      header: t('common:labels.version'),
      cell: ({ row }) => (
        <span className="text-sm">{row.original.version || '—'}</span>
      ),
    },
    {
      accessorKey: 'updated_at',
      header: t('common:labels.updated'),
      cell: ({ row }) => <RelativeDate date={row.original.updated_at} />,
    },
    {
      id: 'actions',
      cell: ({ row }) => (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="h-8 w-8 p-0">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>{t('common:labels.actions')}</DropdownMenuLabel>
            <DropdownMenuItem onClick={() => openTagDialog(row.original)}>
              <Edit className="mr-2 h-4 w-4" />
              {t('common:actions.edit')}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive"
              onClick={() => openDeleteDialog('tag', row.original.id, row.original.name)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              {t('common:actions.delete')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ),
    },
  ];

  const permissionColumns: ColumnDef<TagNamespacePermission>[] = [
    {
      accessorKey: 'group_id',
      header: t('settings:tags.columns.group'),
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4" />
          <span className="font-medium">{row.original.group_id}</span>
        </div>
      ),
    },
    {
      accessorKey: 'access_level',
      header: t('settings:tags.columns.accessLevel'),
      cell: ({ row }) => (
        <Badge variant={row.original.access_level === 'admin' ? 'destructive' : 'default'}>
          {row.original.access_level}
        </Badge>
      ),
    },
    {
      accessorKey: 'updated_at',
      header: t('common:labels.updated'),
      cell: ({ row }) => <RelativeDate date={row.original.updated_at} />,
    },
    {
      id: 'actions',
      cell: ({ row }) => (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="h-8 w-8 p-0">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>{t('common:labels.actions')}</DropdownMenuLabel>
            <DropdownMenuItem onClick={() => openPermissionDialog(row.original)}>
              <Edit className="mr-2 h-4 w-4" />
              {t('common:actions.edit')}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive"
              onClick={() => openDeleteDialog('permission', row.original.id, row.original.group_id)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              {t('common:actions.delete')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ),
    },
  ];

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  return (
    <>
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Tag className="w-8 h-8" />
          {t('settings:tags.title')}
        </h1>
        <p className="text-muted-foreground mt-1">
          {t('settings:tags.description')}
        </p>
      </div>

    <div className="space-y-6">
      {/* Tag Display Settings */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Eye className="h-5 w-5" />
                {t('settings:tags.display.title')}
              </CardTitle>
              <CardDescription>
                {t('settings:tags.display.description')}
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4">
            <Label htmlFor="display-format-select">{t('settings:tags.display.formatLabel')}</Label>
            <Select 
              value={tagDisplayFormat} 
              onValueChange={(value: 'short' | 'long') => saveDisplayFormat(value)}
              disabled={isLoadingDisplayFormat || isSavingDisplayFormat}
            >
              <SelectTrigger id="display-format-select" className="w-[240px]">
                <SelectValue placeholder={t('settings:tags.display.formatPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="short" className="whitespace-nowrap">{t('settings:tags.display.short')}</SelectItem>
                <SelectItem value="long" className="whitespace-nowrap">{t('settings:tags.display.long')}</SelectItem>
              </SelectContent>
            </Select>
            {(isLoadingDisplayFormat || isSavingDisplayFormat) && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-2">
            <Trans
              i18nKey="settings:tags.display.help"
              components={{ strong: <strong />, br: <br /> }}
            />
          </p>
        </CardContent>
      </Card>

      {/* Namespaces Management */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Hash className="h-5 w-5" />
                {t('settings:tags.namespaces.title')}
              </CardTitle>
              <CardDescription>
                {t('settings:tags.namespaces.description')}
              </CardDescription>
            </div>
            <Button onClick={() => openNamespaceDialog()}>
              <Plus className="mr-2 h-4 w-4" />
              {t('settings:tags.namespaces.add')}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4 mb-4">
            <Label htmlFor="namespace-select">{t('settings:tags.namespaces.activeLabel')}</Label>
            <Select value={selectedNamespace} onValueChange={setSelectedNamespace}>
              <SelectTrigger id="namespace-select" className="w-[200px]">
                <SelectValue placeholder={t('settings:tags.namespaces.selectPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {namespaces.map((ns) => (
                  <SelectItem key={ns.id} value={ns.id}>
                    {ns.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {selectedNamespace && (
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => openNamespaceDialog(namespaces.find(ns => ns.id === selectedNamespace))}
                >
                  <Edit className="mr-2 h-4 w-4" />
                  {t('common:actions.edit')}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    const ns = namespaces.find(ns => ns.id === selectedNamespace);
                    if (ns) openDeleteDialog('namespace', ns.id, ns.name);
                  }}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  {t('common:actions.delete')}
                </Button>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {selectedNamespace && (
        <>
          {/* Tags Management */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <Tag className="h-5 w-5" />
                    {t('settings:tags.title')}
                  </CardTitle>
                  <CardDescription>
                    {t('settings:tags.list.description')}
                  </CardDescription>
                </div>
                <Button onClick={() => openTagDialog()}>
                  <Plus className="mr-2 h-4 w-4" />
                  {t('settings:tags.list.add')}
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <DataTable columns={tagColumns} data={tags} />
            </CardContent>
          </Card>

          {/* Permissions Management */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <Settings className="h-5 w-5" />
                    {t('settings:tags.permissions.title')}
                  </CardTitle>
                  <CardDescription>
                    {t('settings:tags.permissions.description')}
                  </CardDescription>
                </div>
                <Button onClick={() => openPermissionDialog()}>
                  <Plus className="mr-2 h-4 w-4" />
                  {t('settings:tags.permissions.add')}
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <DataTable columns={permissionColumns} data={permissions} />
            </CardContent>
          </Card>
        </>
      )}

      {/* Namespace Dialog */}
      <Dialog open={isNamespaceDialogOpen} onOpenChange={setIsNamespaceDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingNamespace ? t('settings:tags.namespaceDialog.editTitle') : t('settings:tags.namespaceDialog.createTitle')}</DialogTitle>
            <DialogDescription>
              {editingNamespace ? t('settings:tags.namespaceDialog.editDescription') : t('settings:tags.namespaceDialog.createDescription')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="namespace-name">{t('common:labels.name')}</Label>
              <Input
                id="namespace-name"
                value={namespaceForm.name}
                onChange={(e) => setNamespaceForm({ ...namespaceForm, name: e.target.value })}
                placeholder={t('settings:tags.namespaceDialog.namePlaceholder')}
              />
            </div>
            <div>
              <Label htmlFor="namespace-description">{t('common:labels.description')}</Label>
              <Textarea
                id="namespace-description"
                value={namespaceForm.description}
                onChange={(e) => setNamespaceForm({ ...namespaceForm, description: e.target.value })}
                placeholder={t('settings:tags.namespaceDialog.descriptionPlaceholder')}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsNamespaceDialogOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button onClick={handleNamespaceSubmit} disabled={loading || !namespaceForm.name}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editingNamespace ? t('common:actions.update') : t('common:actions.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Tag Dialog */}
      <Dialog open={isTagDialogOpen} onOpenChange={setIsTagDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editingTag ? t('settings:tags.tagDialog.editTitle') : t('settings:tags.tagDialog.createTitle')}</DialogTitle>
            <DialogDescription>
              {editingTag ? t('settings:tags.tagDialog.editDescription') : t('settings:tags.tagDialog.createDescription')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="tag-name">{t('common:labels.name')}</Label>
                <Input
                  id="tag-name"
                  value={tagForm.name}
                  onChange={(e) => setTagForm({ ...tagForm, name: e.target.value })}
                  placeholder={t('settings:tags.tagDialog.namePlaceholder')}
                />
              </div>
              <div>
                <Label htmlFor="tag-status">{t('common:labels.status')}</Label>
                <Select value={tagForm.status} onValueChange={(value) => setTagForm({ ...tagForm, status: value })}>
                  <SelectTrigger id="tag-status">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="active">{t('settings:tags.tagDialog.statuses.active')}</SelectItem>
                    <SelectItem value="draft">{t('settings:tags.tagDialog.statuses.draft')}</SelectItem>
                    <SelectItem value="candidate">{t('settings:tags.tagDialog.statuses.candidate')}</SelectItem>
                    <SelectItem value="deprecated">{t('settings:tags.tagDialog.statuses.deprecated')}</SelectItem>
                    <SelectItem value="inactive">{t('settings:tags.tagDialog.statuses.inactive')}</SelectItem>
                    <SelectItem value="retired">{t('settings:tags.tagDialog.statuses.retired')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label htmlFor="tag-description">{t('common:labels.description')}</Label>
              <Textarea
                id="tag-description"
                value={tagForm.description}
                onChange={(e) => setTagForm({ ...tagForm, description: e.target.value })}
                placeholder={t('settings:tags.tagDialog.descriptionPlaceholder')}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="tag-version">{t('common:labels.version')}</Label>
                <Input
                  id="tag-version"
                  value={tagForm.version}
                  onChange={(e) => setTagForm({ ...tagForm, version: e.target.value })}
                  placeholder={t('settings:tags.tagDialog.versionPlaceholder')}
                />
              </div>
              <div>
                <Label htmlFor="tag-parent">{t('settings:tags.tagDialog.parentLabel')}</Label>
                <Select value={tagForm.parent_id || '__none__'} onValueChange={(value) => setTagForm({ ...tagForm, parent_id: value === '__none__' ? undefined : value })}>
                  <SelectTrigger id="tag-parent">
                    <SelectValue placeholder={t('common:states.none')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">{t('common:states.none')}</SelectItem>
                    {tags.filter(t => t.id !== editingTag?.id).map((tag) => (
                      <SelectItem key={tag.id} value={tag.id}>
                        {tag.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label htmlFor="tag-possible-values">{t('settings:tags.tagDialog.possibleValuesLabel')}</Label>
              <Textarea
                id="tag-possible-values"
                value={tagForm.possible_values}
                onChange={(e) => setTagForm({ ...tagForm, possible_values: e.target.value })}
                placeholder='["value1", "value2", "value3"]'
              />
              <p className="text-sm text-muted-foreground mt-1">
                {t('settings:tags.tagDialog.possibleValuesHelp')}
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsTagDialogOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button onClick={handleTagSubmit} disabled={loading || !tagForm.name}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editingTag ? t('common:actions.update') : t('common:actions.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Permission Dialog */}
      <Dialog open={isPermissionDialogOpen} onOpenChange={setIsPermissionDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingPermission ? t('settings:tags.permissionDialog.editTitle') : t('settings:tags.permissionDialog.addTitle')}</DialogTitle>
            <DialogDescription>
              {editingPermission ? t('settings:tags.permissionDialog.editDescription') : t('settings:tags.permissionDialog.addDescription')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="permission-group">{t('settings:tags.permissionDialog.groupLabel')}</Label>
              <PrincipalPicker
                id="permission-group"
                accepts={['group']}
                value={permissionForm.group_id || null}
                onChange={(next) => setPermissionForm({ ...permissionForm, group_id: next ?? '' })}
                placeholder={t('settings:tags.permissionDialog.groupPlaceholder')}
                aria-label={t('settings:tags.permissionDialog.groupLabel')}
              />
            </div>
            <div>
              <Label htmlFor="permission-access">{t('settings:tags.columns.accessLevel')}</Label>
              <Select value={permissionForm.access_level} onValueChange={(value) => setPermissionForm({ ...permissionForm, access_level: value })}>
                <SelectTrigger id="permission-access">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="read_only">{t('settings:tags.accessLevels.readOnly')}</SelectItem>
                  <SelectItem value="read_write">{t('settings:tags.accessLevels.readWrite')}</SelectItem>
                  <SelectItem value="admin">{t('settings:tags.accessLevels.admin')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsPermissionDialogOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button onClick={handlePermissionSubmit} disabled={loading || !permissionForm.group_id}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editingPermission ? t('common:actions.update') : t('common:actions.add')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('settings:tags.deleteDialog.title', { type: deletingItem?.type })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('settings:tags.deleteDialog.description', { name: deletingItem?.name })}
              {deletingItem?.type === 'namespace' && ` ${t('settings:tags.deleteDialog.namespaceWarning')}`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:actions.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground">
              {t('common:actions.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
    </>
  );
}