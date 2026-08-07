import { NavLink, Outlet, useLocation } from 'react-router-dom';
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
  Upload,
  PenLine,
  Compass,
  Boxes,
  type LucideIcon,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Concept Builder v2 navigation — 3 primary sections (Define / Explore / Enrich).
// Low-risk restructure: the 7 underlying view components and their routes are
// kept AS-IS. This shell only regroups them under 3 sections and, within
// Explore, exposes browse/search/graph/hierarchy as view toggles.
// See wireframes: .claude/notes/ontos_v2_prototypes/{define,explore,enrich}.html
// ---------------------------------------------------------------------------

type SectionId = 'define' | 'explore' | 'enrich';

interface SubNavItem {
  path: string;
  labelKey: string;
  defaultLabel: string;
  icon: LucideIcon;
}

interface Section {
  id: SectionId;
  labelKey: string;
  defaultLabel: string;
  icon: LucideIcon;
  // Canonical landing route for the section (used when switching sections).
  basePath: string;
  // The routes that belong to this section (for active-section detection).
  memberPaths: string[];
  // Sub-navigation shown inside the section.
  subItems: SubNavItem[];
}

const SECTIONS: Section[] = [
  {
    id: 'define',
    labelKey: 'concepts:sections.define',
    defaultLabel: 'Define',
    icon: PenLine,
    basePath: '/concepts/collections',
    memberPaths: ['/concepts/collections', '/concepts/generator', '/concepts/import', '/schema-importer'],
    subItems: [
      { path: '/concepts/collections', labelKey: 'concepts:nav.collections', defaultLabel: 'Collections', icon: Layers },
      { path: '/concepts/generator', labelKey: 'concepts:nav.generator', defaultLabel: 'Generator', icon: Wand2 },
      // Import reuses the existing SchemaImporterView, now also mounted inside the
      // /concepts outlet at /concepts/import so the Concepts shell stays visible.
      // The legacy top-level /schema-importer route still works.
      { path: '/concepts/import', labelKey: 'concepts:nav.import', defaultLabel: 'Import', icon: Upload },
    ],
  },
  {
    id: 'explore',
    labelKey: 'concepts:sections.explore',
    defaultLabel: 'Explore',
    icon: Compass,
    basePath: '/concepts/browser',
    memberPaths: ['/concepts/browser', '/concepts/search', '/concepts/graph', '/concepts/hierarchy'],
    subItems: [
      { path: '/concepts/browser', labelKey: 'concepts:nav.browser', defaultLabel: 'Concepts', icon: Network },
      { path: '/concepts/search', labelKey: 'concepts:nav.search', defaultLabel: 'Search', icon: Brain },
      { path: '/concepts/hierarchy', labelKey: 'concepts:nav.hierarchy', defaultLabel: 'Hierarchy', icon: TreePine },
      { path: '/concepts/graph', labelKey: 'concepts:nav.graph', defaultLabel: 'Graph', icon: Globe2 },
    ],
  },
  {
    id: 'enrich',
    labelKey: 'concepts:sections.enrich',
    defaultLabel: 'Enrich',
    icon: Sparkles,
    basePath: '/concepts/mapping',
    memberPaths: ['/concepts/mapping'],
    subItems: [
      { path: '/concepts/mapping', labelKey: 'concepts:nav.mapping', defaultLabel: 'Mapping', icon: Boxes },
      // TODO(cb-v2): the Enrich wireframe (enrich.html) also has a delivery lane
      // (tags / descriptions / glossary). No standalone view component exists for
      // it yet — delivery config currently lives under Settings > Delivery. Wire a
      // dedicated Enrich delivery surface here once that component lands.
    ],
  },
];

function isPathActive(pathname: string, target: string): boolean {
  return pathname === target || pathname.startsWith(target + '/');
}

function resolveActiveSection(pathname: string): Section {
  const match = SECTIONS.find((section) =>
    section.memberPaths.some((p) => isPathActive(pathname, p))
  );
  // Default to Explore (the browser is the /concepts index target).
  return match ?? SECTIONS[1];
}

export default function ConceptsLayout() {
  const { t } = useTranslation(['concepts']);
  const { pathname } = useLocation();
  const activeSection = resolveActiveSection(pathname);
  const useToggles = activeSection.id === 'explore';

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold">{t('concepts:title', 'Concepts')}</h1>

        {/* Primary section switch — horizontal tab strip (Define / Explore / Enrich) */}
        <div
          role="tablist"
          aria-label={t('concepts:sections.label', 'Concept sections')}
          className="inline-flex items-center gap-1 rounded-lg bg-muted p-1"
        >
          {SECTIONS.map((section) => {
            const active = section.id === activeSection.id;
            return (
              <NavLink
                key={section.id}
                to={section.basePath}
                role="tab"
                aria-selected={active}
                className={cn(
                  'inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                  active
                    ? 'bg-background text-foreground shadow'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <section.icon className="h-4 w-4 shrink-0" />
                {t(section.labelKey, section.defaultLabel)}
              </NavLink>
            );
          })}
        </div>

        {/* Sub-navigation for the active section.
            Explore renders view toggles (segmented control); Define/Enrich render
            entry-point links. */}
        <div
          role={useToggles ? 'tablist' : undefined}
          aria-label={
            useToggles ? t('concepts:explore.viewLabel', 'Explore views') : undefined
          }
          className={cn(
            useToggles
              ? 'inline-flex items-center gap-1 rounded-lg border bg-card p-1'
              : 'flex flex-wrap items-center gap-1'
          )}
        >
          {activeSection.subItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              role={useToggles ? 'tab' : undefined}
              className={({ isActive }) =>
                cn(
                  'inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors',
                  isActive
                    ? 'bg-accent text-accent-foreground font-medium'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
                )
              }
              aria-selected={
                useToggles ? isPathActive(pathname, item.path) : undefined
              }
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {t(item.labelKey, item.defaultLabel)}
            </NavLink>
          ))}
        </div>
      </div>

      <div className="min-w-0">
        <Outlet />
      </div>
    </div>
  );
}
