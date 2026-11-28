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
import { LogOut, User as UserIcon, FlaskConical, Beaker, Users as UsersIcon, Settings, Info, TestTube2, ChevronDown, Presentation } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';
import { usePermissions } from '@/stores/permissions-store';
import { isOntosAdmin, rolesHeldBy } from '@/hooks/use-is-ontos-admin';
import useTestPersonaStore from '@/stores/test-persona-store';
import { FeatureAccessLevel, AppRole } from '@/types/settings';
import { ACCESS_LEVEL_ORDER } from '../../lib/permissions';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useNavigate } from 'react-router-dom';
import UserProfileDialog from '@/components/ui/user-profile-dialog';
import { PersonaAvatar } from '@/components/ui/persona-avatar';
import { useToast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';
import {
  personaDisplay,
  readPresenterMode,
  writePresenterMode,
  markPersonaSwitched,
  takePersonaSwitched,
  personaCycleStep,
  cyclePersonaIndex,
  chipDensity,
} from '@/lib/persona-display';
// Key names stay untranslated (they match the physical keys).
const PERSONA_CYCLE_KEYS = 'Alt + ]';

interface UserInfoData {
  email: string | null;
  username: string | null;
  user: string | null;
  ip: string | null;
  groups: string[] | null;
}

// Helper function to get a display name for the highest access level
const getHighestAccessLevelName = (
    userPermissions: Record<string, FeatureAccessLevel>,
    t: (key: string) => string,
): string => {
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
        case FeatureAccessLevel.ADMIN: return t('common:userInfo.accessLevel.admin');
        case FeatureAccessLevel.READ_WRITE: return t('common:userInfo.accessLevel.readWrite');
        case FeatureAccessLevel.READ_ONLY: return t('common:userInfo.accessLevel.readOnly');
        case FeatureAccessLevel.NONE: return t('common:userInfo.accessLevel.none');
        default: return t('common:userInfo.accessLevel.unknown');
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

  const activeDisplay = useMemo(
      () => (activeTestPersona ? personaDisplay(activeTestPersona) : null),
      [activeTestPersona],
  );
  const [presenterMode, setPresenterMode] = useState<boolean>(() => readPresenterMode());
  const { toast } = useToast();

  const handleTestPersonaChange = (value: string) => {
      const next = value === 'none' ? null : value;
      if (next === selectedTestPersonaId) return;
      setTestPersona(next);
      markPersonaSwitched(next);
      // Hard reload so every store (user, permissions, notifications, etc.) is
      // re-hydrated with the new identity. Cheaper and more correct than
      // teaching every store to handle mid-session identity swaps.
      window.location.reload();
  };

  // After a persona switch (which reloads the page), say who we are now.
  useEffect(() => {
      if (!activeTestPersona) return;
      if (takePersonaSwitched() !== activeTestPersona.id) return;
      const d = personaDisplay(activeTestPersona);
      toast({
          duration: 2600,
          className: 'border-l-4',
          style: { borderLeftColor: d.color },
          // `description` (not `title`) because ToastProps types `title` as the HTML string attribute.
          description: (
              <span className="flex items-center gap-3 text-foreground">
                  <PersonaAvatar display={d} className="h-9 w-9" />
                  <span className="flex flex-col">
                      <span className="text-xs font-normal text-muted-foreground">{t('common:userInfo.nowViewingAs')}</span>
                      <span className="text-sm font-semibold">{d.title ? `${d.name} · ${d.title}` : d.name}</span>
                  </span>
              </span>
          ),
      });
  }, [activeTestPersona, toast, t]);

  // Alt+] / Alt+[ cycles through the personas (same reload as picking one).
  useEffect(() => {
      if (!testPersonasEnabled || !testToken || testPersonas.length === 0) return;
      const onKey = (e: KeyboardEvent) => {
          const step = personaCycleStep(e);
          if (!step) return;
          e.preventDefault();
          const current = testPersonas.findIndex((p) => p.id === selectedTestPersonaId);
          const next = cyclePersonaIndex(current, step, testPersonas.length);
          if (next >= 0) handleTestPersonaChange(testPersonas[next].id);
      };
      window.addEventListener('keydown', onKey);
      return () => window.removeEventListener('keydown', onKey);
      // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [testPersonasEnabled, testToken, testPersonas, selectedTestPersonaId]);

  // Track the header width so the chip can step down (see chipDensity).
  const chipRef = useRef<HTMLButtonElement>(null);
  const [headerWidth, setHeaderWidth] = useState<number>(Number.POSITIVE_INFINITY);
  useEffect(() => {
      const header = chipRef.current?.closest('header');
      if (!activeTestPersona || !header || typeof ResizeObserver === 'undefined') return;
      // Border-box width (contentRect leaves out the header's padding).
      const ro = new ResizeObserver(([entry]) => setHeaderWidth(entry.target.getBoundingClientRect().width));
      ro.observe(header);
      return () => ro.disconnect();
  }, [activeTestPersona]);
  const density = chipDensity(headerWidth, presenterMode);
  // Presenter size applies while there is room for the name.
  const big = presenterMode && density !== 'avatar';

  const togglePresenterMode = (on: boolean) => {
      writePresenterMode(on);
      setPresenterMode(on);
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

  // Membership-scoped role set: roles the user holds by group or by assigned user.
  // Fix for regression where end users belonging to 2+ roles could not switch between them —
  // the previous gate was admin-only, so non-admin multi-role users saw no switcher at all.
  // Group comparison is case-insensitive because `assigned_groups` and `userInfo.groups` may
  // originate from different sources (settings.yaml vs SCIM/identity headers).
  const myRoles = useMemo<AppRole[]>(
      () => rolesHeldBy(userInfo?.groups, availableRoles, userInfo?.email),
      [userInfo?.groups, userInfo?.email, availableRoles],
  );

  // Ontos admin = user belongs to any AppRole flagged is_admin. Same check as the
  // menus (useIsOntosAdmin), on the groups this component loads itself.
  const isAdminActual = useMemo<boolean>(
      () => isOntosAdmin(userInfo?.groups, availableRoles, userInfo?.email),
      [userInfo?.groups, userInfo?.email, availableRoles],
  );

  // Admins/localdev keep the impersonation power (all roles); non-admins with 2+ membership-matched
  // roles get a membership-scoped switcher. Single-role users still don't see the switcher.
  const canSwitchRoles = !permissionsLoading && (isLocalDev || isAdminActual || myRoles.length >= 2);

  const loadingText = t('common:states.loading');
  const displayName = userInfo?.user || userInfo?.username || userInfo?.email || loadingText;
  const initials = displayName === loadingText ? '?' : displayName.charAt(0).toUpperCase();
  const userEmail = userInfo?.email;

  let displayRoleName = loadingText;
  let highestActualLevelName = loadingText; // Store the display name for the actual level
  // Canonical name available for future role display features
  // let highestActualCanonicalRoleName: string | null = null;

  if (!permissionsLoading) {
      highestActualLevelName = getHighestAccessLevelName(permissions, t);
      // highestActualCanonicalRoleName = CANONICAL_ROLE_NAMES[highestActualLevelName];

      if (appliedRoleId) {
          const appliedRole = availableRoles.find(role => role.id === appliedRoleId);
          displayRoleName = appliedRole?.name || t('common:userInfo.unknownRole');
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
        {activeTestPersona && activeDisplay ? (
          // Persona chip: who is acting, readable across a room (demos, screenshots).
          <Button
              ref={chipRef}
              variant="outline"
              data-persona-id={activeTestPersona.id}
              data-density={density}
              className={cn(
                  'h-11 max-w-[300px] gap-2.5 rounded-full bg-background py-1 pl-1 pr-2.5 hover:bg-background',
                  big && 'h-14 max-w-[380px] gap-3 pr-3.5',
                  density === 'name' && (big ? 'max-w-[300px]' : 'max-w-[220px]'),
                  // Narrow header: just the ringed avatar plus today's amber dot.
                  density === 'avatar' && 'relative w-11 justify-center border-transparent p-0.5 px-0.5',
              )}
              title={t('common:userInfo.actingAs', { label: activeTestPersona.label })}
          >
            <PersonaAvatar display={activeDisplay} ring className={big ? 'h-[46px] w-[46px] text-base' : 'h-9 w-9 text-[13px]'} />
            <span className={cn('flex min-w-0 flex-col text-left', density === 'avatar' && 'sr-only')}>
              <span className={cn('truncate font-semibold leading-tight', big ? 'text-base' : 'text-[13px]')}>
                {activeDisplay.name}
              </span>
              {activeDisplay.title && density === 'full' && (
                <span className={cn('truncate font-normal leading-tight text-muted-foreground', big ? 'text-[13px]' : 'text-[11px]')}>
                  {activeDisplay.title}
                </span>
              )}
            </span>
            {density === 'avatar' ? (
              <span className="absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-background bg-yellow-500" />
            ) : (
              <>
                <span className="shrink-0 rounded-full border border-yellow-500 px-1.5 text-[10px] font-semibold uppercase tracking-wide text-yellow-700 dark:text-yellow-400">
                  {t('common:userInfo.testBadge')}
                </span>
                <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              </>
            )}
          </Button>
        ) : (
          <Button variant="ghost" className="relative h-8 w-8 rounded-full">
            <Avatar className="h-8 w-8">
              <AvatarFallback>{initials}</AvatarFallback>
            </Avatar>
          </Button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className={testPersonasEnabled ? 'w-[340px]' : 'w-64'}>
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-1">
            <p className="text-sm font-medium leading-none">{displayName}</p>
            {userEmail && userEmail !== displayName && (
              <p className="text-xs leading-none text-muted-foreground">{userEmail}</p>
            )}
            <p className="text-xs leading-none text-muted-foreground pt-1">
              {t('userMenu.role')}: {displayRoleName}
              {appliedRoleId && t('common:userInfo.override')}
            </p>
            {!userInfo && !error && <p className="text-xs text-muted-foreground">{t('common:states.loadingInfo')}</p>}
            {error && (
              <p className="text-xs text-destructive">{t('common:userInfo.error', { message: error })}</p>
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
                <DropdownMenuLabel className="text-xs font-semibold text-muted-foreground px-2 py-1.5 flex items-center justify-between gap-2">
                    <span className="flex items-center">
                        <TestTube2 className="mr-1.5 h-3.5 w-3.5" />
                        {t('common:userInfo.testPersona')}
                    </span>
                    <span className="flex items-center gap-1.5">
                    {testToken && testPersonas.length > 0 && (
                        <kbd className="rounded border px-1 font-mono text-[10px] font-normal" title={t('common:userInfo.cycleShortcut')}>
                            {PERSONA_CYCLE_KEYS}
                        </kbd>
                    )}
                    {activeTestPersona ? (
                        <Badge variant="outline" className="text-[10px] border-yellow-500 text-yellow-700 dark:text-yellow-400">
                            {t('common:status.active')}
                        </Badge>
                    ) : !testToken ? (
                        <Badge variant="outline" className="text-[10px]" title="Set VITE_TEST_USER_TOKEN or localStorage['ucapp.testToken'] to enable">
                            {t('common:userInfo.noToken')}
                        </Badge>
                    ) : null}
                    </span>
                </DropdownMenuLabel>
                <ScrollArea className="max-h-[320px] overflow-y-auto">
                    <DropdownMenuRadioGroup
                        value={selectedTestPersonaId || 'none'}
                        onValueChange={handleTestPersonaChange}
                    >
                        {testPersonas.map((p) => {
                            const d = personaDisplay(p);
                            return (
                                <DropdownMenuRadioItem
                                    key={p.id}
                                    value={p.id}
                                    disabled={!testToken}
                                    className="flex items-center gap-2.5 py-2"
                                    title={p.description ? `${p.email} · ${p.description}` : p.email}
                                >
                                    <PersonaAvatar display={d} className="text-xs" />
                                    <span className="flex min-w-0 flex-col">
                                        <span className="truncate font-semibold">{d.name}</span>
                                        {d.title && <span className="truncate text-xs text-muted-foreground">{d.title}</span>}
                                        {p.groups && p.groups.length > 0 && (
                                            <span className="mt-0.5 flex flex-wrap gap-0.5">
                                                {p.groups.map((g) => (
                                                    <span key={g} className="rounded border px-1 text-[10px] text-muted-foreground">{g}</span>
                                                ))}
                                            </span>
                                        )}
                                    </span>
                                </DropdownMenuRadioItem>
                            );
                        })}
                        <DropdownMenuSeparator />
                        <DropdownMenuRadioItem value="none" disabled={!testToken} className="flex items-center gap-2.5">
                            <UserIcon className="h-3.5 w-3.5" />
                            {activeTestPersona ? t('common:userInfo.stopActing') : t('common:userInfo.noneRealIdentity')}
                        </DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                </ScrollArea>
                <DropdownMenuItem
                    className="flex items-center justify-between"
                    onSelect={(e) => e.preventDefault()}
                >
                    <div className="flex items-center">
                        <Presentation className="mr-2 h-4 w-4" />
                        <span>{t('common:userInfo.presenterSize')}</span>
                    </div>
                    <Switch
                        checked={presenterMode}
                        onCheckedChange={togglePresenterMode}
                        className="scale-75"
                        aria-label={t('common:userInfo.presenterSize')}
                    />
                </DropdownMenuItem>
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
                            {(canonicalActualRoleName || highestActualLevelName)}{t('common:userInfo.actual')}
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


