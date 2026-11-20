/**
 * A contract create / update refused for its domain fields is explained in the user's
 * language, from the error's code and params.
 */
import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { contractDomainErrorText } from './contract-domain-error';

const blank = {
  detail: { code: 'invalid_domain_identifier', message: 'x', params: { field: 'primaryDomainId' } },
};
const primary = {
  detail: {
    code: 'primary_domain_not_in_domains', message: 'x', params: { primaryDomainId: 'd-9' },
  },
};

describe('contractDomainErrorText', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('explains a blank domain identifier with its field', () => {
    expect(contractDomainErrorText(blank, i18n.t)).toBe(
      "primaryDomainId is empty: send a domain id, or leave the field out to keep the contract's domains.",
    );
  });

  it('explains a primary domain outside the domains, from the raw text', () => {
    expect(contractDomainErrorText(JSON.stringify(primary), i18n.t)).toBe(
      "Domain d-9 is not one of the contract's domains, so it cannot be the primary domain.",
    );
  });

  it('says it in Portuguese', async () => {
    await i18n.changeLanguage('pt');

    expect(contractDomainErrorText(blank, i18n.t)).toMatch(/^primaryDomainId está vazio/);
  });

  it('is null for any other error', () => {
    expect(contractDomainErrorText({ detail: { code: 'other' } }, i18n.t)).toBeNull();
    expect(contractDomainErrorText('not json', i18n.t)).toBeNull();
  });
});
