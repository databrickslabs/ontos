/**
 * The estate list with the edit dialog of one estate open: the estate page's
 * "Edit Estate" button goes there (the dialog lives on the list).
 */
export const ESTATE_EDIT_PARAM = 'edit';

export function buildEstateEditPath(estateId: string): string {
  return `/estate-manager?${ESTATE_EDIT_PARAM}=${encodeURIComponent(estateId)}`;
}
