import { NavLink, Outlet } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import {
  Layers,
  Network,
  Brain,
  Globe2,
  TreePine,
  Wand2,
  Sparkles,
  type LucideIcon,
} from 'lucide-react';

interface ConceptsNavItem {
  path: string;
  labelKey: string;
  defaultLabel: string;
  icon: LucideIcon;
}

const conceptsNavItems: ConceptsNavItem[] = [
  { path: '/concepts/collections', labelKey: 'concepts:nav.collections', defaultLabel: 'Collections', icon: Layers },
  { path: '/concepts/browser', labelKey: 'concepts:nav.browser', defaultLabel: 'Concepts', icon: Network },
  { path: '/concepts/search', labelKey: 'concepts:nav.search', defaultLabel: 'Search', icon: Brain },
  { path: '/concepts/graph', labelKey: 'concepts:nav.graph', defaultLabel: 'Graph', icon: Globe2 },
  { path: '/concepts/hierarchy', labelKey: 'concepts:nav.hierarchy', defaultLabel: 'Hierarchy', icon: TreePine },
  { path: '/concepts/generator', labelKey: 'concepts:nav.generator', defaultLabel: 'Generator', icon: Wand2 },
  { path: '/concepts/mapping', labelKey: 'concepts:nav.mapping', defaultLabel: 'Mapping', icon: Sparkles },
];

export default function ConceptsLayout() {
  const { t } = useTranslation(['concepts']);

  return (
    <div className="flex gap-8 min-h-[calc(100vh-12rem)]">
      <nav className="w-48 shrink-0">
        <h1 className="text-2xl font-semibold mb-6">
          {t('concepts:title', 'Concepts')}
        </h1>

        <ul className="space-y-0.5">
          {conceptsNavItems.map((item) => (
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
      </nav>

      <div className="flex-1 min-w-0">
        <Outlet />
      </div>
    </div>
  );
}
