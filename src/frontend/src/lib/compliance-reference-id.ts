/**
 * Slug for a compliance template field key or reference id.
 *
 * The backend accepts ``^[a-z0-9][a-z0-9_-]*$``. Accented letters are
 * transliterated first (a few letters by a table, e.g. ß -> ss, ł -> l; then
 * NFKD, then the combining marks are dropped), so
 * "Limitações conhecidas" becomes ``limitacoes-conhecidas`` instead of
 * ``limita-es-conhecidas``. Any other run of characters outside ``a-z0-9``
 * becomes one ``-``; leading and trailing dashes are trimmed.
 */
// Letters NFKD doesn't decompose into a base letter plus marks.
const LETTERS: Record<string, string> = {
  ß: 'ss', ẞ: 'ss', ł: 'l', Ł: 'l', ø: 'o', Ø: 'o', æ: 'ae', Æ: 'ae', đ: 'd', Đ: 'd',
  œ: 'oe', Œ: 'oe', þ: 'th', Þ: 'th',
};
const LETTER_RE = new RegExp(`[${Object.keys(LETTERS).join('')}]`, 'g');

export function toReferenceSlug(value: string): string {
  return value
    .replace(LETTER_RE, (c) => LETTERS[c])
    .normalize('NFKD')
    .replace(/\p{M}+/gu, '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
