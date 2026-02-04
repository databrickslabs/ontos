import { useState, useEffect, useCallback } from 'react';
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
      toast({ variant: 'destructive', title: 'Error fetching namespaces', description: err.message });
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
      toast({ variant: 'destructive', title: 'Error fetching tags', description: err.message });
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
      toast({ variant: 'destructive', title: 'Error fetching permissions', description: err.message });
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
      toast({ title: 'Tag display format updated' });
    } catch (err: any) {
      toast({ variant: 'destructive', title: 'Error saving display format', description: err.message });
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
        toast({ title: 'Namespace updated successfully' });
      } else {
        await post('/api/tags/namespaces', namespaceForm);
        toast({ title: 'Namespace created successfully' });
      }
      setIsNamespaceDialogOpen(false);
      fetchNamespaces();
    } catch (err: any) {
      toast({ variant: 'destructive', title: 'Error saving namespace', description: err.message });
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
        toast({ title: 'Tag updated successfully' });
      } else {
        await post('/api/tags', payload);
        toast({ title: 'Tag created successfully' });
      }
      setIsTagDialogOpen(false);
      fetchTags();
    } catch (err: any) {
      toast({ variant: 'destructive', title: 'Error saving tag', description: err.message });
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
        toast({ title: 'Permission updated successfully' });
      } else {
        await post(`/api/tags/namespaces/${selectedNamespace}/permissions`, permissionForm);
        toast({ title: 'Permission created successfully' });
      }
      setIsPermissionDialogOpen(false);
      fetchPermissions();
    } catch (err: any) {
      toast({ variant: 'destructive', title: 'Error saving permission', description: err.message });
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
      toast({ title: `${deletingItem.type} deleted successfully` });
      setIsDeleteDialogOpen(false);
      setDeletingItem(null);
    } catch (err: any) {
      toast({ variant: 'destructive', title: 'Error deleting item', description: err.message });
    }
  };

  // Table columns
  const tagColumns: ColumnDef<Tag>[] = [
    {
      accessorKey: 'name',
      header: 'Name',
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <Tag className="h-4 w-4" />
          <span className="font-medium">{row.original.name}</span>
        </div>
      ),
    },
    {
      accessorKey: 'description',
      header: 'Description',
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">{row.original.description || '—'}</span>
      ),
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ row }) => (
        <Badge variant={row.original.status === 'active' ? 'default' : 'secondary'}>
          {row.original.status}
        </Badge>
      ),
    },
    {
      accessorKey: 'version',
      header: 'Version',
      cell: ({ row }) => (
        <span className="text-sm">{row.original.version || '—'}</span>
      ),
    },
    {
      accessorKey: 'updated_at',
      header: 'Updated',
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
            <DropdownMenuLabel>Actions</DropdownMenuLabel>
            <DropdownMenuItem onClick={() => openTagDialog(row.original)}>
              <Edit className="mr-2 h-4 w-4" />
              Edit
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive"
              onClick={() => openDeleteDialog('tag', row.original.id, row.original.name)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ),
    },
  ];

  const permissionColumns: ColumnDef<TagNamespacePermission>[] = [
    {
      accessorKey: 'group_id',
      header: 'Group',
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4" />
          <span className="font-medium">{row.original.group_id}</span>
        </div>
      ),
    },
    {
      accessorKey: 'access_level',
      header: 'Access Level',
      cell: ({ row }) => (
        <Badge variant={row.original.access_level === 'admin' ? 'destructive' : 'default'}>
          {row.original.access_level}
        </Badge>
      ),
    },
    {
      accessorKey: 'updated_at',
      header: 'Updated',
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
            <DropdownMenuLabel>Actions</DropdownMenuLabel>
            <DropdownMenuItem onClick={() => openPermissionDialog(row.original)}>
              <Edit className="mr-2 h-4 w-4" />
              Edit
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive"
              onClick={() => openDeleteDialog('permission', row.original.id, row.original.group_id)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete
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
    <div className="space-y-6">
      {/* Tag Display Settings */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Eye className="h-5 w-5" />
                Tag Display Settings
              </CardTitle>
              <CardDescription>
                Configure how tags are displayed throughout the application.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4">
            <Label htmlFor="display-format-select">Display Format:</Label>
            <Select 
              value={tagDisplayFormat} 
              onValueChange={(value: 'short' | 'long') => saveDisplayFormat(value)}
              disabled={isLoadingDisplayFormat || isSavingDisplayFormat}
            >
              <SelectTrigger id="display-format-select" className="w-[240px]">
                <SelectValue placeholder="Select format" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="short" className="whitespace-nowrap">Short (tag name only)</SelectItem>
                <SelectItem value="long" className="whitespace-nowrap">Long (namespace/tag name)</SelectItem>
              </SelectContent>
            </Select>
            {(isLoadingDisplayFormat || isSavingDisplayFormat) && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-2">
            <strong>Short:</strong> Shows only the tag name (e.g., "pii"). <br />
            <strong>Long:</strong> Shows namespace and tag name (e.g., "compliance/pii").
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
                Tag Namespaces
              </CardTitle>
              <CardDescription>
                Organize tags into logical namespaces for better management and permissions.
              </CardDescription>
            </div>
            <Button onClick={() => openNamespaceDialog()}>
              <Plus className="mr-2 h-4 w-4" />
              Add Namespace
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4 mb-4">
            <Label htmlFor="namespace-select">Active Namespace:</Label>
            <Select value={selectedNamespace} onValueChange={setSelectedNamespace}>
              <SelectTrigger id="namespace-select" className="w-[200px]">
                <SelectValue placeholder="Select namespace" />
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
                  Edit
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
                  Delete
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
                    Tags
                  </CardTitle>
                  <CardDescription>
                    Manage tags within the selected namespace.
                  </CardDescription>
                </div>
                <Button onClick={() => openTagDialog()}>
                  <Plus className="mr-2 h-4 w-4" />
                  Add Tag
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
                    Namespace Permissions
                  </CardTitle>
                  <CardDescription>
                    Control which groups can access and modify tags in this namespace.
                  </CardDescription>
                </div>
                <Button onClick={() => openPermissionDialog()}>
                  <Plus className="mr-2 h-4 w-4" />
                  Add Permission
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
            <DialogTitle>{editingNamespace ? 'Edit Namespace' : 'Create Namespace'}</DialogTitle>
            <DialogDescription>
              {editingNamespace ? 'Update the namespace details.' : 'Create a new namespace for organizing tags.'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="namespace-name">Name</Label>
              <Input
                id="namespace-name"
                value={namespaceForm.name}
                onChange={(e) => setNamespaceForm({ ...namespaceForm, name: e.target.value })}
                placeholder="e.g., finance, marketing, engineering"
              />
            </div>
            <div>
              <Label htmlFor="namespace-description">Description</Label>
              <Textarea
                id="namespace-description"
                value={namespaceForm.description}
                onChange={(e) => setNamespaceForm({ ...namespaceForm, description: e.target.value })}
                placeholder="Optional description for the namespace"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsNamespaceDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleNamespaceSubmit} disabled={loading || !namespaceForm.name}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editingNamespace ? 'Update' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Tag Dialog */}
      <Dialog open={isTagDialogOpen} onOpenChange={setIsTagDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editingTag ? 'Edit Tag' : 'Create Tag'}</DialogTitle>
            <DialogDescription>
              {editingTag ? 'Update the tag details.' : 'Create a new tag in the selected namespace.'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="tag-name">Name</Label>
                <Input
                  id="tag-name"
                  value={tagForm.name}
                  onChange={(e) => setTagForm({ ...tagForm, name: e.target.value })}
                  placeholder="e.g., pii, sensitive, public"
                />
              </div>
              <div>
                <Label htmlFor="tag-status">Status</Label>
                <Select value={tagForm.status} onValueChange={(value) => setTagForm({ ...tagForm, status: value })}>
                  <SelectTrigger id="tag-status">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="active">Active</SelectItem>
                    <SelectItem value="draft">Draft</SelectItem>
                    <SelectItem value="candidate">Candidate</SelectItem>
                    <SelectItem value="deprecated">Deprecated</SelectItem>
                    <SelectItem value="inactive">Inactive</SelectItem>
                    <SelectItem value="retired">Retired</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label htmlFor="tag-description">Description</Label>
              <Textarea
                id="tag-description"
                value={tagForm.description}
                onChange={(e) => setTagForm({ ...tagForm, description: e.target.value })}
                placeholder="Describe what this tag represents"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="tag-version">Version</Label>
                <Input
                  id="tag-version"
                  value={tagForm.version}
                  onChange={(e) => setTagForm({ ...tagForm, version: e.target.value })}
                  placeholder="e.g., v1.0, 2023.1"
                />
              </div>
              <div>
                <Label htmlFor="tag-parent">Parent Tag</Label>
                <Select value={tagForm.parent_id || '__none__'} onValueChange={(value) => setTagForm({ ...tagForm, parent_id: value === '__none__' ? undefined : value })}>
                  <SelectTrigger id="tag-parent">
                    <SelectValue placeholder="None" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">None</SelectItem>
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
              <Label htmlFor="tag-possible-values">Possible Values (JSON Array)</Label>
              <Textarea
                id="tag-possible-values"
                value={tagForm.possible_values}
                onChange={(e) => setTagForm({ ...tagForm, possible_values: e.target.value })}
                placeholder='["value1", "value2", "value3"]'
              />
              <p className="text-sm text-muted-foreground mt-1">
                Optional. JSON array of allowed values for this tag when assigned to entities.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsTagDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleTagSubmit} disabled={loading || !tagForm.name}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editingTag ? 'Update' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Permission Dialog */}
      <Dialog open={isPermissionDialogOpen} onOpenChange={setIsPermissionDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingPermission ? 'Edit Permission' : 'Add Permission'}</DialogTitle>
            <DialogDescription>
              {editingPermission ? 'Update the permission details.' : 'Grant access to a group for this namespace.'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="permission-group">Group ID</Label>
              <Input
                id="permission-group"
                value={permissionForm.group_id}
                onChange={(e) => setPermissionForm({ ...permissionForm, group_id: e.target.value })}
                placeholder="e.g., data-engineers, analysts"
              />
            </div>
            <div>
              <Label htmlFor="permission-access">Access Level</Label>
              <Select value={permissionForm.access_level} onValueChange={(value) => setPermissionForm({ ...permissionForm, access_level: value })}>
                <SelectTrigger id="permission-access">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="read_only">Read Only</SelectItem>
                  <SelectItem value="read_write">Read/Write</SelectItem>
                  <SelectItem value="admin">Admin</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsPermissionDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handlePermissionSubmit} disabled={loading || !permissionForm.group_id}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editingPermission ? 'Update' : 'Add'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deletingItem?.type}</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete "{deletingItem?.name}"? This action cannot be undone.
              {deletingItem?.type === 'namespace' && ' All tags and permissions in this namespace will also be deleted.'}
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