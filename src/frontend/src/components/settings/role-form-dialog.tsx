import React, { useState, useEffect } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Loader2, AlertCircle } from 'lucide-react';
import { AppRole, FeatureConfig, FeatureAccessLevel, HomeSection, ApprovalEntity, NO_ROLE_SENTINEL } from '@/types/settings';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { ACCESS_LEVEL_ORDER } from '../../lib/permissions';
import { features as orderedFeatures } from '@/config/features'; // Import the ordered features
import { usePermissions } from '@/stores/permissions-store';
import { Checkbox } from '@/components/ui/checkbox';
import { PrincipalPicker } from '@/components/common/principal-picker';
import { normaliseAssignedGroups } from '@/lib/assigned-groups';

interface RoleFormDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    initialRole: AppRole | null; // Role to edit, or null for create
    featuresConfig: Record<string, FeatureConfig>; // Feature config from backend
    onSubmitSuccess: () => void; // Callback on successful save
}

// Helper to generate default permissions based on feature config
const getDefaultPermissions = (features: Record<string, FeatureConfig>): Record<string, FeatureAccessLevel> => {
    const defaults: Record<string, FeatureAccessLevel> = {};
    Object.keys(features).forEach(featureId => {
        // Default to NONE if available, otherwise the first allowed level (should include NONE)
        const allowed = features[featureId]?.allowed_levels || [];
        defaults[featureId] = allowed.includes(FeatureAccessLevel.NONE)
            ? FeatureAccessLevel.NONE
            : (allowed[0] || FeatureAccessLevel.NONE);
    });
    return defaults;
};

// Helper function to find the highest allowed level for a feature
const getHighestAllowedLevel = (allowedLevels: FeatureAccessLevel[]): FeatureAccessLevel => {
    if (!allowedLevels || allowedLevels.length === 0) {
        return FeatureAccessLevel.NONE; // Default if none specified
    }
    let highestLevel = FeatureAccessLevel.NONE;
    let maxOrder = -1;
    for (const level of allowedLevels) {
        const currentOrder = ACCESS_LEVEL_ORDER[level];
        if (currentOrder > maxOrder) {
            maxOrder = currentOrder;
            highestLevel = level;
        }
    }
    return highestLevel;
};

const RoleFormDialog: React.FC<RoleFormDialogProps> = ({
    isOpen,
    onOpenChange,
    initialRole,
    featuresConfig,
    onSubmitSuccess,
}) => {
    const { post, put } = useApi();
    const { toast } = useToast();
    const { t } = useTranslation('settings');
    const { availableRoles } = usePermissions();
    const isEditMode = !!initialRole;
    const [formError, setFormError] = useState<string | null>(null);

    // Helper to normalize deployment policy from backend (handles nulls)
    const normalizeDeploymentPolicy = (policy: any) => {
        if (!policy) return null;
        return {
            allowed_catalogs: Array.isArray(policy.allowed_catalogs) ? policy.allowed_catalogs : [],
            allowed_schemas: Array.isArray(policy.allowed_schemas) ? policy.allowed_schemas : [],
            default_catalog: policy.default_catalog || '',
            default_schema: policy.default_schema || '',
            require_approval: Boolean(policy.require_approval),
            can_approve_deployments: Boolean(policy.can_approve_deployments),
        };
    };

    // Helper to normalize approval privileges (ensure all values are booleans)
    const normalizeApprovalPrivileges = (privileges: any) => {
        if (!privileges) return {};
        const normalized: Record<string, boolean> = {};
        Object.entries(privileges).forEach(([key, value]) => {
            normalized[key] = Boolean(value);
        });
        return normalized;
    };

    const defaultValues: AppRole = {
        id: initialRole?.id || '',
        name: initialRole?.name || '',
        description: initialRole?.description || '',
        assigned_groups: initialRole?.assigned_groups || [],
        feature_permissions: initialRole?.feature_permissions || getDefaultPermissions(featuresConfig),
        home_sections: initialRole?.home_sections || [],
        approval_privileges: normalizeApprovalPrivileges(initialRole?.approval_privileges),
        deployment_policy: normalizeDeploymentPolicy(initialRole?.deployment_policy),
        is_admin: initialRole?.is_admin || false,
        requestable_by_roles: initialRole?.requestable_by_roles || [],
        approver_roles: initialRole?.approver_roles || [],
    } as AppRole;

    const {
        register,
        handleSubmit,
        control,
        reset,
        formState: { errors, isSubmitting, isDirty },
    } = useForm<AppRole>({ defaultValues });

    // Reset form when initialRole or isOpen changes
    useEffect(() => {
        if (isOpen) {
            const baseRoleData = initialRole ? {
                id: initialRole.id || '',
                name: initialRole.name || '',
                description: initialRole.description || '',
                assigned_groups: initialRole.assigned_groups || [],
                feature_permissions: initialRole.feature_permissions || getDefaultPermissions(featuresConfig),
                home_sections: initialRole.home_sections || [],
                approval_privileges: normalizeApprovalPrivileges(initialRole.approval_privileges),
                deployment_policy: normalizeDeploymentPolicy(initialRole.deployment_policy),
                is_admin: initialRole.is_admin || false,
                requestable_by_roles: initialRole.requestable_by_roles || [],
                approver_roles: initialRole.approver_roles || [],
            } : { 
                id: '', 
                name: '', 
                description: '', 
                assigned_groups: [], 
                feature_permissions: getDefaultPermissions(featuresConfig),
                home_sections: [],
                approval_privileges: {},
                deployment_policy: null,
                is_admin: false,
                requestable_by_roles: [],
                approver_roles: [],
            };

            // Adjust permissions before resetting
            const adjustedPermissions = { ...baseRoleData.feature_permissions }; 
            if (initialRole) { // Only adjust for existing roles
                Object.keys(adjustedPermissions).forEach(featureId => {
                    const assignedLevel = adjustedPermissions[featureId];
                    const featureConf = featuresConfig[featureId];
                    const allowedLevels = featureConf?.allowed_levels || [];

                    if (!allowedLevels.includes(assignedLevel)) {
                        console.warn(`Role '${initialRole.name}' has unallowed level '${assignedLevel}' for feature '${featureId}'. Defaulting to highest allowed.`);
                        adjustedPermissions[featureId] = getHighestAllowedLevel(allowedLevels);
                    }
                });
            }

            const roleData = { ...baseRoleData, feature_permissions: adjustedPermissions } as AppRole;

            reset(roleData);
            setFormError(null);
        } else {
            // Reset with defaults when closing (ensure clean state for next create)
            reset({ 
                id: '', 
                name: '', 
                description: '', 
                assigned_groups: [], 
                feature_permissions: getDefaultPermissions(featuresConfig),
                home_sections: [],
                approval_privileges: {},
                deployment_policy: null,
                is_admin: false,
                requestable_by_roles: [],
                approver_roles: [],
            } as AppRole);
        }
    }, [isOpen, initialRole, reset, featuresConfig]);

    const handleCloseDialog = (open: boolean) => {
        if (!open) {
            if (isDirty) {
                if (!confirm('You have unsaved changes. Are you sure you want to close?')) {
                    return; // Prevent closing
                }
            }
            setFormError(null);
        }
        onOpenChange(open);
    };

    const onSubmit = async (data: AppRole) => {
        setFormError(null);

        // Prepare payload - convert assigned_groups string to array
        let assignedGroupsArray: string[] = [];
        if (Array.isArray(data.assigned_groups)) {
            assignedGroupsArray = data.assigned_groups;
        } else if (typeof data.assigned_groups === 'string') {
            assignedGroupsArray = (data.assigned_groups as string)
                .split(',')
                .map(g => g.trim())
                .filter(Boolean);
        }

        // Ensure approval_privileges values are always booleans (not null/undefined)
        const cleanedApprovalPrivileges: Record<string, boolean> = {};
        if (data.approval_privileges) {
            Object.entries(data.approval_privileges).forEach(([key, value]) => {
                // Convert any truthy/falsy value to explicit boolean
                cleanedApprovalPrivileges[key] = Boolean(value);
            });
        }

        // Ensure deployment_policy has proper types (arrays not null, booleans not undefined)
        let cleanedDeploymentPolicy = null;
        if (data.deployment_policy) {
            cleanedDeploymentPolicy = {
                allowed_catalogs: Array.isArray(data.deployment_policy.allowed_catalogs) 
                    ? data.deployment_policy.allowed_catalogs.filter(Boolean) 
                    : [],
                allowed_schemas: Array.isArray(data.deployment_policy.allowed_schemas) 
                    ? data.deployment_policy.allowed_schemas.filter(Boolean) 
                    : [],
                default_catalog: data.deployment_policy.default_catalog || null,
                default_schema: data.deployment_policy.default_schema || null,
                require_approval: Boolean(data.deployment_policy.require_approval),
                can_approve_deployments: Boolean(data.deployment_policy.can_approve_deployments),
            };
        }

        const basePayload: AppRole = {
            ...data,
            assigned_groups: assignedGroupsArray,
            approval_privileges: cleanedApprovalPrivileges,
            deployment_policy: cleanedDeploymentPolicy,
        } as AppRole;

        try {
            let response;
            if (isEditMode) {
                const updatePayload: AppRole = {
                    ...basePayload,
                    id: initialRole!.id,
                } as AppRole;
                response = await put<AppRole>(`/api/settings/roles/${updatePayload.id}`, updatePayload);
            } else {
                const { id, ...createPayloadWithoutId } = basePayload as any;
                response = await post<AppRole>('/api/settings/roles', createPayloadWithoutId);
            }

            // Check for API errors (already formatted as string by useApi hook)
            if (response.error) {
                throw new Error(response.error);
            }

            const savedRoleData = response.data as AppRole;
            toast({ title: 'Success', description: `Role "${savedRoleData.name}" ${isEditMode ? 'updated' : 'created'}.` });
            reset(savedRoleData, { keepDirty: false });
            onSubmitSuccess();
            setTimeout(() => {
                onOpenChange(false);
            }, 0);

        } catch (err: any) {
            console.error('Error submitting role form:', err);
            const errorMsg = err.message || 'An unexpected error occurred.';
            setFormError(errorMsg);
            toast({ title: 'Save Error', description: errorMsg, variant: 'destructive' });
        }
    };

    return (
        <Dialog open={isOpen} onOpenChange={handleCloseDialog}>
            <DialogContent className="max-w-2xl max-h-[90vh] flex flex-col">
                <DialogHeader>
                    <DialogTitle>
                        {isEditMode ? t('roles.dialog.editTitle', { name: initialRole?.name || 'Role' }) : t('roles.dialog.createTitle')}
                    </DialogTitle>
                    <DialogDescription>
                        {t('roles.dialog.description')}
                    </DialogDescription>
                </DialogHeader>

                <form onSubmit={handleSubmit(onSubmit)} className="flex-1 flex flex-col">
                    <Tabs defaultValue="general" className="flex-1 flex flex-col">
                        <TabsList className="w-full justify-start">
                            <TabsTrigger value="general">{t('roles.tabs.general')}</TabsTrigger>
                            <TabsTrigger value="privileges">{t('roles.tabs.privileges')}</TabsTrigger>
                            <TabsTrigger value="permissions">{t('roles.tabs.permissions')}</TabsTrigger>
                            <TabsTrigger value="deployment">{t('roles.tabs.deployment')}</TabsTrigger>
                            <TabsTrigger value="access-control">{t('roles.tabs.accessControl', 'Access Control')}</TabsTrigger>
                        </TabsList>

                        {/* General Tab */}
                        <TabsContent value="general" className="flex-1 mt-4">
                            <ScrollArea className="h-[calc(90vh-280px)]">
                                <div className="space-y-4 pr-4 px-1 py-1">
                                    {/* Basic Role Info */}
                                    <div>
                                        <Label htmlFor="name">{t('roles.general.roleName')}</Label>
                                        <Input
                                            id="name"
                                            {...register("name", { required: t('roles.general.roleNameRequired') })}
                                            readOnly={isEditMode && initialRole?.id === 'admin'}
                                            className={(isEditMode && initialRole?.id === 'admin') ? "bg-muted" : ""}
                                        />
                                        {errors.name && <p className="text-sm text-red-600 mt-1">{errors.name.message}</p>}
                                    </div>

                                    <div>
                                        <Label htmlFor="description">{t('roles.general.description')}</Label>
                                        <Textarea id="description" {...register("description")} />
                                    </div>

                                    <div>
                                        <Label htmlFor="assigned_groups">{t('roles.general.assignedGroups')}</Label>
                                        <Controller
                                            name="assigned_groups"
                                            control={control}
                                            render={({ field }) => {
                                                const value = normaliseAssignedGroups(field.value);
                                                return (
                                                    <PrincipalPicker
                                                        id="assigned_groups"
                                                        multiple
                                                        accepts={['group']}
                                                        value={value}
                                                        onChange={(next) => field.onChange(next)}
                                                        placeholder={t('roles.general.assignedGroupsPlaceholder')}
                                                        aria-label={t('roles.general.assignedGroups')}
                                                    />
                                                );
                                            }}
                                        />
                                        {errors.assigned_groups && <p className="text-sm text-red-600 mt-1">{errors.assigned_groups.message}</p>}
                                        <p className="text-xs text-muted-foreground mt-1">{t('roles.general.assignedGroupsHelp')}</p>
                                    </div>
                                </div>
                            </ScrollArea>
                        </TabsContent>

                        {/* Privileges Tab */}
                        <TabsContent value="privileges" className="flex-1 mt-4">
                            <ScrollArea className="h-[calc(90vh-280px)]">
                                <div className="space-y-4 pr-4 px-1 py-1">
                                    {/* Home Sections Selection */}
                                    <div className="space-y-3">
                                        <h4 className="font-medium">{t('roles.privileges.homeSections.title')}</h4>
                                        <p className="text-xs text-muted-foreground">{t('roles.privileges.homeSections.description')}</p>
                                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                            {Object.values(HomeSection).map(section => (
                                                <label key={section} className="flex items-center gap-2 text-sm">
                                                    <input
                                                        type="checkbox"
                                                        {...register('home_sections')}
                                                        value={section}
                                                        defaultChecked={defaultValues.home_sections?.includes(section)}
                                                    />
                                                    <span>{section.replace('_', ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase())}</span>
                                                </label>
                                            ))}
                                        </div>
                                    </div>

                                    {/* Approval Privileges */}
                                    <div className="space-y-3 pt-4 border-t">
                                        <h4 className="font-medium">{t('roles.privileges.approvalPrivileges.title')}</h4>
                                        <p className="text-xs text-muted-foreground">{t('roles.privileges.approvalPrivileges.description')}</p>
                                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                            {Object.values(ApprovalEntity).map(entity => (
                                                <label key={entity} className="flex items-center gap-2 text-sm">
                                                    <input
                                                        type="checkbox"
                                                        {...register(`approval_privileges.${entity}` as const)}
                                                        defaultChecked={Boolean(defaultValues.approval_privileges?.[entity as keyof typeof defaultValues.approval_privileges])}
                                                    />
                                                    <span>{entity.replace('_', ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase())}</span>
                                                </label>
                                            ))}
                                        </div>
                                    </div>

                                    {/* Admin Role Flag */}
                                    <div className="space-y-3 pt-4 border-t">
                                        <h4 className="font-medium">{t('roles.privileges.adminRole.title', 'Admin Role')}</h4>
                                        <p className="text-xs text-muted-foreground">
                                            {t('roles.privileges.adminRole.description', 'Mark this role as the admin role. Only one role should be marked as admin.')}
                                        </p>
                                        <label className="flex items-center gap-2 text-sm">
                                            <input
                                                type="checkbox"
                                                {...register('is_admin')}
                                                defaultChecked={Boolean(defaultValues.is_admin)}
                                            />
                                            <span>{t('roles.privileges.adminRole.label', 'This is the admin role')}</span>
                                        </label>
                                    </div>

                                </div>
                            </ScrollArea>
                        </TabsContent>

                        {/* Permissions Tab */}
                        <TabsContent value="permissions" className="flex-1 mt-4">
                            <ScrollArea className="h-[calc(90vh-280px)]">
                                <div className="space-y-4 pr-4 px-1 py-1">
                                    {/* Feature Permissions */}
                                    <div className="space-y-3">
                                        <h4 className="font-medium">{t('roles.permissions.featurePermissions.title')}</h4>
                                        <p className="text-xs text-muted-foreground">{t('roles.permissions.featurePermissions.description')}</p>
                                        <div className="space-y-1">
                                    {orderedFeatures.map((feature) => {
                                        const featureConf = featuresConfig[feature.id];
                                        if (!featureConf) {
                                            console.warn(`No backend config found for feature ID: ${feature.id}. Skipping permission setting.`);
                                            return null;
                                        }
                                        const allowedLevels = Array.isArray(featureConf.allowed_levels) ? featureConf.allowed_levels : [];

                                        return (
                                            <div key={feature.id} className="flex items-center justify-between space-x-4 py-2 border-b border-gray-200 dark:border-gray-700 last:border-b-0">
                                                <Label htmlFor={`permissions-${feature.id}`} className="text-sm font-normal flex-1">
                                                     {feature.name}
                                                     <p className="text-xs text-muted-foreground">{feature.description}</p>
                                                 </Label>
                                                <div className="w-auto">
                                                    <Controller
                                                        name={`feature_permissions.${feature.id}`}
                                                        control={control}
                                                        render={({ field }) => (
                                                            <Select
                                                                value={field.value || FeatureAccessLevel.NONE}
                                                                onValueChange={field.onChange}
                                                                disabled={allowedLevels.length === 0}
                                                            >
                                                                <SelectTrigger id={`permissions-${feature.id}`} className="w-[180px]">
                                                                    <SelectValue placeholder="Select access" />
                                                                </SelectTrigger>
                                                                <SelectContent>
                                                                    {allowedLevels.length > 0 ? (
                                                                        [...allowedLevels]
                                                                            .sort((a, b) => (ACCESS_LEVEL_ORDER[a] ?? -1) - (ACCESS_LEVEL_ORDER[b] ?? -1))
                                                                            .map(level => (
                                                                                <SelectItem key={level} value={level}>
                                                                                    {level}
                                                                                </SelectItem>
                                                                            ))
                                                                    ) : (
                                                                        <SelectItem value="none" disabled>No levels</SelectItem>
                                                                    )}
                                                                </SelectContent>
                                                            </Select>
                                                        )}
                                                    />
                                                </div>
                                            </div>
                                        );
                                    })}
                                    {/* Backend-only features (not in frontend navigation) */}
                                    {Object.entries(featuresConfig)
                                        .filter(([featureId]) => !orderedFeatures.some(f => f.id === featureId))
                                        .map(([featureId, featureConf]) => {
                                            const allowedLevels = Array.isArray(featureConf.allowed_levels) ? featureConf.allowed_levels : [];
                                            return (
                                                <div key={featureId} className="flex items-center justify-between space-x-4 py-2 border-b border-gray-200 dark:border-gray-700 last:border-b-0">
                                                    <Label htmlFor={`permissions-${featureId}`} className="text-sm font-normal flex-1">
                                                        {featureConf.name || featureId}
                                                        <p className="text-xs text-muted-foreground">Cross-cutting feature</p>
                                                    </Label>
                                                    <div className="w-auto">
                                                        <Controller
                                                            name={`feature_permissions.${featureId}`}
                                                            control={control}
                                                            render={({ field }) => (
                                                                <Select
                                                                    value={field.value || FeatureAccessLevel.NONE}
                                                                    onValueChange={field.onChange}
                                                                    disabled={allowedLevels.length === 0}
                                                                >
                                                                    <SelectTrigger id={`permissions-${featureId}`} className="w-[180px]">
                                                                        <SelectValue placeholder="Select access" />
                                                                    </SelectTrigger>
                                                                    <SelectContent>
                                                                        {allowedLevels.length > 0 ? (
                                                                            [...allowedLevels]
                                                                                .sort((a, b) => (ACCESS_LEVEL_ORDER[a] ?? -1) - (ACCESS_LEVEL_ORDER[b] ?? -1))
                                                                                .map(level => (
                                                                                    <SelectItem key={level} value={level}>
                                                                                        {level}
                                                                                    </SelectItem>
                                                                                ))
                                                                        ) : (
                                                                            <SelectItem value="none" disabled>No levels</SelectItem>
                                                                        )}
                                                                    </SelectContent>
                                                                </Select>
                                                            )}
                                                        />
                                                    </div>
                                                </div>
                                            );
                                        })
                                    }
                                    {Object.keys(featuresConfig).length === 0 && (
                                        <p className="text-sm text-muted-foreground">No features configuration loaded.</p>
                                    )}
                                        </div>
                                    </div>
                                </div>
                            </ScrollArea>
                        </TabsContent>

                        {/* Deployment Tab */}
                        <TabsContent value="deployment" className="flex-1 mt-4">
                            <ScrollArea className="h-[calc(90vh-280px)]">
                                <div className="space-y-4 pr-4 px-1 py-1">
                                    <div className="space-y-3">
                                        <h4 className="font-medium">{t('roles.deployment.title')}</h4>
                                        <p className="text-xs text-muted-foreground">
                                            {t('roles.deployment.description')}
                                        </p>
                                        
                                        <div className="space-y-3 pt-2">
                                            {/* Allowed Catalogs */}
                                            <div>
                                                <Label htmlFor="deployment_policy_catalogs">{t('roles.deployment.allowedCatalogs.label')}</Label>
                                                <Controller
                                                    name="deployment_policy.allowed_catalogs"
                                                    control={control}
                                                    render={({ field }) => (
                                                        <Input
                                                            id="deployment_policy_catalogs"
                                                            placeholder={t('roles.deployment.allowedCatalogs.placeholder')}
                                                            value={Array.isArray(field.value) ? field.value.join(', ') : ''}
                                                            onChange={(e) => {
                                                                const catalogs = e.target.value.split(',').map(c => c.trim()).filter(Boolean);
                                                                field.onChange(catalogs);
                                                            }}
                                                        />
                                                    )}
                                                />
                                                <p className="text-xs text-muted-foreground mt-1">
                                                    {t('roles.deployment.allowedCatalogs.help')}
                                                </p>
                                            </div>
                                            
                                            {/* Allowed Schemas */}
                                            <div>
                                                <Label htmlFor="deployment_policy_schemas">{t('roles.deployment.allowedSchemas.label')}</Label>
                                                <Controller
                                                    name="deployment_policy.allowed_schemas"
                                                    control={control}
                                                    render={({ field }) => (
                                                        <Input
                                                            id="deployment_policy_schemas"
                                                            placeholder={t('roles.deployment.allowedSchemas.placeholder')}
                                                            value={Array.isArray(field.value) ? field.value.join(', ') : ''}
                                                            onChange={(e) => {
                                                                const schemas = e.target.value.split(',').map(s => s.trim()).filter(Boolean);
                                                                field.onChange(schemas);
                                                            }}
                                                        />
                                                    )}
                                                />
                                                <p className="text-xs text-muted-foreground mt-1">
                                                    {t('roles.deployment.allowedSchemas.help')}
                                                </p>
                                            </div>
                                            
                                            {/* Default Catalog/Schema */}
                                            <div className="grid grid-cols-2 gap-3">
                                                <div>
                                                    <Label htmlFor="deployment_policy_default_catalog">{t('roles.deployment.defaultCatalog.label')}</Label>
                                                    <Input
                                                        id="deployment_policy_default_catalog"
                                                        {...register('deployment_policy.default_catalog')}
                                                        placeholder={t('roles.deployment.defaultCatalog.placeholder')}
                                                    />
                                                    <p className="text-xs text-muted-foreground mt-1">{t('roles.deployment.defaultCatalog.help')}</p>
                                                </div>
                                                <div>
                                                    <Label htmlFor="deployment_policy_default_schema">{t('roles.deployment.defaultSchema.label')}</Label>
                                                    <Input
                                                        id="deployment_policy_default_schema"
                                                        {...register('deployment_policy.default_schema')}
                                                        placeholder={t('roles.deployment.defaultSchema.placeholder')}
                                                    />
                                                    <p className="text-xs text-muted-foreground mt-1">{t('roles.deployment.defaultSchema.help')}</p>
                                                </div>
                                            </div>
                                            
                                            {/* Approval Settings */}
                                            <div className="space-y-2 pt-2">
                                                <label className="flex items-center gap-2 text-sm">
                                                    <input
                                                        type="checkbox"
                                                        {...register('deployment_policy.require_approval')}
                                                        defaultChecked={Boolean(defaultValues.deployment_policy?.require_approval)}
                                                    />
                                                    <span>{t('roles.deployment.requireApproval')}</span>
                                                </label>
                                                <label className="flex items-center gap-2 text-sm">
                                                    <input
                                                        type="checkbox"
                                                        {...register('deployment_policy.can_approve_deployments')}
                                                        defaultChecked={Boolean(defaultValues.deployment_policy?.can_approve_deployments)}
                                                    />
                                                    <span>{t('roles.deployment.canApprove')}</span>
                                                </label>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </ScrollArea>
                        </TabsContent>

                        {/* Access Control Tab */}
                        <TabsContent value="access-control" className="flex-1 mt-4">
                            <ScrollArea className="h-[calc(90vh-280px)]">
                                <div className="space-y-6 pr-4 px-1 py-1">
                                    {/* Requestable By Roles */}
                                    <div className="space-y-3">
                                        <h4 className="font-medium">{t('roles.accessControl.requestableBy.title', 'Who can request this role?')}</h4>
                                        <p className="text-xs text-muted-foreground">
                                            {t('roles.accessControl.requestableBy.description', 'Select which roles are allowed to request access to this role. Users with these roles will see this role in their requestable roles list.')}
                                        </p>
                                        <Controller
                                            name="requestable_by_roles"
                                            control={control}
                                            render={({ field }) => {
                                                const selectedRoles = field.value || [];
                                                const toggleRole = (roleId: string) => {
                                                    if (selectedRoles.includes(roleId)) {
                                                        field.onChange(selectedRoles.filter((r: string) => r !== roleId));
                                                    } else {
                                                        field.onChange([...selectedRoles, roleId]);
                                                    }
                                                };
                                                return (
                                                    <div className="space-y-2 border rounded-md p-3 bg-muted/30">
                                                        {/* Special "No Role" option */}
                                                        <label className="flex items-center gap-2 text-sm p-2 rounded hover:bg-muted cursor-pointer">
                                                            <Checkbox
                                                                checked={selectedRoles.includes(NO_ROLE_SENTINEL)}
                                                                onCheckedChange={() => toggleRole(NO_ROLE_SENTINEL)}
                                                            />
                                                            <span className="font-medium text-primary">
                                                                {t('roles.accessControl.noRole', 'Users with no role (new users)')}
                                                            </span>
                                                        </label>
                                                        <div className="border-t my-2" />
                                                        {/* Available roles (excluding current role being edited) */}
                                                        {availableRoles
                                                            .filter(r => r.id !== initialRole?.id)
                                                            .map(role => (
                                                                <label key={role.id} className="flex items-center gap-2 text-sm p-2 rounded hover:bg-muted cursor-pointer">
                                                                    <Checkbox
                                                                        checked={selectedRoles.includes(role.id)}
                                                                        onCheckedChange={() => toggleRole(role.id)}
                                                                    />
                                                                    <span>{role.name}</span>
                                                                    {role.description && (
                                                                        <span className="text-xs text-muted-foreground ml-1">- {role.description}</span>
                                                                    )}
                                                                </label>
                                                            ))
                                                        }
                                                        {availableRoles.length === 0 && (
                                                            <p className="text-sm text-muted-foreground italic">
                                                                {t('roles.accessControl.noRolesAvailable', 'No other roles available')}
                                                            </p>
                                                        )}
                                                    </div>
                                                );
                                            }}
                                        />
                                    </div>

                                    {/* Approver Roles */}
                                    <div className="space-y-3 pt-4 border-t">
                                        <h4 className="font-medium">{t('roles.accessControl.approvers.title', 'Who can approve requests for this role?')}</h4>
                                        <p className="text-xs text-muted-foreground">
                                            {t('roles.accessControl.approvers.description', 'Select which roles can approve access requests for this role. Users with these roles will receive notifications when someone requests this role.')}
                                        </p>
                                        <Controller
                                            name="approver_roles"
                                            control={control}
                                            render={({ field }) => {
                                                const selectedApprovers = field.value || [];
                                                const toggleApprover = (roleId: string) => {
                                                    if (selectedApprovers.includes(roleId)) {
                                                        field.onChange(selectedApprovers.filter((r: string) => r !== roleId));
                                                    } else {
                                                        field.onChange([...selectedApprovers, roleId]);
                                                    }
                                                };
                                                return (
                                                    <div className="space-y-2 border rounded-md p-3 bg-muted/30">
                                                        {/* Available roles (including Admin as default approver) */}
                                                        {availableRoles
                                                            .filter(r => r.id !== initialRole?.id)
                                                            .map(role => (
                                                                <label key={role.id} className="flex items-center gap-2 text-sm p-2 rounded hover:bg-muted cursor-pointer">
                                                                    <Checkbox
                                                                        checked={selectedApprovers.includes(role.id)}
                                                                        onCheckedChange={() => toggleApprover(role.id)}
                                                                    />
                                                                    <span>{role.name}</span>
                                                                    {role.name === 'Admin' && (
                                                                        <span className="text-xs bg-primary/10 text-primary px-1.5 py-0.5 rounded">
                                                                            {t('roles.accessControl.defaultApprover', 'Default')}
                                                                        </span>
                                                                    )}
                                                                </label>
                                                            ))
                                                        }
                                                        {availableRoles.length === 0 && (
                                                            <p className="text-sm text-muted-foreground italic">
                                                                {t('roles.accessControl.noRolesAvailable', 'No other roles available')}
                                                            </p>
                                                        )}
                                                    </div>
                                                );
                                            }}
                                        />
                                        <p className="text-xs text-muted-foreground mt-2">
                                            {t('roles.accessControl.approvers.hint', 'If no approvers are selected, requests will be sent to Admin by default.')}
                                        </p>
                                    </div>
                                </div>
                            </ScrollArea>
                        </TabsContent>
                    </Tabs>

                    {/* Form Error Display */}
                    {formError && (
                        <Alert variant="destructive" className="mt-4">
                            <AlertCircle className="h-4 w-4" />
                            <AlertDescription>{formError}</AlertDescription>
                        </Alert>
                    )}

                    <DialogFooter className="pt-4 border-t mt-4">
                        <Button type="button" variant="outline" onClick={() => handleCloseDialog(false)} disabled={isSubmitting}>{t('roles.actions.cancel')}</Button>
                        <Button type="submit" disabled={isSubmitting}>
                            {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                            {isEditMode ? t('roles.actions.update') : t('roles.actions.create')}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
};

export default RoleFormDialog; 