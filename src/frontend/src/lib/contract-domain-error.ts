import type { TFunction } from 'i18next';

const parsed = (body: unknown): any => {
  if (typeof body !== 'string') return body;
  try {
    return JSON.parse(body);
  } catch {
    return null;
  }
};

/** Codes of the domain checks of a contract create / update (`data-contracts:domainErrors`). */
const DOMAIN_ERROR_KEYS: Record<string, string> = {
  invalid_domain_identifier: 'data-contracts:domainErrors.invalidDomainIdentifier',
  primary_domain_not_in_domains: 'data-contracts:domainErrors.primaryDomainNotInDomains',
};

/**
 * The message for a contract create / update refused for its domain fields
 * (`detail = {code, message, params}`): a blank domain identifier
 * (`invalid_domain_identifier`, param `field`) or a primary domain that isn't one of the
 * contract's domains (`primary_domain_not_in_domains`, param `primaryDomainId`). `null` for
 * any other error. Takes the parsed JSON body or its raw text.
 */
export function contractDomainErrorText(body: unknown, t: TFunction): string | null {
  const error = parsed(body);
  const detail = error && typeof error === 'object' ? error.detail : null;
  if (!detail || typeof detail !== 'object' || !DOMAIN_ERROR_KEYS[detail.code]) return null;
  const params = detail.params && typeof detail.params === 'object' ? detail.params : {};
  return String(
    t(DOMAIN_ERROR_KEYS[detail.code], { ...params, defaultValue: detail.message ?? '' }),
  );
}
