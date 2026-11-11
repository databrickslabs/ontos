import type { TFunction } from 'i18next';
import { lifecycleStatusLabel } from '@/lib/status-labels';

/** Code of the refusal to subscribe to a product that is not active. */
export const PRODUCT_NOT_SUBSCRIBABLE = 'product_not_subscribable';

/**
 * The error of a subscribe request, in the user's language.
 *
 * `detail` is the `detail` of the API's error body: either a text, or a coded
 * `{code, message, params}`. `product_not_subscribable` is translated with the
 * product's status shown in the user's language; any other detail is shown as
 * the API sent it, and `fallback` when it sent none.
 */
export function subscribeErrorText(detail: unknown, t: TFunction, fallback: string): string {
  return subscribeCodedErrorText(detail, t, fallback);
}

/**
 * The same for an `ApiResponse` of `useApi` (`error`, `errorCode`, `errorParams`),
 * which carries the parts of the coded `detail` separately.
 */
export function subscribeResponseErrorText(
  response: {
    error?: string | null;
    errorCode?: string | null;
    errorParams?: Record<string, unknown> | null;
  },
  t: TFunction,
  fallback: string,
): string {
  return subscribeCodedErrorText(
    { code: response.errorCode, message: response.error, params: response.errorParams },
    t,
    fallback,
  );
}

function subscribeCodedErrorText(detail: unknown, t: TFunction, fallback: string): string {
  if (typeof detail === 'string') return detail || fallback;
  if (!detail || typeof detail !== 'object') return fallback;
  const { code, message, params } = detail as {
    code?: string; message?: string; params?: Record<string, unknown>;
  };
  const defaultValue = typeof message === 'string' && message ? message : fallback;
  if (code === PRODUCT_NOT_SUBSCRIBABLE) {
    const status = String(params?.status ?? '');
    return t('errors:subscription.productNotSubscribable', {
      ...(params ?? {}),
      status: status ? lifecycleStatusLabel(status, 'data_product', t as never) : status,
      defaultValue,
    }) as string;
  }
  return defaultValue;
}
