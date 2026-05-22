import { NavLink, useLocation } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { getNavigationGroups, FeatureConfig } from '@/config/features';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';
import { Button } from '@/components/ui/button';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { Home as HomeIcon, Loader2 } from 'lucide-react';

interface NavigationProps {
  isCollapsed: boolean;
}

export function Navigation({ isCollapsed }: NavigationProps) {
  const { t } = useTranslation(['navigation', 'features']);
  const location = useLocation();
  const allowedMaturities = useFeatureVisibilityStore((state) => state.allowedMaturities);
  const { permissions, isLoading: permissionsLoading, hasPermission } = usePermissions();

  const rawNavigationGroups = getNavigationGroups(allowedMaturities);

  const ungroupedFeatureIds: string[] = [];

  const { navigationGroups, ungroupedItems } = React.useMemo(() => {
    if (permissionsLoading || Object.keys(permissions).length === 0) {
      return { navigationGroups: [], ungroupedItems: [] };
    }

    const extractedUngroupedItems: FeatureConfig[] = [];
    
    const filteredGroups = rawNavigationGroups
      .map(group => ({
        ...group,
        items: group.items.filter(item => {
          const hasAccess = hasPermission(item.permissionId || item.id, FeatureAccessLevel.READ_ONLY);
          
          if (ungroupedFeatureIds.includes(item.id) && hasAccess) {
            extractedUngroupedItems.push(item);
            return false;
          }
          
          return hasAccess;
        })
      }))
      .filter(group => group.items.length > 0);

    return { 
      navigationGroups: filteredGroups, 
      ungroupedItems: extractedUngroupedItems 
    };
  }, [rawNavigationGroups, permissions, permissionsLoading, hasPermission]);

  if (permissionsLoading) {
     return (
         <div className="flex justify-center items-center h-full p-4">
             <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
         </div>
     );
  }

  const homeLink: FeatureConfig = {
    id: 'home',
    name: t('navigation:home'),
    path: '/',
    description: 'Dashboard overview',
    icon: HomeIcon,
    group: 'Discover',
    maturity: 'ga',
  };

  const groupKeyMap: Record<string, string> = {
    'Discover': 'discover',
    'Build': 'build',
    'Govern': 'govern',
    'Deploy': 'deploy',
  };

  const translateGroupName = (groupName: string) => {
    const key = groupKeyMap[groupName] || groupName;
    return t(`navigation:groups.${key}`, { defaultValue: groupName });
  };

  const translateFeatureName = (featureId: string, defaultName: string) => {
    return t(`features:${featureId}.name`, { defaultValue: defaultName });
  };

  return (
    <ScrollArea className="h-full py-2">
      <TooltipProvider delayDuration={0}>
        <nav className={cn("flex flex-col px-1 gap-1")}>
          {/* Home Link */}
          {isCollapsed ? (
            <Tooltip key={homeLink.path}>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className={cn(
                    'flex items-center justify-center rounded-lg p-2 transition-colors',
                    location.pathname === homeLink.path
                      ? 'bg-muted text-primary'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  )}
                  aria-label={homeLink.name}
                  asChild
                >
                  <NavLink to={homeLink.path}>
                    <homeLink.icon className="h-5 w-5" />
                    <span className="sr-only">{homeLink.name}</span>
                  </NavLink>
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right" className="flex items-center gap-4">
                {homeLink.name}
              </TooltipContent>
            </Tooltip>
          ) : (
            <NavLink
              key={homeLink.path}
              to={homeLink.path}
              end
              className={({ isActive: navIsActive }) =>
                cn(
                  'flex items-center gap-2 rounded-lg px-2 py-2 text-sm font-medium transition-colors',
                  navIsActive
                    ? 'bg-muted text-primary'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                )
              }
            >
              <homeLink.icon className="h-5 w-5 shrink-0" />
              <span className="flex-1 min-w-0 truncate">{homeLink.name}</span>
            </NavLink>
          )}
          {/* Ungrouped Items (Domains, Teams, Projects) */}
          {ungroupedItems.map((item: FeatureConfig) => {
            const isActive = location.pathname === item.path || location.pathname.startsWith(`${item.path}/`);
            const translatedName = translateFeatureName(item.id, item.name);

            return isCollapsed ? (
              <Tooltip key={item.path}>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className={cn(
                      'flex items-center justify-center rounded-lg p-2 transition-colors',
                      isActive
                        ? 'bg-muted text-primary'
                        : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                    )}
                    aria-label={translatedName}
                    asChild
                  >
                    <NavLink to={item.path}>
                      <item.icon className="h-5 w-5" />
                      <span className="sr-only">{translatedName}</span>
                    </NavLink>
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">
                  {translatedName}
                  {item.maturity !== 'ga' && (
                    <sup className={cn(
                      "ml-1 text-[10px] font-bold px-1 py-0.5 rounded whitespace-nowrap",
                      item.maturity === 'beta' ? "bg-yellow-500/20 text-yellow-700 dark:bg-yellow-500/30 dark:text-yellow-400" : "",
                      item.maturity === 'alpha' ? "bg-purple-500/20 text-purple-700 dark:bg-purple-500/30 dark:text-purple-400" : ""
                    )}>
                      {item.maturity === 'beta' ? 'β' : 'α'}
                    </sup>
                  )}
                </TooltipContent>
              </Tooltip>
            ) : (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive: navIsActive }) =>
                  cn(
                    'flex items-center gap-2 rounded-lg px-2 py-2 text-sm font-medium transition-colors',
                    navIsActive
                      ? 'bg-muted text-primary'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  )
                }
              >
                <item.icon className="h-5 w-5 shrink-0" />
                <span className="flex-1 min-w-0 truncate">
                  {translatedName}
                  {item.maturity !== 'ga' && (
                    <sup className={cn(
                      "ml-1 text-[10px] font-bold px-1 py-0.5 rounded whitespace-nowrap",
                      item.maturity === 'beta' ? "bg-yellow-500/20 text-yellow-700 dark:bg-yellow-500/30 dark:text-yellow-400" : "",
                      item.maturity === 'alpha' ? "bg-purple-500/20 text-purple-700 dark:bg-purple-500/30 dark:text-purple-400" : ""
                    )}>
                      {item.maturity === 'beta' ? 'β' : 'α'}
                    </sup>
                  )}
                </span>
              </NavLink>
            );
          })}
          {/* Grouped Navigation */}
          {navigationGroups.map((group) => (
            <div key={group.name} className={cn("w-full", isCollapsed ? "" : "mb-2 last:mb-0")}>
              {!isCollapsed && group.items.length > 0 && (
                <h2 className="px-2 py-1 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  {translateGroupName(group.name)}
                </h2>
              )}
              {group.items.map((item: FeatureConfig) => {
                const isActive = location.pathname === item.path || location.pathname.startsWith(`${item.path}/`);
                const translatedName = translateFeatureName(item.id, item.name);

                return isCollapsed ? (
                  <Tooltip key={item.path}>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className={cn(
                          'flex items-center justify-center rounded-lg p-2 transition-colors',
                          isActive
                            ? 'bg-muted text-primary'
                            : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                        )}
                        aria-label={translatedName}
                        asChild
                      >
                        <NavLink to={item.path}>
                          <item.icon className="h-5 w-5" />
                          <span className="sr-only">{translatedName}</span>
                        </NavLink>
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="right">
                      {translatedName}
                      {item.maturity !== 'ga' && (
                        <sup className={cn(
                          "ml-1 text-[10px] font-bold px-1 py-0.5 rounded whitespace-nowrap",
                          item.maturity === 'beta' ? "bg-yellow-500/20 text-yellow-700 dark:bg-yellow-500/30 dark:text-yellow-400" : "",
                          item.maturity === 'alpha' ? "bg-purple-500/20 text-purple-700 dark:bg-purple-500/30 dark:text-purple-400" : ""
                        )}>
                          {item.maturity === 'beta' ? 'β' : 'α'}
                        </sup>
                      )}
                    </TooltipContent>
                  </Tooltip>
                ) : (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    className={({ isActive: navIsActive }) =>
                      cn(
                        'flex items-center gap-2 rounded-lg px-2 py-2 text-sm font-medium transition-colors',
                        navIsActive
                          ? 'bg-muted text-primary'
                          : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                      )
                    }
                  >
                    <item.icon className="h-5 w-5 shrink-0" />
                    <span className="flex-1 min-w-0 truncate">
                      {translatedName}
                      {item.maturity !== 'ga' && (
                        <sup className={cn(
                          "ml-1 text-[10px] font-bold px-1 py-0.5 rounded whitespace-nowrap",
                          item.maturity === 'beta' ? "bg-yellow-500/20 text-yellow-700 dark:bg-yellow-500/30 dark:text-yellow-400" : "",
                          item.maturity === 'alpha' ? "bg-purple-500/20 text-purple-700 dark:bg-purple-500/30 dark:text-purple-400" : ""
                        )}>
                          {item.maturity === 'beta' ? 'β' : 'α'}
                        </sup>
                      )}
                    </span>
                  </NavLink>
                );
              })}
            </div>
          ))}
        </nav>
      </TooltipProvider>
    </ScrollArea>
  );
}
