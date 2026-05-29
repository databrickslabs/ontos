import { useState, useEffect, useCallback, useMemo } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { MoreHorizontal, PlusCircle, AlertCircle, FolderOpen, User, Users, Loader2, ChevronDown } from 'lucide-react';
import { ListViewSkeleton } from '@/components/common/list-view-skeleton';
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { ProjectRead } from '@/types/project';
import { useApi } from '@/hooks/use-api';
import TagChip from '@/components/ui/tag-chip';
import { useToast } from "@/hooks/use-toast";
import { RelativeDate } from '@/components/common/relative-date';
import {
    DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import {
    AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from "@/components/ui/badge";
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { Toaster } from "@/components/ui/toaster";
import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import { ProjectFormDialog } from '@/components/projects/project-form-dialog';
import { useTranslation } from 'react-i18next';

// Check API response helper
const checkApiResponse = <T,>(response: { data?: T | { detail?: string }, error?: string | null | undefined }, name: string): T => {
    if (response.error) throw new Error(`${name} fetch failed: ${response.error}`);
    if (response.data && typeof response.data === 'object' && response.data !== null && 'detail' in response.data && typeof (response.data as { detail: string }).detail === 'string') {
        throw new Error(`${name} fetch failed: ${(response.data as { detail: string }).detail}`);
    }
    if (response.data === null || response.data === undefined) throw new Error(`${name} fetch returned null or undefined data.`);
    return response.data as T;
};

export default function ProjectsView() {
  const [projects, setProjects] = useState<ProjectRead[]>([]);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingProject, setEditingProject] = useState<ProjectRead | null>(null);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null);
  const [componentError, setComponentError] = useState<string | null>(null);

  const { t } = useTranslation(['projects', 'common']);
  const { get: apiGet, delete: apiDelete, loading: apiIsLoading } = useApi();
  const { toast } = useToast();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();

  const featureId = 'projects';
  const canRead = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_ONLY);
  const canWrite = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_WRITE);
  const canAdmin = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.ADMIN);

  const fetchProjects = useCallback(async () => {
    if (!canRead && !permissionsLoading) {
        setComponentError(t('permissions.deniedView'));
        return;
    }
    setComponentError(null);
    try {
      const response = await apiGet<ProjectRead[]>('/api/projects');
      const data = checkApiResponse(response, 'Projects');
      const projectsData = Array.isArray(data) ? data : [];
      setProjects(projectsData);
      if (response.error) {
        setComponentError(response.error);
        setProjects([]);
        toast({ variant: "destructive", title: t('messages.errorFetchingProjects'), description: response.error });
      }
    } catch (err: any) {
      setComponentError(err.message || 'Failed to load projects');
      setProjects([]);
      toast({ variant: "destructive", title: t('messages.errorFetchingProjects'), description: err.message });
    }
  }, [canRead, permissionsLoading, apiGet, toast, setComponentError, t]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  const handleOpenCreateDialog = () => {
    if (!canWrite) {
        toast({ variant: "destructive", title: t('permissions.permissionDenied'), description: t('permissions.deniedCreate') });
        return;
    }
    setEditingProject(null);
    setIsFormOpen(true);
  };

  const handleOpenEditDialog = (project: ProjectRead) => {
    if (!canWrite) {
        toast({ variant: "destructive", title: t('permissions.permissionDenied'), description: t('permissions.deniedEdit') });
        return;
    }
    setEditingProject(project);
    setIsFormOpen(true);
  };

  const handleFormSubmitSuccess = (_savedProject: ProjectRead) => {
    fetchProjects();
  };

  const openDeleteDialog = (projectId: string) => {
    if (!canAdmin) {
         toast({ variant: "destructive", title: t('permissions.permissionDenied'), description: t('permissions.deniedDelete') });
         return;
    }
    setDeletingProjectId(projectId);
    setIsDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (!deletingProjectId || !canAdmin) return;
    try {
      const response = await apiDelete(`/api/projects/${deletingProjectId}`);
      if (response.error) {
        let errorMessage = response.error;
        if (response.data && typeof response.data === 'object' && response.data !== null && 'detail' in response.data && typeof (response.data as { detail: string }).detail === 'string') {
            errorMessage = (response.data as { detail: string }).detail;
        }
        throw new Error(errorMessage || 'Failed to delete project.');
      }
      toast({ title: t('messages.projectDeleted'), description: t('messages.projectDeletedSuccess') });
      fetchProjects();
    } catch (err: any) {
       toast({ variant: "destructive", title: t('messages.errorDeletingProject'), description: err.message || 'Failed to delete project.' });
       setComponentError(err.message || 'Failed to delete project.');
    } finally {
       setIsDeleteDialogOpen(false);
       setDeletingProjectId(null);
    }
  };

  const columns = useMemo<ColumnDef<ProjectRead>[]>(() => [
    {
      accessorKey: "name",
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.name')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const project = row.original;
        const isPersonal = ((project as any).project_type || '').toUpperCase() === 'PERSONAL';
        const Icon = isPersonal ? User : Users;
        return (
          <div className="flex items-start gap-2">
            <Icon className="w-4 h-4 mt-0.5 text-muted-foreground" />
            <div>
              <span
                className="font-medium cursor-pointer hover:underline"
                onClick={(e) => {
                  e.stopPropagation();
                  handleOpenEditDialog(project);
                }}
              >
                {project.name}
              </span>
              {project.title && (
                <div className="text-xs text-muted-foreground">
                  {project.title}
                </div>
              )}
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: "description",
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.description')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="truncate max-w-sm text-sm text-muted-foreground">
          {row.getValue("description") || '-'}
        </div>
      ),
    },
    {
      accessorKey: "teams",
      header: t('table.teams'),
      cell: ({ row }) => {
        const teams = row.original.teams;
        if (!teams || teams.length === 0) return '-';
        return (
          <div className="flex flex-col space-y-0.5">
            {teams.slice(0, 3).map((team: any, index: number) => (
              <Badge
                key={index}
                variant="secondary"
                className="text-xs truncate w-fit"
              >
                {team.name}
              </Badge>
            ))}
            {teams.length > 3 && (
              <Badge variant="outline" className="text-xs">
                +{teams.length - 3} {t('table.moreTeams')}
              </Badge>
            )}
          </div>
        );
      }
    },
    {
      accessorKey: "tags",
      header: t('table.tags'),
      cell: ({ row }) => {
        const tags = row.original.tags;
        if (!tags || tags.length === 0) return '-';
        return (
          <div className="flex flex-wrap gap-1">
            {tags.slice(0, 2).map((tag: any, index: number) => (
              <TagChip key={index} tag={tag} size="sm" />
            ))}
            {tags.length > 2 && (
              <Badge variant="outline" className="text-xs">
                +{tags.length - 2} {t('table.moreTags')}
              </Badge>
            )}
          </div>
        );
      }
    },
    {
      accessorKey: "updated_at",
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.lastUpdated')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
         const dateValue = row.getValue("updated_at");
         return dateValue ? <RelativeDate date={dateValue as string | Date | number} /> : t('common:states.notAvailable');
      },
    },
    {
      id: "actions",
      header: t('table.actions'),
      cell: ({ row }) => {
        const project = row.original;
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="h-8 w-8 p-0">
                <span className="sr-only">Open menu</span>
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>{t('table.actions')}</DropdownMenuLabel>
              <DropdownMenuItem onClick={() => handleOpenEditDialog(project)} disabled={!canWrite}>
                {t('editProject')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => openDeleteDialog(project.id)}
                className="text-red-600 focus:text-red-600 focus:bg-red-50 dark:text-red-400 dark:focus:text-red-400 dark:focus:bg-red-950"
                disabled={!canAdmin}
              >
                {t('deleteProject')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ], [canWrite, canAdmin, t, handleOpenEditDialog]);

  return (
    <SettingsPageWrapper title={t('title')} permissionId="settings-projects">
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
           <FolderOpen className="w-8 h-8" />
           {t('title')}
        </h1>
        <p className="text-muted-foreground mt-1">{t('subtitle')}</p>
      </div>

      {(apiIsLoading || permissionsLoading) ? (
        <ListViewSkeleton columns={5} rows={5} toolbarButtons={1} />
      ) : !canRead ? (
         <Alert variant="destructive" className="mb-4">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>{t('permissions.permissionDenied')}</AlertTitle>
              <AlertDescription>{t('permissions.deniedView')}</AlertDescription>
         </Alert>
      ) : componentError ? (
          <Alert variant="destructive" className="mb-4">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>{t('messages.errorLoadingData')}</AlertTitle>
              <AlertDescription>{componentError}</AlertDescription>
          </Alert>
      ) : (
        <>
          <DataTable
             columns={columns}
             data={projects}
             searchColumn="name"
             storageKey="projects-sort"
             toolbarActions={
               <Button onClick={handleOpenCreateDialog} disabled={!canWrite || permissionsLoading || apiIsLoading} className="h-9">
                 <PlusCircle className="mr-2 h-4 w-4" /> {t('addNewProject')}
               </Button>
             }
          />
          <ProjectFormDialog
            isOpen={isFormOpen}
            onOpenChange={setIsFormOpen}
            project={editingProject}
            onSubmitSuccess={handleFormSubmitSuccess}
          />
        </>
      )}

      <AlertDialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('deleteDialog.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('deleteDialog.description')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeletingProjectId(null)}>{t('deleteDialog.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteConfirm} className="bg-red-600 hover:bg-red-700" disabled={apiIsLoading || permissionsLoading}>
               {(apiIsLoading || permissionsLoading) ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} {t('deleteDialog.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Toaster />
    </SettingsPageWrapper>
  );
}