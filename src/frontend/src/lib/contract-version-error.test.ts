/**
 * "Create New Version" on a contract: a version not in the X.Y.Z form is
 * explained in the user's language, from the error's code and version.
 */
import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { contractDraftErrorText, contractVersionErrorText } from './contract-version-error';

const REFUSED = {
  errorCode: 'invalid_version_format',
  errorParams: { version: '2.1' },
};

describe('contractVersionErrorText', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('explains a version not in the X.Y.Z form', () => {
    expect(contractVersionErrorText(REFUSED, '2.1', i18n.t)).toBe(
      '"2.1" is not a valid version: a new version uses the X.Y.Z form, for example 2.0.0.',
    );
  });

  it('says it in Portuguese', async () => {
    await i18n.changeLanguage('pt');

    expect(contractVersionErrorText(REFUSED, '2.1', i18n.t)).toBe(
      '"2.1" não é uma versão válida: uma nova versão usa o formato X.Y.Z, por exemplo 2.0.0.',
    );
  });

  it('gives the generic message for any other failure', () => {
    expect(contractVersionErrorText({ errorCode: null, errorParams: null }, '2.0.0', i18n.t)).toBe(
      'Failed to create new version.',
    );
  });
});

describe('contractDraftErrorText', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  const REFUSED_DRAFT = {
    error: 'new_version must be in format X.Y.Z or X.Y.Z-draft',
    errorCode: 'invalid_version_format',
    errorParams: { version: '1.0-draft' },
  };

  it("names the contract's own version, in Portuguese", async () => {
    await i18n.changeLanguage('pt');

    expect(contractDraftErrorText(REFUSED_DRAFT, '1.0', i18n.t)).toBe(
      'A versão "1.0" deste contrato não está no formato X.Y.Z, então não é possível criar um rascunho pessoal a partir dela. Crie uma nova versão (por exemplo 2.0.0).',
    );
  });

  it("shows the API's message for another failure, never an object", () => {
    expect(contractDraftErrorText({ error: 'Contract not found', errorCode: null }, '1.0', i18n.t)).toBe(
      'Contract not found',
    );
    expect(contractDraftErrorText({ error: null, errorCode: null }, '1.0', i18n.t)).toBe(
      'Failed to create personal draft',
    );
  });
});
