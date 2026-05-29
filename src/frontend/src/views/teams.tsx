import { useState, useEffect, useCallback, useMemo } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { MoreHorizontal, PlusCircle, AlertCircle, UserCheck, User, Users, Loader2, ChevronDown } from 'lucide-react';
import { ListViewSkeleton } from '@/components/common/list-view-skeleton';
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { TeamRead } from '@/types/team';
import { useApi } from '@/hooks/use-api';
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
import { useProjectContext } from '@/stores/project-store';
import { TeamFormDialog } from '@/components/teams/team-form-dialog';
import { useNavigate } from 'react-router-dom';
import { useDomains } from '@/hooks/use-domains';
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

export default function TeamsView() {
  const [teams, setTeams] = useState<TeamRead[]>([]);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingTeam, setEditingTeam] = useState<TeamRead | null>(null);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [deletingTeamId, setDeletingTeamId] = useState<string | null>(null);
  const [componentError, setComponentError] = useState<string | null>(null);

  const { t } = useTranslation(['teams', 'common']);
  const { get: apiGet, delete: apiDelete, loading: apiIsLoading } = useApi();
  const { toast } = useToast();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const navigate = useNavigate();
  const { getDomainName } = useDomains();
  const { currentProject, hasProjectContext } = useProjectContext();

  const featureId = 'teams';
  const canRead = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_ONLY);
  const canWrite = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_WRITE);
  const canAdmin = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.ADMIN);

  const fetchTeams = useCallback(async () => {
    if (!canRead && !permissionsLoading) {
        setComponentError(t('permissions.deniedView'));
        return;
    }
    setComponentError(null);
    try {
      // Build URL with project context if available
      let endpoint = '/api/teams';
      if (hasProjectContext && currentProject) {
        endpoint += `?project_id=${currentProject.id}`;
      }

      const response = await apiGet<TeamRead[]>(endpoint);
      const data = checkApiResponse(response, 'Teams');
      const teamsData = Array.isArray(data) ? data : [];
      setTeams(teamsData);
      if (response.error) {
        setComponentError(response.error);
        setTeams([]);
        toast({ variant: "destructive", title: t('messages.errorFetchingTeams'), description: response.error });
      }
    } catch (err: any) {
      setComponentError(err.message || 'Failed to load teams');
      setTeams([]);
      toast({ variant: "destructive", title: t('messages.errorFetchingTeams'), description: err.message });
    }
  }, [canRead, permissionsLoading, apiGet, toast, setComponentError, hasProjectContext, currentProject, t]);

  useEffect(() => {
    fetchTeams();
  }, [fetchTeams]);

  const handleOpenCreateDialog = () => {
    if (!canWrite) {
        toast({ variant: "destructive", title: t('permissions.permissionDenied'), description: t('permissions.deniedCreate') });
        return;
    }
    setEditingTeam(null);
    setIsFormOpen(true);
  };

  const handleOpenEditDialog = (team: TeamRead) => {
    if (!canWrite) {
        toast({ variant: "destructive", title: t('permissions.permissionDenied'), description: t('permissions.deniedEdit') });
        return;
    }
    setEditingTeam(team);
    setIsFormOpen(true);
  };

  const handleFormSubmitSuccess = (_savedTeam: TeamRead) => {
    fetchTeams();
  };

  const openDeleteDialog = (teamId: string) => {
    if (!canAdmin) {
         toast({ variant: "destructive", title: t('permissions.permissionDenied'), description: t('permissions.deniedDelete') });
         return;
    }
    setDeletingTeamId(teamId);
    setIsDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (!deletingTeamId || !canAdmin) return;
    try {
      const response = await apiDelete(`/api/teams/${deletingTeamId}`);
      if (response.error) {
        let errorMessage = response.error;
        if (response.data && typeof response.data === 'object' && response.data !== null && 'detail' in response.data && typeof (response.data as { detail: string }).detail === 'string') {
            errorMessage = (response.data as { detail: string }).detail;
        }
        throw new Error(errorMessage || 'Failed to delete team.');
      }
      toast({ title: t('messages.teamDeleted'), description: t('messages.teamDeletedSuccess') });
      fetchTeams();
    } catch (err: any) {
       toast({ variant: "destructive", title: t('messages.errorDeletingTeam'), description: err.message || 'Failed to delete team.' });
       setComponentError(err.message || 'Failed to delete team.');
    } finally {
       setIsDeleteDialogOpen(false);
       setDeletingTeamId(null);
    }
  };

  const columns = useMemo<ColumnDef<TeamRead>[]>(() => [
    {
      accessorKey: "name",
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.name')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const team = row.original;
        const domainName = team.domain_name || getDomainName(team.domain_id);
        return (
          <div>
            <span
              className="font-medium cursor-pointer hover:underline"
              onClick={(e) => {
                e.stopPropagation();
                handleOpenEditDialog(team);
              }}
            >
              {team.name}
            </span>
            {domainName && team.domain_id && (
              <div
                className="text-xs text-muted-foreground cursor-pointer hover:underline"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate(`/settings/data-domains/${team.domain_id}`);
                }}
              >
                {t('table.domainPrefix')} {domainName}
              </div>
            )}
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
      accessorKey: "members",
      header: t('table.members'),
      cell: ({ row }) => {
        const members = row.original.members;
        if (!members || members.length === 0) return '-';
        return (
          <div className="flex flex-col space-y-0.5">
            {members.slice(0, 3).map((member, index) => (
              <div key={index} className="flex items-center gap-1">
                <Badge
                  variant={member.member_type === 'user' ? 'default' : 'secondary'}
                  className={`text-xs truncate w-fit flex items-center gap-1 ${
                    member.member_type === 'user'
                      ? 'bg-white text-gray-900 border border-gray-300 hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-100 dark:border-gray-600 dark:hover:bg-gray-700'
                      : 'bg-gray-900 text-white hover:bg-gray-800 dark:bg-gray-200 dark:text-gray-900 dark:hover:bg-gray-300'
                  }`}
                >
                  {member.member_type === 'user' ? (
                    <User className="w-3 h-3" />
                  ) : (
                    <Users className="w-3 h-3" />
                  )}
                  {member.member_name || member.member_identifier}
                </Badge>
                {(member.role_override || member.app_role_override) && (
                  <Badge variant="outline" className="text-xs">
                    {member.role_override || member.app_role_override}
                  </Badge>
                )}
              </div>
            ))}
            {members.length > 3 && (
              <Badge variant="outline" className="text-xs">
                +{members.length - 3} {t('table.moreMembers')}
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
        const team = row.original;
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
              <DropdownMenuItem onClick={() => handleOpenEditDialog(team)} disabled={!canWrite}>
                {t('editTeam')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => openDeleteDialog(team.id)}
                className="text-red-600 focus:text-red-600 focus:bg-red-50 dark:text-red-400 dark:focus:text-red-400 dark:focus:bg-red-950"
                disabled={!canAdmin}
              >
                {t('deleteTeam')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ], [canWrite, canAdmin, getDomainName, navigate, t, handleOpenEditDialog]);

  return (
    <SettingsPageWrapper title={t('title')} permissionId="settings-teams">
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
           <UserCheck className="w-8 h-8" />
           {t('title')}
        </h1>
        <p className="text-muted-foreground mt-1">
          {t('subtitle')}
          {hasProjectContext && currentProject && (
            <> — {t('showingTeamsForProject')} <span className="font-medium">{currentProject.name}</span></>
          )}
        </p>
      </div>

      {(apiIsLoading || permissionsLoading) ? (
        <ListViewSkeleton columns={4} rows={5} toolbarButtons={1} />
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
             data={teams}
             searchColumn="name"
             storageKey="teams-sort"
             toolbarActions={
               <Button onClick={handleOpenCreateDialog} disabled={!canWrite || permissionsLoading || apiIsLoading} className="h-9">
                 <PlusCircle className="mr-2 h-4 w-4" /> {t('addNewTeam')}
               </Button>
             }
          />
          <TeamFormDialog
            isOpen={isFormOpen}
            onOpenChange={setIsFormOpen}
            team={editingTeam}
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
            <AlertDialogCancel onClick={() => setDeletingTeamId(null)}>{t('deleteDialog.cancel')}</AlertDialogCancel>
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