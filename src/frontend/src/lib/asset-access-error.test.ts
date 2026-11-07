import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { assetAccessErrorText, responseErrorText } from './asset-access-error';

const coded = (code: string, params: Record<string, unknown> = {}) => ({
  detail: { code, message: `English text of ${code}`, params },
});

const response = (body: string, status = 403) => new Response(body, { status });

describe('assetAccessErrorText', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('gives each asset access error in the user language, from the body or its text', async () => {
    await i18n.changeLanguage('pt');

    expect(assetAccessErrorText(coded('asset_write_denied'))).toBe(
      'Alterar as notas, links, documentos e custos de um ativo exige ' +
        'acesso de leitura/escrita a Ativos.',
    );
    expect(assetAccessErrorText(JSON.stringify(coded('asset_read_denied')))).toMatch(
      /^Você não tem acesso a este ativo\./,
    );
    expect(assetAccessErrorText(coded('asset_not_found', { assetId: 'a-1' }))).toBe(
      "Ativo 'a-1' não encontrado.",
    );
  });

  it('gives nothing for any other error', () => {
    expect(assetAccessErrorText(coded('status_change_blocked'))).toBeNull();
    expect(assetAccessErrorText({ detail: 'Insufficient permissions' })).toBeNull();
    expect(assetAccessErrorText('Internal Server Error')).toBeNull();
    expect(assetAccessErrorText(null)).toBeNull();
  });
});

describe('responseErrorText', () => {
  it('translates an asset access error', async () => {
    const text = await responseErrorText(response(JSON.stringify(coded('asset_write_denied'))));
    expect(text).toBe(
      'Changing the notes, links, documents and costs of an asset needs ' +
        'read/write access to Assets.',
    );
  });

  it('keeps any other error as the API sent it, or the fallback when given', async () => {
    const body = JSON.stringify({ detail: "Insufficient permissions for feature 'data-domains'." });

    expect(await responseErrorText(response(body))).toBe(body);
    expect(await responseErrorText(response(body), 'Failed to delete')).toBe('Failed to delete');
  });
});
