import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { User, Settings, Plus, Edit2, Trash2, Shield } from 'lucide-react';
import { ListItemSkeleton } from '@/components/common/list-view-skeleton';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { PrincipalPicker } from '@/components/common/principal-picker';

interface Privilege {
  securable_id: string;
  securable_type: string;
  permission: string;
}

interface Persona {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  privileges: Privilege[];
  groups: string[];
}

const Entitlements: React.FC = () => {
  const { t } = useTranslation(['entitlements', 'common']);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedPersona, setSelectedPersona] = useState<Persona | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [isPrivilegeDialogOpen, setIsPrivilegeDialogOpen] = useState(false);
  const [isEditMode, setIsEditMode] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newPrivilege, setNewPrivilege] = useState<Partial<Privilege>>({
    securable_id: '',
    securable_type: 'table',
    permission: 'READ'
  });
  const { toast } = useToast();

  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  useEffect(() => {
    fetchPersonas();
    setStaticSegments([]);
    setDynamicTitle(t('entitlements:title'));

    return () => {
        setStaticSegments([]);
        setDynamicTitle(null);
    };
  }, [setStaticSegments, setDynamicTitle]);

  const fetchPersonas = async () => {
    try {
      setIsLoading(true);
      const response = await fetch('/api/entitlements/personas');
      if (!response.ok) throw new Error('Failed to fetch personas');
      const data = await response.json();
      setPersonas(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('entitlements:personas.errors.loadFailed'));
      toast({
        title: t('common:toast.error'),
        description: t('entitlements:personas.errors.loadFailed'),
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectPersona = (persona: Persona) => {
    setSelectedPersona(persona);
  };

  const handleAddPersona = () => {
    setIsEditMode(false);
    setSelectedPersona(null);
    setIsDialogOpen(true);
  };

  const handleEditPersona = () => {
    if (selectedPersona) {
      setIsEditMode(true);
      setIsDialogOpen(true);
    }
  };

  const handleDeletePersona = async () => {
    if (!selectedPersona) return;
    
    try {
      const response = await fetch(`/api/entitlements/personas/${selectedPersona.id}`, {
        method: 'DELETE',
      });
      
      if (!response.ok) throw new Error('Failed to delete persona');
      
      await fetchPersonas();
      setSelectedPersona(null);
      toast({
        title: t('common:toast.success'),
        description: t('entitlements:personas.toast.personaDeleted'),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : t('entitlements:personas.errors.deleteFailed'));
      toast({
        title: t('common:toast.error'),
        description: t('entitlements:personas.errors.deleteFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleSavePersona = async (e: React.FormEvent) => {
    e.preventDefault();
    const formData = new FormData(e.target as HTMLFormElement);
    
    const personaData: Partial<Persona> = {
      name: formData.get('name') as string,
      description: formData.get('description') as string,
    };
    
    try {
      const method = isEditMode ? 'PUT' : 'POST';
      const url = isEditMode 
        ? `/api/entitlements/personas/${selectedPersona?.id}`
        : '/api/entitlements/personas';
      
      const response = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(personaData),
      });

      if (!response.ok) throw new Error('Failed to save persona');
      
      await fetchPersonas();
      setIsDialogOpen(false);
      toast({
        title: t('common:toast.success'),
        description: isEditMode ? t('entitlements:personas.toast.personaUpdated') : t('entitlements:personas.toast.personaCreated'),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : t('entitlements:personas.errors.saveFailed'));
      toast({
        title: t('common:toast.error'),
        description: t('entitlements:personas.errors.saveFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleAddPrivilege = () => {
    setIsPrivilegeDialogOpen(true);
  };

  const handleSavePrivilege = async () => {
    if (!selectedPersona || !newPrivilege.securable_id) return;
    
    try {
      const response = await fetch(`/api/entitlements/personas/${selectedPersona.id}/privileges`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(newPrivilege),
      });

      if (!response.ok) throw new Error('Failed to add privilege');
      
      const updatedPersona = await response.json();
      setSelectedPersona(updatedPersona);
      setPersonas(personas.map(p => 
        p.id === updatedPersona.id ? updatedPersona : p
      ));
      
      setIsPrivilegeDialogOpen(false);
      setNewPrivilege({
        securable_id: '',
        securable_type: 'table',
        permission: 'READ'
      });
      toast({
        title: t('common:toast.success'),
        description: t('entitlements:personas.toast.privilegeAdded'),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : t('entitlements:personas.errors.privilegeAddFailed'));
      toast({
        title: t('common:toast.error'),
        description: t('entitlements:personas.errors.privilegeAddFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleRemovePrivilege = async (securableId: string) => {
    if (!selectedPersona) return;
    
    try {
      const response = await fetch(`/api/entitlements/personas/${selectedPersona.id}/privileges/${securableId}`, {
        method: 'DELETE',
      });

      if (!response.ok) throw new Error('Failed to remove privilege');
      
      const updatedPersona = await response.json();
      setSelectedPersona(updatedPersona);
      setPersonas(personas.map(p => 
        p.id === updatedPersona.id ? updatedPersona : p
      ));
      toast({
        title: t('common:toast.success'),
        description: t('entitlements:personas.toast.privilegeRemoved'),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : t('entitlements:personas.errors.privilegeRemoveFailed'));
      toast({
        title: t('common:toast.error'),
        description: t('entitlements:personas.errors.privilegeRemoveFailed'),
        variant: 'destructive',
      });
    }
  };

  const getPermissionColor = (permission: string) => {
    switch (permission) {
      case 'READ':
        return 'bg-blue-100 text-blue-800';
      case 'WRITE':
        return 'bg-green-100 text-green-800';
      case 'MANAGE':
        return 'bg-yellow-100 text-yellow-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const handleUpdateGroups = async (personaId: string, groups: string[]) => {
    try {
      const response = await fetch(`/api/entitlements/personas/${personaId}/groups`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ groups }),
      });

      if (!response.ok) throw new Error('Failed to update groups');
      
      const updatedPersona = await response.json();
      setSelectedPersona(updatedPersona);
      setPersonas(personas.map(p => 
        p.id === updatedPersona.id ? updatedPersona : p
      ));
      toast({
        title: t('common:toast.success'),
        description: t('entitlements:personas.toast.groupsUpdated'),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : t('entitlements:personas.errors.groupsUpdateFailed'));
      toast({
        title: t('common:toast.error'),
        description: t('entitlements:personas.errors.groupsUpdateFailed'),
        variant: 'destructive',
      });
    }
  };

  return (
    <div className="py-6">
      <h1 className="text-3xl font-bold mb-6 flex items-center gap-2">
        <Shield className="w-8 h-8" /> {t('entitlements:title')}
      </h1>
      <div className="flex justify-between items-center mb-6">
        <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogTrigger asChild>
            <Button onClick={handleAddPersona} className="gap-2">
              <Plus className="h-4 w-4" />
              {t('entitlements:personas.createPersona')}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{isEditMode ? t('entitlements:personas.editPersona') : t('entitlements:personas.createNewPersona')}</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleSavePersona}>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label htmlFor="name">{t('entitlements:personas.personaName')}</Label>
                  <Input
                    id="name"
                    name="name"
                    defaultValue={isEditMode && selectedPersona ? selectedPersona.name : ''}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="description">{t('common:labels.description')}</Label>
                  <Textarea
                    id="description"
                    name="description"
                    defaultValue={isEditMode && selectedPersona ? selectedPersona.description : ''}
                  />
                </div>
              </div>
              <div className="flex justify-end space-x-2">
                <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
                  {t('common:actions.cancel')}
                </Button>
                <Button type="submit">
                  {isEditMode ? t('common:actions.saveChanges') : t('entitlements:personas.createPersona')}
                </Button>
              </div>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {error && (
        <div className="mb-4 p-4 bg-red-100 text-red-800 rounded-md">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {/* Personas List */}
        <Card className="md:col-span-1">
          <CardHeader>
            <CardTitle>{t('entitlements:personas.title')}</CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[70vh]">
              {isLoading ? (
                <ListItemSkeleton count={5} height="h-16" className="space-y-2" />
              ) : personas.length === 0 ? (
                <div className="p-4 text-center text-muted-foreground">
                  {t('entitlements:personas.noPersonas')}
                </div>
              ) : (
                <div className="space-y-2">
                  {personas.map((persona) => (
                    <div
                      key={persona.id}
                      className={`p-4 rounded-md cursor-pointer ${
                        selectedPersona?.id === persona.id
                          ? 'bg-primary/10'
                          : 'hover:bg-muted'
                      }`}
                      onClick={() => handleSelectPersona(persona)}
                    >
                      <div className="flex items-center space-x-3">
                        <User className="w-5 h-5" />
                        <div>
                          <h3 className="font-medium">{persona.name}</h3>
                          <p className="text-sm text-muted-foreground">
                            {persona.privileges.length} privileges
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>

        {/* Persona Details */}
        <Card className="md:col-span-3">
          <CardHeader>
            <div className="flex justify-between items-center">
              <CardTitle>
                {selectedPersona ? selectedPersona.name : t('entitlements:personas.selectPersona')}
              </CardTitle>
              {selectedPersona && (
                <div className="flex space-x-2">
                  <Button variant="outline" onClick={handleEditPersona}>
                    <Edit2 className="w-4 h-4 mr-2" />
                    {t('common:actions.edit')}
                  </Button>
                  <Button variant="outline" onClick={handleDeletePersona}>
                    <Trash2 className="w-4 h-4 mr-2" />
                    {t('common:actions.delete')}
                  </Button>
                </div>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {selectedPersona ? (
              <Tabs defaultValue="privileges">
                <TabsList>
                  <TabsTrigger value="privileges">{t('entitlements:personas.accessPrivileges')}</TabsTrigger>
                  <TabsTrigger value="groups">{t('entitlements:personas.groupAssignments')}</TabsTrigger>
                </TabsList>
                <TabsContent value="privileges">
                  <div className="space-y-4">
                    <div className="flex justify-between items-center">
                      <h3 className="text-lg font-medium">{t('entitlements:personas.accessPrivileges')}</h3>
                      <Button onClick={handleAddPrivilege}>
                        <Plus className="w-4 h-4 mr-2" />
                        {t('entitlements:personas.addPrivilege')}
                      </Button>
                    </div>
                    {selectedPersona.privileges.length === 0 ? (
                      <div className="text-center text-muted-foreground py-4">
                        {t('entitlements:personas.noPrivileges')}
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {selectedPersona.privileges.map((privilege) => (
                          <div
                            key={privilege.securable_id}
                            className="flex items-center justify-between p-4 border rounded-md"
                          >
                            <div>
                              <div className="font-medium">{privilege.securable_id}</div>
                              <div className="text-sm text-muted-foreground">
                                {privilege.securable_type}
                              </div>
                            </div>
                            <div className="flex items-center space-x-2">
                              <Badge className={getPermissionColor(privilege.permission)}>
                                {privilege.permission}
                              </Badge>
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => handleRemovePrivilege(privilege.securable_id)}
                              >
                                <Trash2 className="w-4 h-4" />
                              </Button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </TabsContent>
                <TabsContent value="groups">
                  <div className="space-y-4">
                    <h3 className="text-lg font-medium">{t('entitlements:personas.groupAssignments')}</h3>
                    <div className="space-y-2">
                      <Label>{t('entitlements:personas.addGroups')}</Label>
                      <PrincipalPicker
                        multiple
                        accepts={['group']}
                        value={selectedPersona.groups}
                        onChange={(next) => handleUpdateGroups(selectedPersona.id, next)}
                        placeholder={t('common:placeholders.selectGroup')}
                        aria-label={t('entitlements:personas.groupAssignments')}
                      />
                    </div>
                  </div>
                </TabsContent>
              </Tabs>
            ) : (
              <div className="flex flex-col items-center justify-center h-[70vh] text-muted-foreground">
                <Settings className="w-12 h-12 mb-4" />
                <p className="text-lg">{t('entitlements:personas.selectPersonaHint')}</p>
                <p className="text-sm">{t('entitlements:personas.createPersonaHint')}</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Add Privilege Dialog */}
      <Dialog open={isPrivilegeDialogOpen} onOpenChange={setIsPrivilegeDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('entitlements:personas.addPrivilege')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="securable_id">{t('common:labels.securableId')}</Label>
              <Input
                id="securable_id"
                value={newPrivilege.securable_id}
                onChange={(e) => setNewPrivilege({...newPrivilege, securable_id: e.target.value})}
                placeholder={t('common:placeholders.exampleCatalogSchemaTable')}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="securable_type">{t('common:labels.securableType')}</Label>
              <Select
                value={newPrivilege.securable_type}
                onValueChange={(value) => setNewPrivilege({...newPrivilege, securable_type: value})}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('common:placeholders.selectType')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="catalog">Catalog</SelectItem>
                  <SelectItem value="schema">Schema</SelectItem>
                  <SelectItem value="table">Table</SelectItem>
                  <SelectItem value="view">View</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="permission">{t('common:labels.permission')}</Label>
              <Select
                value={newPrivilege.permission}
                onValueChange={(value) => setNewPrivilege({...newPrivilege, permission: value})}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('common:placeholders.selectPermission')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="READ">READ</SelectItem>
                  <SelectItem value="WRITE">WRITE</SelectItem>
                  <SelectItem value="MANAGE">MANAGE</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="flex justify-end space-x-2">
            <Button variant="outline" onClick={() => setIsPrivilegeDialogOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button onClick={handleSavePrivilege} disabled={!newPrivilege.securable_id}>
              {t('common:actions.add')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Entitlements; 