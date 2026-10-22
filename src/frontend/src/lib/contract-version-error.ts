import type { TFunction } from 'i18next';
import type { ApiResponse } from '@/hooks/use-api';

/**
 * The message for a failed "Create New Version" (`POST /clone`): a version not in the
 * X.Y.Z form comes back with the code `invalid_version_format` and is shown in the
 * user's language; any other failure gets the generic message.
 */
export function contractVersionErrorText(
  response: Pick<ApiResponse<unknown>, 'errorCode' | 'errorParams'>,
  version: string,
  t: TFunction,
): string {
  if (response.errorCode === 'invalid_version_format') {
    return t('data-contracts:detailsView.errors.invalidVersionFormat', {
      version: String(response.errorParams?.version ?? version),
    });
  }
  return t('data-contracts:detailsView.errors.createVersionFailed', 'Failed to create new version.');
}

/**
 * The message for a failed "Clone for Editing" (`POST /clone-for-editing`): the personal
 * draft gets the version `<version>-draft`, so a contract whose version isn't X.Y.Z (an
 * imported `1.0`, say) is refused with `invalid_version_format`. The message names the
 * contract's own version; any other failure shows the API's message, or the generic one.
 */
export function contractDraftErrorText(
  response: Pick<ApiResponse<unknown>, 'error' | 'errorCode' | 'errorParams'>,
  contractVersion: string | undefined,
  t: TFunction,
): string {
  if (response.errorCode === 'invalid_version_format') {
    return t('data-contracts:detailsView.errors.draftVersionFormat', {
      version: contractVersion ?? '',
    });
  }
  return (
    response.error ||
    t('data-contracts:detailsView.errors.createDraftFailed', 'Failed to create personal draft')
  );
}
