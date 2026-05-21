/**
 * Helper for normalising the AppRole ``assigned_groups`` field.
 *
 * Historically this field was edited as a comma-separated text input
 * and persisted as ``string[]``. With the Directory PrincipalPicker
 * the field is always ``string[]``, but old role records loaded from
 * the API (or other code paths) may still surface a raw comma string.
 * This helper makes the picker tolerant of both shapes without
 * leaking the conditional throughout the form.
 */

export function normaliseAssignedGroups(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return (raw as unknown[]).filter((x): x is string => typeof x === 'string' && x.length > 0);
  }
  if (typeof raw === 'string' && raw.length > 0) {
    return raw
      .split(',')
      .map((g) => g.trim())
      .filter(Boolean);
  }
  return [];
}
