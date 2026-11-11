import { create } from 'zustand';
import { useEffect } from 'react';
import { UserPermissions, FeatureAccessLevel, AppRole } from '@/types/settings'; // Import AppRole
import { ACCESS_LEVEL_ORDER } from '@/lib/permissions';
interface PermissionsState {
    permissions: UserPermissions; // User's effective permissions (may be overridden)
    actualPermissions: UserPermissions; // User's actual permissions based on groups (never overridden)
    isLoading: boolean;
    error: string | null;
    availableRoles: AppRole[];    // List of all possible roles
    requestableRoles: AppRole[];  // List of roles the user can request
    appliedRoleId: string | null; // ID of the role currently being impersonated/applied
    /** Feature ids the user's roles hide from the menus (#1325); visibility only. */
    hiddenNavFeatures: string[];
    _isInitializing: boolean; // Internal flag to prevent concurrent initializations
    _initAttempted: boolean; // Prevents infinite retry on failure
    fetchPermissions: () => Promise<void>;
    fetchActualPermissions: () => Promise<void>; // Fetch actual non-overridden permissions
    fetchAvailableRoles: () => Promise<void>; // New action
    fetchRequestableRoles: () => Promise<void>; // Fetch roles the user can request
    fetchAppliedOverride: () => Promise<void>; // New action to read persisted override
    fetchNavigation: () => Promise<void>; // Hidden menu features for the applied role(s)
    setRoleOverride: (roleId: string | null) => Promise<void>; // Returns Promise so callers can await
    hasPermission: (featureId: string, requiredLevel: FeatureAccessLevel) => boolean;
    getPermissionLevel: (featureId: string) => FeatureAccessLevel;
    initializeStore: () => Promise<void>; // New action
}

// Helper function to get permission level, considering override
const getPermissionLevelFromState = (
    permissions: UserPermissions,
    appliedRoleId: string | null,
    availableRoles: AppRole[],
    featureId: string
): FeatureAccessLevel => {
    if (appliedRoleId) {
        const overrideRole = availableRoles.find(role => role.id === appliedRoleId);
        return overrideRole?.feature_permissions?.[featureId] || FeatureAccessLevel.NONE;
    }
    // Default to actual user permissions if no override
    return permissions[featureId] || FeatureAccessLevel.NONE;
};

const usePermissionsStore = create<PermissionsState>((set, get) => ({
    permissions: {},
    actualPermissions: {},
    isLoading: false,
    error: null,
    availableRoles: [],
    requestableRoles: [],
    appliedRoleId: null,
    hiddenNavFeatures: [],
    _isInitializing: false,
    _initAttempted: false,

    fetchPermissions: async () => {
        try {
            const response = await fetch('/api/user/permissions', { cache: 'no-store' });
            if (!response.ok) {
                let errorMsg = `HTTP error! status: ${response.status}`;
                try {
                     const errData = await response.json();
                     errorMsg = errData.detail || errorMsg;
                } catch (e) { /* Ignore JSON parsing error */ }
                throw new Error(errorMsg);
            }
            const data: UserPermissions = await response.json();
            set({ permissions: data, error: null });
        } catch (error: any) {
            console.error("Failed to fetch user permissions:", error);
            set({ permissions: {}, error: error.message || 'Failed to load permissions.' });
            throw error;
        }
    },

    fetchActualPermissions: async () => {
        try {
            const response = await fetch('/api/user/actual-permissions', { cache: 'no-store' });
            if (!response.ok) {
                let errorMsg = `HTTP error! status: ${response.status}`;
                try {
                     const errData = await response.json();
                     errorMsg = errData.detail || errorMsg;
                } catch (e) { /* Ignore JSON parsing error */ }
                throw new Error(errorMsg);
            }
            const data: UserPermissions = await response.json();
            set({ actualPermissions: data, error: null });
        } catch (error: any) {
            console.error("Failed to fetch actual user permissions:", error);
            set({ actualPermissions: {}, error: error.message || 'Failed to load actual permissions.' });
            throw error;
        }
    },

    fetchAvailableRoles: async () => {
        try {
            const response = await fetch('/api/settings/roles', { cache: 'no-store' });
            if (!response.ok) {
                 let errorMsg = `HTTP error! status: ${response.status}`;
                 try {
                      const errData = await response.json();
                      errorMsg = errData.detail || errorMsg;
                 } catch (e) { /* Ignore */ }
                 throw new Error(errorMsg);
            }
            const data: AppRole[] = await response.json();
            set({ availableRoles: data, error: null });
        } catch (error: any) {
             console.error("Failed to fetch available roles:", error);
             set({ availableRoles: [], error: error.message || 'Failed to load roles.' });
             throw error;
        }
    },

    fetchRequestableRoles: async () => {
        try {
            const response = await fetch('/api/user/requestable-roles', { cache: 'no-store' });
            if (!response.ok) {
                 let errorMsg = `HTTP error! status: ${response.status}`;
                 try {
                      const errData = await response.json();
                      errorMsg = errData.detail || errorMsg;
                 } catch (e) { /* Ignore */ }
                 throw new Error(errorMsg);
            }
            const data: AppRole[] = await response.json();
            set({ requestableRoles: data, error: null });
        } catch (error: any) {
             console.error("Failed to fetch requestable roles:", error);
             set({ requestableRoles: [], error: error.message || 'Failed to load requestable roles.' });
             // Don't throw - this is not critical for app operation
        }
    },

    fetchAppliedOverride: async () => {
        try {
            const response = await fetch('/api/user/role-override', { cache: 'no-store' });
            if (!response.ok) {
                // If endpoint missing/fails, don't break UI
                return;
            }
            const data: { role_id: string | null } = await response.json();
            set({ appliedRoleId: data?.role_id ?? null });
        } catch {
            // ignore
        }
    },

    fetchNavigation: async () => {
        // Not critical: on failure the menus show every feature the user can access.
        try {
            const response = await fetch('/api/user/navigation', { cache: 'no-store' });
            if (!response.ok) {
                set({ hiddenNavFeatures: [] });
                return;
            }
            const data: { hidden_features?: unknown } = await response.json();
            const hidden = Array.isArray(data?.hidden_features)
                ? data.hidden_features.filter((id): id is string => typeof id === 'string')
                : [];
            set({ hiddenNavFeatures: hidden });
        } catch {
            set({ hiddenNavFeatures: [] });
        }
    },

    initializeStore: async () => {
        // --- Guard 1: Already actively initializing? ---
        if (get()._isInitializing) {
            return;
        }

        // --- Guard 2: Already attempted (prevents infinite retry on failure) ---
        if (get()._initAttempted) {
            return;
        }

        // --- Guard 3: Already successfully loaded? ---
        const { isLoading, permissions, actualPermissions, availableRoles } = get();
        const alreadyLoaded = !isLoading && (Object.keys(permissions).length > 0 || Object.keys(actualPermissions).length > 0 || availableRoles.length > 0);
        if (alreadyLoaded) {
            return;
        }

        set({ isLoading: true, _isInitializing: true, _initAttempted: true, error: null });

        try {
            // Use the instance methods from get() to ensure the latest state is used
            await Promise.all([
                get().fetchPermissions(),
                get().fetchActualPermissions(),
                get().fetchAvailableRoles(),
                get().fetchRequestableRoles(),
                get().fetchAppliedOverride(),
                get().fetchNavigation(),
            ]);
            // NOTE: isLoading and _isInitializing are reset in finally block
        } catch (error: any) {
            console.error("Error caught during permissions store initialization Promise.all:", error);
            set({ error: error.message || "Initialization failed." }); // Set error state
            // NOTE: isLoading and _isInitializing are reset in finally block
        } finally {
            set({ isLoading: false, _isInitializing: false }); // Reset flags regardless of outcome
        }
    },

    setRoleOverride: async (roleId: string | null) => {
        // Optimistic local state update
        set({ appliedRoleId: roleId });
        try {
            await fetch('/api/user/role-override', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role_id: roleId })
            });
        } catch { /* ignore */ }
        // Force-refresh state so views recompute immediately
        try {
            await Promise.all([
                get().fetchPermissions(),
                get().fetchAvailableRoles(),
                get().fetchAppliedOverride(),
                get().fetchNavigation(),
            ]);
        } catch { /* ignore */ }
    },

    hasPermission: (featureId: string, requiredLevel: FeatureAccessLevel): boolean => {
        const state = get();
        const userLevel = getPermissionLevelFromState(
            state.permissions,
            state.appliedRoleId,
            state.availableRoles,
            featureId
        );
        return ACCESS_LEVEL_ORDER[userLevel] >= ACCESS_LEVEL_ORDER[requiredLevel];
    },

    getPermissionLevel: (featureId: string): FeatureAccessLevel => {
        const state = get();
        return getPermissionLevelFromState(
            state.permissions,
            state.appliedRoleId,
            state.availableRoles,
            featureId
        );
    },
}));

// Hook to initialize the store (fetch permissions AND roles on first use)
export const usePermissions = () => {
    const state = usePermissionsStore();
    
    useEffect(() => {
        if (state._initAttempted || state.isLoading || state._isInitializing) return;

        const hasData = Object.keys(state.permissions).length > 0
            || Object.keys(state.actualPermissions).length > 0
            || state.availableRoles.length > 0;
        if (!hasData) {
            state.initializeStore();
        }
    }, [state.initializeStore, state._initAttempted, state.isLoading, state._isInitializing,
        state.permissions, state.actualPermissions, state.availableRoles]);

    return state;
};

export default usePermissionsStore;