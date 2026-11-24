/**
 * The certified guard's refusal (`certified_deprecation_requires_approval`)
 * is translated, and marks a change that can be sent as a request instead.
 */
import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import {
  CERTIFIED_APPROVAL_REFUSED_CODE,
  CERTIFIED_DEPRECATION_CODE,
  needsStatusChangeRequest,
  statusChangeErrorText,
} from './status-change-error';

const REFUSED = {
  error: "The data product 'Orders' is certified: deprecating it needs an approved status "
    + 'change request. Request the status change instead.',
  errorCode: CERTIFIED_DEPRECATION_CODE,
  errorParams: { entityType: 'data_product', entityId: 'p-1', entityName: 'Orders' },
};

describe('certified deprecation refusal', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('is shown in the UI language with the entity name', async () => {
    await i18n.changeLanguage('pt');

    expect(statusChangeErrorText(REFUSED, i18n.t, 'data-products')).toBe(
      'Orders é certificado, então só pode ser descontinuado por uma solicitação de '
      + 'mudança de status aprovada. Solicite a mudança de status.',
    );
  });

  it('is translated in English too', () => {
    expect(statusChangeErrorText(REFUSED, i18n.t, 'data-contracts')).toBe(
      'Orders is certified, so it can only be deprecated through an approved status change '
      + 'request. Request the status change instead.',
    );
  });

  it.each([
    ['not_admin',
      'Orders is certified: only an admin of this feature can approve its deprecation.'],
    ['self_approval',
      'Orders is certified: you made this request, so someone else has to approve it.'],
  ])('explains an approval that does not count (%s)', (reason, text) => {
    const response = {
      error: "The approval of this request doesn't count",
      errorCode: CERTIFIED_APPROVAL_REFUSED_CODE,
      errorParams: { entityName: 'Orders', reason },
    };
    expect(statusChangeErrorText(response, i18n.t, 'data-contracts')).toBe(text);
    expect(needsStatusChangeRequest(response)).toBe(false);
  });

  it('can be sent as a request; other refusals cannot', () => {
    expect(needsStatusChangeRequest(REFUSED)).toBe(true);
    expect(needsStatusChangeRequest({ errorCode: 'status_change_blocked' })).toBe(false);
    expect(needsStatusChangeRequest({ errorCode: null })).toBe(false);
  });
});
