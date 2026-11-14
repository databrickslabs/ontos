import type { TFunction } from 'i18next';
import type { ApiResponse } from '@/hooks/use-api';

/** Code of a create or update refused because the asset type is retired (#970). */
export const ASSET_TYPE_RETIRED_CODE = 'asset_type_retired';

/**
 * The error of an asset create or update in the user's language. A refused
 * retired type (`asset_type_retired`) is named in the translation; any other
 * error is shown as the API sent it, and `fallback` when it sent none.
 */
export function assetTypeErrorText(
  response: Pick<ApiResponse<unknown>, 'error' | 'errorCode' | 'errorParams'>,
  t: TFunction,
  fallback = '',
): string {
  const defaultValue = response.error || fallback;
  if (response.errorCode === ASSET_TYPE_RETIRED_CODE) {
    return t('assets:errors.assetTypeRetired', {
      name: String(response.errorParams?.name ?? ''),
      defaultValue,
    });
  }
  return defaultValue;
}
