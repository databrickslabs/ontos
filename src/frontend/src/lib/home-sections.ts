import { HomeSection } from '@/types/settings';

/**
 * The journey home (#1347) and the marketplace home (#1325) replace the home page, so a role
 * that has one of them can't also have another section, nor the other one: the role editor
 * keeps them and the other sections apart.
 */
const EXCLUSIVE_SECTIONS: readonly HomeSection[] = [HomeSection.JOURNEY, HomeSection.MARKETPLACE];

export function normalizeHomeSections(value: unknown): HomeSection[] {
  if (Array.isArray(value)) return value as HomeSection[];
  return typeof value === 'string' && value ? [value as HomeSection] : [];
}

/**
 * Whether `section` can't be added to `selected`: JOURNEY or MARKETPLACE with any other
 * section selected, or another section with one of them selected. A section already selected
 * stays toggleable, so a role saved with both before this rule can still be fixed.
 */
export function homeSectionBlocked(selected: HomeSection[], section: HomeSection): boolean {
  if (selected.includes(section)) return false;
  return EXCLUSIVE_SECTIONS.includes(section)
    ? selected.length > 0
    : selected.some((s) => EXCLUSIVE_SECTIONS.includes(s));
}
