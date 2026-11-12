/**
 * Trying a rule's LLM_CHECK criteria on a sample entity in the rule editor (#1479).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';

const post = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ post }) }));

import i18n from '@/i18n/config';
import { LlmCheckTester } from './llm-check-tester';

const RULE = "MATCH (d:domain)\nASSERT LLM_CHECK(d.description, 'states the grain')";

function result(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      entity_type: 'domain', entity_id: 'd1', entity_name: 'misc', passed: false,
      error_code: null,
      llm_checks: [{
        criterion: 'states the grain', passed: false,
        reason: 'does not say what one row is', code: null, cached: false,
      }],
      ...overrides,
    },
  };
}

describe('LlmCheckTester', () => {
  beforeEach(() => {
    post.mockReset();
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('tests the rule in the editor on the named entity and shows the reason', async () => {
    post.mockResolvedValue(result());
    const user = userEvent.setup();
    render(<LlmCheckTester getRule={() => RULE} />);

    await user.type(screen.getByLabelText('Test on a sample entity'), ' misc ');
    await user.click(screen.getByRole('button', { name: 'Test' }));

    expect(post).toHaveBeenCalledWith('/api/compliance/llm-check/test', { rule: RULE, entity: 'misc' });
    const shown = await screen.findByTestId('llm-check-test-result');
    expect(shown).toHaveTextContent('domain misc');
    expect(shown).toHaveTextContent('Failed');
    expect(shown).toHaveTextContent('FAIL');
    expect(shown).toHaveTextContent('states the grain');
    expect(shown).toHaveTextContent('does not say what one row is');
  });

  it('uses the first match when no entity is given', async () => {
    post.mockResolvedValue(result({
      passed: true,
      llm_checks: [{ criterion: 'states the grain', passed: true, reason: 'daily grain', cached: true }],
    }));
    const user = userEvent.setup();
    render(<LlmCheckTester getRule={() => RULE} />);

    await user.click(screen.getByRole('button', { name: 'Test' }));

    expect(post).toHaveBeenCalledWith('/api/compliance/llm-check/test', { rule: RULE, entity: null });
    const shown = await screen.findByTestId('llm-check-test-result');
    expect(shown).toHaveTextContent('Passed');
    expect(shown).toHaveTextContent('daily grain');
    expect(shown).toHaveTextContent('(cached)');
  });

  it("shows a check without a verdict by its code, in the user's language", async () => {
    await i18n.changeLanguage('pt');
    post.mockResolvedValue(result({
      error_code: 'llm_check_no_endpoint',
      llm_checks: [{ criterion: 'states the grain', passed: false, reason: '', code: 'llm_check_no_endpoint' }],
    }));
    const user = userEvent.setup();
    render(<LlmCheckTester getRule={() => RULE} />);

    await user.click(screen.getByRole('button', { name: 'Testar' }));

    expect(await screen.findByText(
      'Nenhum endpoint de serving está configurado, então o LLM_CHECK falha.',
    )).toBeInTheDocument();
  });

  it('shows a coded API error translated', async () => {
    post.mockResolvedValue({
      data: {}, error: "No entity the rule matches was found with the name 'nope'",
      errorCode: 'sample_entity_not_found', errorParams: { entity: 'nope' },
    });
    const user = userEvent.setup();
    render(<LlmCheckTester getRule={() => RULE} />);

    await user.click(screen.getByRole('button', { name: 'Test' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No entity the rule matches was found. Check the name, or leave it empty to use the first match.',
    );
  });

  it('shows the API message for an error without a code', async () => {
    post.mockResolvedValue({ data: {}, error: 'Failed to parse rule: Unexpected token: EOF' });
    const user = userEvent.setup();
    render(<LlmCheckTester getRule={() => RULE} />);

    await user.click(screen.getByRole('button', { name: 'Test' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to parse rule: Unexpected token: EOF');
  });

  it('asks for a rule before calling the API', async () => {
    const user = userEvent.setup();
    render(<LlmCheckTester getRule={() => '  '} />);

    await user.click(screen.getByRole('button', { name: 'Test' }));

    expect(post).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a rule first.');
  });
});
