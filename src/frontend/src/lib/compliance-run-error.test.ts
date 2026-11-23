import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import { complianceRunErrorText } from './compliance-run-error';

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('complianceRunErrorText', () => {
  it('translates a run error that has a code', async () => {
    await i18n.changeLanguage('pt');
    const text = complianceRunErrorText(i18n.t, {
      error_code: 'rule_parse_failed',
      error_params: { detail: 'Parser error at line 1' },
    });

    expect(text).toBe('Não foi possível interpretar a regra: Parser error at line 1');
  });

  it('translates the entity-load error with its entity type', async () => {
    await i18n.changeLanguage('pt');
    const text = complianceRunErrorText(i18n.t, {
      error_code: 'entities_load_failed',
      error_params: { entityType: 'data_contract' },
    });

    expect(text).toBe(
      'Não foi possível carregar as entidades data_contract, por isso a regra não pôde ser avaliada.',
    );
  });

  it('translates the tag-load error with its entity type', async () => {
    await i18n.changeLanguage('pt');
    const text = complianceRunErrorText(i18n.t, {
      error_code: 'tags_load_failed',
      error_params: { entityType: 'data_product' },
    });

    expect(text).toBe(
      'Não foi possível carregar as tags das entidades data_product, por isso a regra não pôde ser avaliada.',
    );
  });

  it('translates a run refused for tag actions on an LLM_CHECK rule', async () => {
    await i18n.changeLanguage('pt');
    const text = complianceRunErrorText(i18n.t, {
      error_code: 'llm_check_tag_action',
      error_params: { actions: 'ASSIGN_TAG' },
    });

    expect(text).toBe(
      'Uma regra com LLM_CHECK não pode usar ASSIGN_TAG nem REMOVE_TAG (ASSIGN_TAG): o '
      + 'veredito do modelo mudaria tags. Use NOTIFY, ou uma regra separada sem LLM_CHECK '
      + 'para as ações de tag.',
    );
  });

  it('does not show the stored exception text for an error that has a code', async () => {
    await i18n.changeLanguage('en');
    const text = complianceRunErrorText(i18n.t, {
      error_code: 'workspace_client_unavailable',
      error_params: null,
    });

    expect(text).toBe(
      "The Databricks workspace isn't available, and this rule checks Unity Catalog objects, so it could not run.",
    );
    expect(text).not.toContain('internal.example');
  });

  it('shows the generic text, not a stored message, when there is no code', async () => {
    await i18n.changeLanguage('pt');
    const text = complianceRunErrorText(i18n.t, {
      error_message: 'PERMISSION_DENIED on main.secret.payroll',
    } as never);

    expect(text).toBe('A execução falhou. Os detalhes estão no log do app.');
    expect(text).not.toContain('payroll');
  });

  it('shows the generic text for a code without a translation', async () => {
    await i18n.changeLanguage('en');
    expect(complianceRunErrorText(i18n.t, { error_code: 'not_a_known_code' })).toBe(
      'The run failed. The details are in the app log.',
    );
  });

  it('translates the run_failed code the backend sends for errors without one', async () => {
    await i18n.changeLanguage('de');
    expect(complianceRunErrorText(i18n.t, { error_code: 'run_failed' })).toBe(
      'Der Lauf ist fehlgeschlagen. Die Details stehen im App-Log.',
    );
  });
});
