import { NavLink, Outlet } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
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
      { path: '/settings/data-domains', labelKey: 'settings:tabs.dataDomains', defaultLabel: 'Domains', icon: BoxSelect },
      { path: '/settings/business-roles', labelKey: 'settings:tabs.businessRoles', defaultLabel: 'Business Roles', icon: Briefcase },
      { path: '/settings/delivery-methods', labelKey: 'settings:tabs.deliveryMethods', defaultLabel: 'Delivery Methods', icon: Truck },
      { path: '/settings/asset-types', labelKey: 'settings:tabs.assetTypes', defaultLabel: 'Asset Types', icon: Shapes },
      { path: '/settings/teams', labelKey: 'settings:tabs.teams', defaultLabel: 'Teams', icon: UserCheck },
      { path: '/settings/projects', labelKey: 'settings:tabs.projects', defaultLabel: 'Projects', icon: FolderOpen },
      { path: '/settings/certification-levels', labelKey: 'settings:tabs.certificationLevels', defaultLabel: 'Certification Levels', icon: ShieldCheck },
    ],
  },
  {
    titleKey: 'settings:nav.groups.configuration',
    defaultTitle: 'Configuration',
    items: [
      { path: '/settings/general', labelKey: 'settings:tabs.general', defaultLabel: 'General', icon: Settings },
      { path: '/settings/ui', labelKey: 'settings:tabs.ui', defaultLabel: 'UI', icon: Palette },
      { path: '/settings/tags', labelKey: 'settings:tabs.tags', defaultLabel: 'Tags', icon: Tags },
      { path: '/settings/connectors', labelKey: 'settings:tabs.connectors', defaultLabel: 'Connectors', icon: Plug2 },
    ],
  },
  {
    titleKey: 'settings:nav.groups.integrations',
    defaultTitle: 'Integrations',
    items: [
      { path: '/settings/git', labelKey: 'settings:tabs.git', defaultLabel: 'Git', icon: GitBranch },
      { path: '/settings/mcp', labelKey: 'settings:tabs.mcp', defaultLabel: 'MCP', icon: Bot },
      { path: '/settings/directory', labelKey: 'settings:tabs.directory', defaultLabel: 'Directory', icon: Contact },
      { path: '/settings/semantic-models', labelKey: 'settings:tabs.rdfSources', defaultLabel: 'RDF Sources', icon: Network },
      { path: '/settings/search', labelKey: 'settings:tabs.search', defaultLabel: 'Search', icon: Search },
    ],
  },
  {
    titleKey: 'settings:nav.groups.operations',
    defaultTitle: 'Operations',
    items: [
      { path: '/settings/jobs', labelKey: 'settings:tabs.jobs', defaultLabel: 'Jobs', icon: Clock },
      { path: '/settings/delivery', labelKey: 'settings:tabs.delivery', defaultLabel: 'Delivery', icon: Briefcase },
      { path: '/settings/workflows', labelKey: 'settings:tabs.workflows', defaultLabel: 'Workflows', icon: GitBranch },
    ],
  },
  {
    titleKey: 'settings:nav.groups.accessControl',
    defaultTitle: 'Access Control',
    items: [
      { path: '/settings/roles', labelKey: 'settings:tabs.roles', defaultLabel: 'App Roles', icon: UserCog },
      { path: '/settings/audit', labelKey: 'settings:tabs.audit', defaultLabel: 'Audit Trail', icon: ScrollText },
    ],
  },
];

export default function SettingsLayout() {
  const { t } = useTranslation(['settings']);

  return (
    <div className="flex gap-8 min-h-[calc(100vh-12rem)]">
      {/* Sidebar navigation */}
      <nav className="w-52 shrink-0">
        <h1 className="text-2xl font-semibold mb-6">
          {t('settings:title', 'Settings')}
        </h1>

        <div className="space-y-6">
          {settingsNavGroups.map((group) => (
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
