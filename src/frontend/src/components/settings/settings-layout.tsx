import { NavLink, Outlet, Navigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import usePermissionsStore, { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { Loader2 } from 'lucide-react';
import {
  Settings,
  Palette,
  Tags,
  Plug2,
  GitBranch,
  Bot,
  Contact,
  Network,
  Search,
  Briefcase,
  Clock,
  UserCog,
  ScrollText,
  UserCheck,
  FolderOpen,
  Shapes,
  BoxSelect,
  Truck,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react';

interface SettingsNavItem {
  path: string;
  labelKey: string;
  defaultLabel: string;
  icon: LucideIcon;
  permissionId: string;
}

interface SettingsNavGroup {
  titleKey: string;
  defaultTitle: string;
  items: SettingsNavItem[];
}

const settingsNavGroups: SettingsNavGroup[] = [
  {
    titleKey: 'settings:nav.groups.referenceData',
    defaultTitle: 'Reference Data',
    items: [
      { path: '/settings/data-domains', labelKey: 'settings:tabs.dataDomains', defaultLabel: 'Domains', icon: BoxSelect, permissionId: 'settings-data-domains' },
      { path: '/settings/business-roles', labelKey: 'settings:tabs.businessRoles', defaultLabel: 'Business Roles', icon: Briefcase, permissionId: 'settings-business-roles' },
      { path: '/settings/delivery-methods', labelKey: 'settings:tabs.deliveryMethods', defaultLabel: 'Delivery Methods', icon: Truck, permissionId: 'settings-delivery-methods' },
      { path: '/settings/asset-types', labelKey: 'settings:tabs.assetTypes', defaultLabel: 'Asset Types', icon: Shapes, permissionId: 'settings-asset-types' },
      { path: '/settings/teams', labelKey: 'settings:tabs.teams', defaultLabel: 'Teams', icon: UserCheck, permissionId: 'settings-teams' },
      { path: '/settings/projects', labelKey: 'settings:tabs.projects', defaultLabel: 'Projects', icon: FolderOpen, permissionId: 'settings-projects' },
      { path: '/settings/certification-levels', labelKey: 'settings:tabs.certificationLevels', defaultLabel: 'Certification Levels', icon: ShieldCheck, permissionId: 'settings-certification-levels' },
    ],
  },
  {
    titleKey: 'settings:nav.groups.configuration',
    defaultTitle: 'Configuration',
    items: [
      { path: '/settings/general', labelKey: 'settings:tabs.general', defaultLabel: 'General', icon: Settings, permissionId: 'settings-general' },
      { path: '/settings/ui', labelKey: 'settings:tabs.ui', defaultLabel: 'UI', icon: Palette, permissionId: 'settings-ui' },
      { path: '/settings/tags', labelKey: 'settings:tabs.tags', defaultLabel: 'Tags', icon: Tags, permissionId: 'settings-tags' },
      { path: '/settings/connectors', labelKey: 'settings:tabs.connectors', defaultLabel: 'Connectors', icon: Plug2, permissionId: 'settings-connectors' },
    ],
  },
  {
    titleKey: 'settings:nav.groups.integrations',
    defaultTitle: 'Integrations',
    items: [
      { path: '/settings/git', labelKey: 'settings:tabs.git', defaultLabel: 'Git', icon: GitBranch, permissionId: 'settings-git' },
      { path: '/settings/mcp', labelKey: 'settings:tabs.mcp', defaultLabel: 'MCP', icon: Bot, permissionId: 'settings-mcp' },
      { path: '/settings/directory', labelKey: 'settings:tabs.directory', defaultLabel: 'Directory', icon: Contact, permissionId: 'settings-directory' },
      { path: '/settings/semantic-models', labelKey: 'settings:tabs.rdfSources', defaultLabel: 'RDF Sources', icon: Network, permissionId: 'settings-semantic-models' },
      { path: '/settings/search', labelKey: 'settings:tabs.search', defaultLabel: 'Search', icon: Search, permissionId: 'settings-search' },
    ],
  },
  {
    titleKey: 'settings:nav.groups.operations',
    defaultTitle: 'Operations',
    items: [
      { path: '/settings/jobs', labelKey: 'settings:tabs.jobs', defaultLabel: 'Jobs', icon: Clock, permissionId: 'settings-jobs' },
      { path: '/settings/delivery', labelKey: 'settings:tabs.delivery', defaultLabel: 'Delivery', icon: Briefcase, permissionId: 'settings-delivery' },
      { path: '/settings/workflows', labelKey: 'settings:tabs.workflows', defaultLabel: 'Workflows', icon: GitBranch, permissionId: 'settings-workflows' },
    ],
  },
  {
    titleKey: 'settings:nav.groups.accessControl',
    defaultTitle: 'Access Control',
    items: [
      { path: '/settings/roles', labelKey: 'settings:tabs.roles', defaultLabel: 'App Roles', icon: UserCog, permissionId: 'settings-roles' },
      { path: '/settings/audit', labelKey: 'settings:tabs.audit', defaultLabel: 'Audit Trail', icon: ScrollText, permissionId: 'settings-audit' },
    ],
  },
];

export default function SettingsLayout() {
  const { t } = useTranslation(['settings']);
  const { isLoading: permissionsLoading, hasPermission } = usePermissions();
  // Read internal init flags directly (the hook only exposes the public API).
  // We need to distinguish "store not yet initialized" from "initialized and
  // user genuinely lacks access" — otherwise we'd redirect on first mount
  // before the permissions fetch has even started.
  const initAttempted = usePermissionsStore((s) => s._initAttempted);
  const isInitializing = usePermissionsStore((s) => s._isInitializing);

  if (permissionsLoading || isInitializing || !initAttempted) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  // Layout gate: users below Read-only on `settings` cannot enter the
  // Settings area at all. Redirect home rather than render a sidebar shell
  // they cannot use.
  if (!hasPermission('settings', FeatureAccessLevel.READ_ONLY)) {
    return <Navigate to="/" replace />;
  }

  // Filter sidebar items by per-sub-page permission; hide empty groups
  const visibleGroups = settingsNavGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) =>
        hasPermission(item.permissionId, FeatureAccessLevel.READ_ONLY)
      ),
    }))
    .filter((group) => group.items.length > 0);

  return (
    <div className="flex gap-8 min-h-[calc(100vh-12rem)]">
      {/* Sidebar navigation */}
      <nav className="w-52 shrink-0">
        <h1 className="text-2xl font-semibold mb-6">
          {t('settings:title', 'Settings')}
        </h1>

        <div className="space-y-6">
          {visibleGroups.map((group) => (
            <div key={group.defaultTitle}>
              <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2 px-3">
                {t(group.titleKey, group.defaultTitle)}
              </h3>
              <ul className="space-y-0.5">
                {group.items.map((item) => (
                  <li key={item.path}>
                    <NavLink
                      to={item.path}
                      className={({ isActive }) =>
                        cn(
                          'flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-colors',
                          isActive
                            ? 'bg-accent text-accent-foreground font-medium'
                            : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
                        )
                      }
                    >
                      <item.icon className="h-4 w-4 shrink-0" />
                      {t(item.labelKey, item.defaultLabel)}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </nav>

      {/* Content area */}
      <div className="flex-1 min-w-0">
        <Outlet />
      </div>
    </div>
  );
}
