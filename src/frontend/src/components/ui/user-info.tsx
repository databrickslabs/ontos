import { useState, useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuGroup,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
} from '@/components/ui/dropdown-menu';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { LogOut, User as UserIcon, FlaskConical, Beaker, Users as UsersIcon, Settings, Info, TestTube2 } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';
import { usePermissions } from '@/stores/permissions-store';
import useTestPersonaStore from '@/stores/test-persona-store';
import { FeatureAccessLevel, AppRole } from '@/types/settings';
import { ACCESS_LEVEL_ORDER } from '../../lib/permissions';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useNavigate } from 'react-router-dom';
import UserProfileDialog from '@/components/ui/user-profile-dialog';
interface UserInfoData {
  email: string | null;
  username: string | null;
  user: string | null;
  ip: string | null;
  groups: string[] | null;
}

// Helper function to get a display name for the highest access level
const getHighestAccessLevelName = (userPermissions: Record<string, FeatureAccessLevel>): string => {
    let maxLevel = FeatureAccessLevel.NONE;
    let maxLevelOrder = ACCESS_LEVEL_ORDER[maxLevel];

    for (const featureId in userPermissions) {
        const level = userPermissions[featureId];
        const levelOrder = ACCESS_LEVEL_ORDER[level];
        if (levelOrder > maxLevelOrder) {
            maxLevel = level;
            maxLevelOrder = levelOrder;
        }
    }

    switch (maxLevel) {
        case FeatureAccessLevel.ADMIN: return 'Admin Access';
        case FeatureAccessLevel.READ_WRITE: return 'Read/Write Access';
        case FeatureAccessLevel.READ_ONLY: return 'Read-Only Access';
        case FeatureAccessLevel.NONE: return 'No Access';
        default: return 'Unknown Access';
    }
};

// Map calculated level names to expected canonical role names (available for future use)
// const CANONICAL_ROLE_NAMES: Record<string, string | null> = {
//     'Admin Access': 'Admin',
//     'Read/Write Access': 'Read Write',
//     'Read-Only Access': 'Read Only',
//     'No Access': null,
//     'Unknown Access': null,
// };

export default function UserInfo() {
  const { t } = useTranslation('common');
  const [userInfo, setUserInfo] = useState<UserInfoData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const hasFetched = useRef(false);
  const { showBeta, showAlpha, actions: visibilityActions } = useFeatureVisibilityStore();
  const {
      permissions,
      isLoading: permissionsLoading,
      availableRoles,
      appliedRoleId,
      setRoleOverride,
      initializeStore,
      hasPermission,
  } = usePermissions();
  const {
      enabled: testPersonasEnabled,
      personas: testPersonas,
      selectedPersonaId: selectedTestPersonaId,
      token: testToken,
      setPersona: setTestPersona,
  } = useTestPersonaStore();
  const activeTestPersona = useMemo(
      () => testPersonas.find((p) => p.id === selectedTestPersonaId) || null,
      [testPersonas, selectedTestPersonaId],
  );

  const handleTestPersonaChange = (value: string) => {
      const next = value === 'none' ? null : value;
      if (next === selectedTestPersonaId) return;
      setTestPersona(next);
      // Hard reload so every store (user, permissions, notifications, etc.) is
      // re-hydrated with the new identity. Cheaper and more correct than
      // teaching every store to handle mid-session identity swaps.
      window.location.reload();
  };

  // Hide the Settings menu item when the user lacks the layout gate;
  // the route would otherwise redirect them home anyway.
  const hasSettingsAccess = hasPermission('settings', FeatureAccessLevel.READ_ONLY);

  // Use a string state for the radio group value, mapping null to 'actual'
  const [radioValue, setRadioValue] = useState<string>(appliedRoleId || 'actual');

  // Profile dialog state
  const [profileDialogOpen, setProfileDialogOpen] = useState(false);

  // Get navigate function
  const navigate = useNavigate();

  useEffect(() => {
    // Update radioValue if appliedRoleId changes externally
    setRadioValue(appliedRoleId || 'actual');
  }, [appliedRoleId]);

  useEffect(() => {
    if (hasFetched.current) return;
    
    async function fetchUserDetails() {
      try {
        const response = await fetch('/api/user/details');
        if (!response.ok) {
          // Throw an error to trigger the fallback
          throw new Error(`Details fetch failed: ${response.status}`); 
        }
        const data: UserInfoData = await response.json();
        setUserInfo(data);
        setError(null); // Clear previous errors if successful
      } catch (detailsError: any) {
        console.warn('Failed to fetch user details from SDK, falling back to headers:', detailsError.message);
        // Fallback to fetching basic info from headers
        try {
            const fallbackResponse = await fetch('/api/user/info');
            if (!fallbackResponse.ok) {
                throw new Error(`Fallback fetch failed: ${fallbackResponse.status}`);
            }
            const fallbackData: UserInfoData = await fallbackResponse.json();
            setUserInfo(fallbackData);
            setError(null); // Clear previous errors if fallback successful
        } catch (fallbackError: any) {
            console.error('Failed to load user information from both endpoints:', fallbackError);
            setError(fallbackError.message || 'Failed to load user information');
            setUserInfo(null); // Ensure userInfo is null on final failure
        }
      }
    }
    
    fetchUserDetails();
    hasFetched.current = true;
  }, []);

  // Ensure we refresh permissions/roles on mount (and when switching back to page)
  useEffect(() => {
    // On mount, ensure the permissions store is initialized (will also pull persisted override)
    initializeStore();
  }, [initializeStore]);

  // Load canonical actual role name (role inferred from groups) for the user
  const [canonicalActualRoleName, setCanonicalActualRoleName] = useState<string | null>(null);
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/user/actual-role', { cache: 'no-store' });
        if (res.ok) {
          const data = await res.json();
          const roleName = data?.role?.name ?? null;
          setCanonicalActualRoleName(roleName);
        }
      } catch { /* ignore */ }
    })();
  }, []);

  // Determine if user can switch roles. The admin gate (full impersonation across
  // all roles) is now membership in an AppRole flagged is_admin — NOT settings:ADMIN.
  // See #404: settings:ADMIN should only govern Settings administration, while admin-
  // level capabilities like impersonation belong to the Ontos admin role.
  const isLocalDev = userInfo?.username === 'localdev';

  // Membership-scoped role set: roles whose assigned_groups intersect the user's groups.
  // Fix for regression where end users belonging to 2+ roles could not switch between them —
  // the previous gate was admin-only, so non-admin multi-role users saw no switcher at all.
  // Group comparison is case-insensitive because `assigned_groups` and `userInfo.groups` may
  // originate from different sources (settings.yaml vs SCIM/identity headers).
  const myRoles = useMemo<AppRole[]>(() => {
      const groups = userInfo?.groups;
      if (!groups || groups.length === 0) return [];
      const groupSet = new Set(groups.map(g => (g || '').toLowerCase()));
      return availableRoles.filter(role =>
          (role.assigned_groups || []).some(g => groupSet.has((g || '').toLowerCase()))
      );
  }, [userInfo?.groups, availableRoles]);

  // Ontos admin = user belongs to any AppRole flagged is_admin (canonical check,
  // mirrors AuthorizationManager.is_user_ontos_admin on the backend).
  const isAdminActual = useMemo<boolean>(() => {
      const groups = userInfo?.groups;
      if (!groups || groups.length === 0) return false;
      const groupSet = new Set(groups.map(g => (g || '').toLowerCase()));
      return availableRoles.some(role =>
          role.is_admin === true &&
          (role.assigned_groups || []).some(g => groupSet.has((g || '').toLowerCase()))
      );
  }, [userInfo?.groups, availableRoles]);

  // Admins/localdev keep the impersonation power (all roles); non-admins with 2+ membership-matched
  // roles get a membership-scoped switcher. Single-role users still don't see the switcher.
  const canSwitchRoles = !permissionsLoading && (isLocalDev || isAdminActual || myRoles.length >= 2);

  const displayName = userInfo?.user || userInfo?.username || userInfo?.email || 'Loading...';
  const initials = displayName === 'Loading...' ? '?' : displayName.charAt(0).toUpperCase();
  const userEmail = userInfo?.email;

  let displayRoleName = 'Loading...';
  let highestActualLevelName = 'Loading...'; // Store the display name for the actual level
  // Canonical name available for future role display features
  // let highestActualCanonicalRoleName: string | null = null;

  if (!permissionsLoading) {
      highestActualLevelName = getHighestAccessLevelName(permissions);
      // highestActualCanonicalRoleName = CANONICAL_ROLE_NAMES[highestActualLevelName];

      if (appliedRoleId) {
          const appliedRole = availableRoles.find(role => role.id === appliedRoleId);
          displayRoleName = appliedRole?.name || 'Unknown Role';
      } else {
          // When no override is applied, show canonical role if available
          displayRoleName = canonicalActualRoleName || highestActualLevelName;
      }
  }

  // Filter available roles to exclude the one matching the highest actual canonical name
  // Hide the canonical actual role from the override list to avoid duplication with the "Actual" entry.
  // Admins/localdev see all roles minus canonical (impersonation power preserved).
  // Non-admin multi-role users see ONLY roles they belong to, minus canonical.
  const baseRolesForOverride = (isAdminActual || isLocalDev) ? availableRoles : myRoles;
  const filteredRolesForOverride = baseRolesForOverride.filter((role) => role.name !== (canonicalActualRoleName || ''));

  // Handle RadioGroup changes
  const handleRoleChange = async (value: string) => {
      setRadioValue(value);
      if (value === 'actual') {
          await setRoleOverride(null);
      } else {
          await setRoleOverride(value);
      }
      navigate('/');
  };

  return (
    <>
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
            variant="ghost"
            className="relative h-8 w-8 rounded-full"
            // Subtle persistent visual cue so testers don't forget they're
            // acting as someone else.
            title={activeTestPersona ? `Acting as ${activeTestPersona.label} (test mode)` : undefined}
        >
          <Avatar className={`h-8 w-8 ${activeTestPersona ? 'ring-2 ring-yellow-500' : ''}`}>
            <AvatarFallback>{initials}</AvatarFallback>
          </Avatar>
          {activeTestPersona && (
            <span className="absolute -bottom-1 -right-1 h-3 w-3 rounded-full bg-yellow-500 border-2 border-background" />
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-1">
            <p className="text-sm font-medium leading-none">{displayName}</p>
            {userEmail && userEmail !== displayName && (
              <p className="text-xs leading-none text-muted-foreground">{userEmail}</p>
            )}
            <p className="text-xs leading-none text-muted-foreground pt-1">
              {t('userMenu.role')}: {displayRoleName}
              {appliedRoleId && ' (Override)'}
            </p>
            {!userInfo && !error && <p className="text-xs text-muted-foreground">Loading info...</p>}
            {error && (
              <p className="text-xs text-destructive">Error: {error}</p>
            )}
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
            <DropdownMenuItem onSelect={() => setProfileDialogOpen(true)}>
                <UserIcon className="mr-2 h-4 w-4" />
                <span>{t('userMenu.profile')}</span>
            </DropdownMenuItem>
            {hasSettingsAccess && (
                <DropdownMenuItem onSelect={() => navigate('/settings')}>
                    <Settings className="mr-2 h-4 w-4" />
                    <span>{t('userMenu.settings', 'Settings')}</span>
                </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={() => navigate('/about')}>
                <Info className="mr-2 h-4 w-4" />
                <span>{t('userMenu.about', 'About')}</span>
            </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        {testPersonasEnabled && (
            <>
            <DropdownMenuGroup>
                <DropdownMenuLabel className="text-xs font-semibold text-muted-foreground px-2 py-1.5 flex items-center justify-between">
                    <span className="flex items-center">
                        <TestTube2 className="mr-1.5 h-3.5 w-3.5" />
                        Test persona
                    </span>
                    {activeTestPersona ? (
                        <Badge variant="outline" className="text-[10px] border-yellow-500 text-yellow-700 dark:text-yellow-400">
                            Active
                        </Badge>
                    ) : !testToken ? (
                        <Badge variant="outline" className="text-[10px]" title="Set VITE_TEST_USER_TOKEN or localStorage['ucapp.testToken'] to enable">
                            No token
                        </Badge>
                    ) : null}
                </DropdownMenuLabel>
                <ScrollArea className="max-h-[180px] overflow-y-auto">
                    <DropdownMenuRadioGroup
                        value={selectedTestPersonaId || 'none'}
                        onValueChange={handleTestPersonaChange}
                    >
                        <DropdownMenuRadioItem value="none" disabled={!testToken}>
                            <UserIcon className="mr-1.5 h-3.5 w-3.5" />
                            None (real identity)
                        </DropdownMenuRadioItem>
                        {testPersonas.map((p) => (
                            <DropdownMenuRadioItem
                                key={p.id}
                                value={p.id}
                                disabled={!testToken}
                                className="flex items-center"
                                title={p.description}
                            >
                                <TestTube2 className="mr-1.5 h-3.5 w-3.5" />
                                <span className="flex flex-col">
                                    <span>{p.label}</span>
                                    <span className="text-[10px] text-muted-foreground">{p.email}</span>
                                </span>
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                </ScrollArea>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            </>
        )}
        {canSwitchRoles && (
            <>
            <DropdownMenuGroup>
                <DropdownMenuLabel className="text-xs font-semibold text-muted-foreground px-2 py-1.5 flex items-center">
                    <UsersIcon className="mr-1.5 h-3.5 w-3.5" /> {t('userMenu.applyRoleOverride')}
                </DropdownMenuLabel>
                <ScrollArea className="max-h-[150px] overflow-y-auto">
                    <DropdownMenuRadioGroup value={radioValue} onValueChange={handleRoleChange}>
                        <DropdownMenuRadioItem value="actual">
                            <UserIcon className="mr-1.5 h-3.5 w-3.5" />
                            {(canonicalActualRoleName || highestActualLevelName)} (Actual)
                        </DropdownMenuRadioItem>
                        {filteredRolesForOverride.map((role: AppRole) => (
                            <DropdownMenuRadioItem
                                key={role.id}
                                value={role.id}
                                className="flex items-center"
                            >
                                <UsersIcon className="mr-1.5 h-3.5 w-3.5" />
                                {role.name}
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                </ScrollArea>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            </>
        )}
        <DropdownMenuGroup>
            <DropdownMenuLabel className="text-xs font-semibold text-muted-foreground px-2 py-1.5">{t('userMenu.featurePreviews')}</DropdownMenuLabel>
             <DropdownMenuItem
                className="flex items-center justify-between"
                onSelect={(e) => e.preventDefault()}
             >
                <div className="flex items-center">
                    <FlaskConical className="mr-2 h-4 w-4" />
                    <span>{t('userMenu.showBetaFeatures')}</span>
                </div>
                <Switch
                    checked={showBeta}
                    onCheckedChange={visibilityActions.toggleBeta}
                    className="scale-75"
                 />
            </DropdownMenuItem>
            {isAdminActual && (
             <DropdownMenuItem
                className="flex items-center justify-between"
                onSelect={(e) => e.preventDefault()}
             >
                 <div className="flex items-center">
                    <Beaker className="mr-2 h-4 w-4" />
                    <span>{t('userMenu.showAlphaFeatures')}</span>
                </div>
                <Switch
                    checked={showAlpha}
                    onCheckedChange={visibilityActions.toggleAlpha}
                    className="scale-75"
                />
            </DropdownMenuItem>
            )}
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled>
          <LogOut className="mr-2 h-4 w-4" />
          <span>{t('userMenu.logOut')}</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>

    <UserProfileDialog
      open={profileDialogOpen}
      onOpenChange={setProfileDialogOpen}
    />
  </>
  );
}


