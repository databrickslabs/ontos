import { NavLink, Outlet, useLocation, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import {
  Sparkles,
  PenLine,
  Compass,
  Terminal,
  type LucideIcon,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ConceptModeSwitch } from '@/components/concepts/mode-switch';

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
    basePath: '/concepts/define',
    memberPaths: ['/concepts/define', '/concepts/collections', '/concepts/generator', '/concepts/import', '/schema-importer'],
    subItems: [],
  },
  {
    id: 'explore',
    labelKey: 'concepts:sections.explore',
    defaultLabel: 'Explore',
    icon: Compass,
    basePath: '/concepts/browser',
    // /concepts/graph still resolves (it redirects into the unified browser),
    // so keep it a member for active-section detection. Search + hierarchy are
    // demoted out of the Explore toggle (see below) but remain routable.
    memberPaths: ['/concepts/browser', '/concepts/search', '/concepts/graph', '/concepts/hierarchy'],
    // Explore is now ONE unified browse surface (List | Tree | Graph live as an
    // in-page view-mode switch inside the browser view, not as separate nav
    // toggles). No sub-nav toggles here; power-user links (Search / SPARQL,
    // estate hierarchy) are rendered separately, out of the toggle strip.
    subItems: [],
  },
  {
    id: 'enrich',
    labelKey: 'concepts:sections.enrich',
    defaultLabel: 'Enrich',
    icon: Sparkles,
    basePath: '/concepts/enrich',
    memberPaths: ['/concepts/enrich', '/concepts/mapping'],
    subItems: [],
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
  // The Explore section no longer uses a toggle strip — its browse modes live
  // inside the view. Define/Enrich keep their entry-point link rows.
  const useToggles = false;

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        {/* No standalone page title here — the section tab strip below states
            the location, and each view owns its own header/actions row. This
            keeps a single header and avoids the duplicate "Concepts" title. */}

        {/* Primary section switch — horizontal tab strip (Define / Explore /
            Enrich), with the Simple/Advanced switch aligned on the same row and
            a bottom boundary separating the nav from the view below. */}
        <div className="flex items-center justify-between gap-4 border-b pb-3">
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

          <div className="flex items-center gap-2">
            {/* Power-user SPARQL/Query link — Advanced view only (it exposes the
                raw ontology query layer, which the Simple persona should not
                see). adv-only = hidden unless html[data-mode="advanced"]. */}
            <Button
              variant="ghost"
              size="sm"
              asChild
              className="adv-only"
              title={t('concepts:links.sparqlTitle', 'Query concepts with SPARQL')}
            >
              <Link to="/concepts/search" className="inline-flex items-center gap-2">
                <Terminal className="h-4 w-4" />
                <span className="text-xs">{t('concepts:links.sparql', 'SPARQL')}</span>
              </Link>
            </Button>

            {/* Simple/Advanced switch, aligned with the section tabs. Shared
                across all Concepts views; per-view copies are removed. */}
            <ConceptModeSwitch tipLeft />
          </div>
        </div>

        {/* Sub-navigation for the active section.
            Define/Enrich render entry-point links. Explore renders no
            secondary link row at all — List/Tree/Graph live as a view-mode
            switch inside the browser view, and estate/search surfaces are
            reached from global nav, not from Explore. */}
        {(() => {
          const links = activeSection.subItems;
          if (links.length === 0) return null;
          return (
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
              {links.map((item) => (
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
          );
        })()}
      </div>

      <div className="min-w-0">
        <Outlet />
      </div>
    </div>
  );
}
