import { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { AppRole, FeatureConfig, FeatureAccessLevel } from '@/types/settings'; // Import FeatureAccessLevel
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Plus, Pencil, Trash2, AlertCircle, ChevronDown, UserPlus, Shield, User, Users } from 'lucide-react';
import { ListItemSkeleton } from '@/components/common/list-view-skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import RoleFormDialog from './role-form-dialog'; // Uncomment and import
import RequestRoleAccessDialog from './request-role-access-dialog'; // Import role access request dialog
// useNotificationsStore import removed - not currently used
// import { useNotificationsStore } from '@/stores/notifications-store';
import { useUserStore } from '@/stores/user-store'; // Import user store

// --- DataTable Imports ---
import {
    ColumnDef,
    Column, // Import Column type for header context
} from "@tanstack/react-table";
import { DataTable } from "@/components/ui/data-table"; // Import DataTable
import { usePermissions } from '@/stores/permissions-store'; // Import the permissions hook

export default function RolesSettings() {
    const { get, post: _post, delete: deleteApi } = useApi();
    const { toast } = useToast();
    const { t } = useTranslation('settings');
    const [roles, setRoles] = useState<AppRole[]>([]);
    const [features, setFeatures] = useState<Record<string, FeatureConfig>>({});
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [isDialogOpen, setIsDialogOpen] = useState(false);
    const [roleToEdit, setRoleToEdit] = useState<AppRole | null>(null);
    const [isRequestDialogOpen, setIsRequestDialogOpen] = useState(false);
    const [roleToRequest, setRoleToRequest] = useState<AppRole | null>(null);
    const { hasPermission, fetchPermissions, fetchAvailableRoles } = usePermissions(); // Get userGroups & availableRoles
    const { userInfo } = useUserStore(); // Get user info from user store
    const userGroups = userInfo?.groups ?? []; // Extract groups, default to empty array
    
    const featureId = 'settings-roles'; // Feature ID for permissions
    const canWrite = hasPermission(featureId, FeatureAccessLevel.READ_WRITE);
    const canAdmin = hasPermission(featureId, FeatureAccessLevel.ADMIN);

    // Whether the current user holds a role — via group membership OR direct
    // email assignment (assigned_users, #196/#760).
    const checkUserHasRole = (role: AppRole): boolean => {
        const userGroupSet = new Set(userGroups);
        const byGroup = (role.assigned_groups || []).some(group => userGroupSet.has(group));
        const email = (userInfo?.email || '').trim().toLowerCase();
        const byEmail = !!email && (role.assigned_users || []).some(u => (u || '').trim().toLowerCase() === email);
        return byGroup || byEmail;
    };

    const fetchData = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const [rolesResponse, featuresResponse] = await Promise.all([
                get<AppRole[]>('/api/settings/roles'),
                get<Record<string, FeatureConfig>>('/api/settings/features')
            ]);

            if (rolesResponse.error) throw new Error(`Roles fetch failed: ${rolesResponse.error}`);
            if (featuresResponse.error) throw new Error(`Features fetch failed: ${featuresResponse.error}`);

            setRoles(rolesResponse.data || []);
            setFeatures(featuresResponse.data || {});

        } catch (err: any) {
            console.error("Error fetching roles or features:", err);
            setError(err.message || 'Failed to load roles configuration.');
            setRoles([]);
            setFeatures({});
            toast({ title: 'Error', description: err.message, variant: 'destructive' });
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
        // Permissions and user info are fetched in App.tsx
        // fetchPermissions(); 
        // fetchAvailableRoles(); 
    }, []); // Run once on mount

    const handleOpenDialog = (role?: AppRole) => {
        if (!canWrite) {
            toast({ title: 'Permission Denied', description: 'You do not have permission to edit roles.', variant: 'destructive' });
            return;
        }
        setRoleToEdit(role || null);
        setIsDialogOpen(true);
    };

    const refreshPermissionsAndRoles = async () => {
        try {
            // Fetching happens in App.tsx now, maybe remove this helper or trigger App fetch?
            // For now, keep local toast feedback
            await Promise.all([fetchPermissions(), fetchAvailableRoles()]); // Call actions directly 
            toast({ title: 'Permissions Updated', description: 'User permissions and available roles refreshed.' });
        } catch (err: any) {
            console.error("Error refreshing permissions/roles:", err);
            toast({ title: 'Refresh Failed', description: `Could not refresh permissions/roles: ${err.message}`, variant: 'destructive' });
        }
    };

    const handleRequestAccess = (role: AppRole) => {
        setRoleToRequest(role);
        setIsRequestDialogOpen(true);
    };

    const handleDeleteRole = async (roleId: string, roleName: string) => {
        if (!confirm(`Are you sure you want to delete the role "${roleName}"?`)) return;

        if (!canAdmin) {
            toast({ title: 'Permission Denied', description: 'You do not have permission to delete roles.', variant: 'destructive' });
            return;
        }

        try {
            await deleteApi(`/api/settings/roles/${roleId}`);
            toast({ title: 'Success', description: `Role "${roleName}" deleted.` });
            fetchData(); // Refresh list
            await refreshPermissionsAndRoles(); // Refresh permissions/roles
        } catch (err: any) {
            console.error("Error deleting role:", err);
            const errorMsg = err.message || 'Failed to delete role.';
            toast({ title: 'Error', description: errorMsg, variant: 'destructive' });
            setError(errorMsg);
        }
    };

    const handleDialogSubmitSuccess = async () => {
        fetchData(); 
        await refreshPermissionsAndRoles();
    };

    // --- Column Definitions ---
    const columns = useMemo<ColumnDef<AppRole>[]>(() => [
        {
            accessorKey: "name",
            header: ({ column }: { column: Column<AppRole, unknown> }) => (
                <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
                    {t('roles.table.nameColumn')} <ChevronDown className="ml-2 h-4 w-4" />
                </Button>
            ),
            cell: ({ row }) => <div className="font-medium">{row.getValue("name")}</div>,
            enableSorting: true,
        },
        {
            accessorKey: "description",
            header: ({ column }: { column: Column<AppRole, unknown> }) => (
                 <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
                     {t('roles.table.descriptionColumn')} <ChevronDown className="ml-2 h-4 w-4" />
                 </Button>
            ),
            cell: ({ row }) => <div>{row.getValue("description") || '-'}</div>,
            enableSorting: true,
        },
        {
            accessorKey: "assigned_groups",
            header: t('roles.table.principalsColumn', 'Principals'),
            cell: ({ row }) => {
                const groups = (row.original.assigned_groups as string[]) || [];
                const users = (row.original.assigned_users as string[]) || [];
                // Groups: dark badge + multi-person icon. Users: light badge + single-person icon.
                const principals = [
                    ...groups.map((g) => ({ kind: 'group' as const, label: g })),
                    ...users.map((u) => ({ kind: 'user' as const, label: u })),
                ];
                if (principals.length === 0) {
                    return <span className="text-xs text-muted-foreground">{t('roles.table.none')}</span>;
                }
                const MAX = 3;
                const shown = principals.slice(0, MAX);
                const extra = principals.length - shown.length;
                return (
                    <div className="flex flex-wrap gap-1">
                        {shown.map((p) => (
                            <Badge
                                key={`${p.kind}:${p.label}`}
                                variant={p.kind === 'group' ? 'secondary' : 'outline'}
                                className="gap-1"
                            >
                                {p.kind === 'group' ? <Users className="h-3 w-3" /> : <User className="h-3 w-3" />}
                                {p.label}
                            </Badge>
                        ))}
                        {extra > 0 && <Badge variant="outline">+{extra} more</Badge>}
                    </div>
                );
            },
            enableSorting: false,
        },
        {
            id: "request",
            header: "", // No header text needed
            cell: ({ row }) => {
                 const role = row.original;
                 const userHasThisRole = checkUserHasRole(role); // Use the updated helper function
                 
                 return (
                    <Button
                        variant="outline"
                        size="sm"
                        className="h-8 gap-1"
                        onClick={() => handleRequestAccess(role)}
                        disabled={userHasThisRole} // Disable if user has the role
                        title={userHasThisRole ? t('roles.table.alreadyAssignedTooltip') : t('roles.table.requestTooltip')}
                    >
                        {userHasThisRole ? (
                            <span className="text-muted-foreground italic">{t('roles.table.assigned')}</span>
                        ) : (
                            <>
                                <UserPlus className="h-3.5 w-3.5" /> {t('roles.table.request')}
                            </>
                        )}
                    </Button>
                 );
            },
            enableHiding: true, // Allow hiding if needed
        },
        {
            id: "actions",
            header: () => <div className="text-right">{t('roles.actions.actions')}</div>,
            cell: ({ row }) => {
                const role = row.original;
                const isAdminRole = role.name.toLowerCase() === 'admin';

                return (
                    <div className="flex justify-end gap-1">
                        <Button
                            variant="ghost"
                            size="sm"
                            className="h-8 w-8 p-0"
                            onClick={() => handleOpenDialog(role)}
                            disabled={!canWrite}
                            title={t('roles.actions.editRole')}
                        >
                            <Pencil className="h-4 w-4" />
                            <span className="sr-only">{t('roles.actions.editRole')}</span>
                        </Button>
                        <Button
                            variant="ghost"
                            size="sm"
                            className="h-8 w-8 p-0 text-destructive hover:text-destructive hover:bg-destructive/10"
                            onClick={() => handleDeleteRole(role.id, role.name)}
                            disabled={isAdminRole || !canAdmin}
                            title={isAdminRole ? 'Cannot delete Admin role' : t('roles.actions.deleteRole')}
                        >
                            <Trash2 className="h-4 w-4" />
                            <span className="sr-only">{t('roles.actions.deleteRole')}</span>
                        </Button>
                    </div>
                );
            },
            enableHiding: false,
        },
    ], [handleOpenDialog, handleDeleteRole, handleRequestAccess, features, canWrite, canAdmin, userGroups, checkUserHasRole, t]); // Added t to dependencies

    // --- Render Logic ---
    if (isLoading) {
        return <ListItemSkeleton count={4} height="h-16" className="space-y-2" />;
    }

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
                    <Shield className="w-8 h-8" />
                    {t('roles.title')}
                </h1>
                <p className="text-muted-foreground mt-1">{t('roles.description')}</p>
            </div>

            <DataTable
                columns={columns}
                data={roles}
                searchColumn="name"
                toolbarActions={
                    <Button onClick={() => handleOpenDialog()} disabled={!canWrite} className="h-9">
                        <Plus className="mr-2 h-4 w-4" />
                        {t('roles.actions.addRole')}
                    </Button>
                }
            />

            {isDialogOpen && (
                <RoleFormDialog
                    isOpen={isDialogOpen}
                    onOpenChange={setIsDialogOpen}
                    initialRole={roleToEdit}
                    featuresConfig={features}
                    onSubmitSuccess={handleDialogSubmitSuccess}
                />
            )}

            {isRequestDialogOpen && roleToRequest && (
                <RequestRoleAccessDialog
                    isOpen={isRequestDialogOpen}
                    onOpenChange={setIsRequestDialogOpen}
                    roleId={roleToRequest.id}
                    roleName={roleToRequest.name}
                    roleDescription={roleToRequest.description ?? undefined}
                />
            )}
        </>
    );
} 