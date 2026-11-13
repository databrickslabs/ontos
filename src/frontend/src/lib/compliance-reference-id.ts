/**
 * Slug for a compliance template field key or reference id.
 *
 * The backend accepts ``^[a-z0-9][a-z0-9_-]*$``. Accented letters are
 * transliterated first (NFKD, then the combining marks are dropped), so
 * "Limitações conhecidas" becomes ``limitacoes-conhecidas`` instead of
 * ``limita-es-conhecidas``. Any other run of characters outside ``a-z0-9``
 * becomes one ``-``; leading and trailing dashes are trimmed.
 */
export function toReferenceSlug(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/\p{M}+/gu, '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
