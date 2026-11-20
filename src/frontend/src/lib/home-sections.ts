import { HomeSection } from '@/types/settings';

/**
 * The journey home (#1347) replaces the home page, so a role that has it can't also have
 * another section: the role editor keeps JOURNEY and the other sections apart.
 */
export function normalizeHomeSections(value: unknown): HomeSection[] {
  if (Array.isArray(value)) return value as HomeSection[];
  return typeof value === 'string' && value ? [value as HomeSection] : [];
}

/**
 * Whether `section` can't be added to `selected`: JOURNEY with any other section selected,
 * or another section with JOURNEY selected. A section already selected stays toggleable, so
 * a role saved with both before this rule can still be fixed.
 */
export function homeSectionBlocked(selected: HomeSection[], section: HomeSection): boolean {
  if (selected.includes(section)) return false;
  return section === HomeSection.JOURNEY
    ? selected.length > 0
    : selected.includes(HomeSection.JOURNEY);
}
