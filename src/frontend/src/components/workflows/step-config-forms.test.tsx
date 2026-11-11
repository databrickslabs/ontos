/**
 * Forms of the Conditional and Script steps in the workflow designer (#943, #942).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';

import i18n from '@/i18n/config';
import { ConditionalStepConfig, ScriptStepConfig } from './step-config-forms';
import { localStepConfigIssue, stepConfigIssueText } from './step-config-checks';

const api = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ post: api.post, get: vi.fn() }) }));
vi.mock('./template-vars-inspector', () => ({
  default: () => <div data-testid="template-vars-inspector" />,
}));

const SCRIPT_SCHEMA = {
  type: 'object',
  properties: {
    language: { type: 'string', enum: ['python', 'sql'], default: 'python' },
    code: { type: 'string' },
    timeout_seconds: { type: 'integer', default: 60, minimum: 1 },
  },
  required: ['code'],
};

// Holds the config like the designer does, so edits show up in the form.
function Editable({
  kind,
  initial = {},
  onConfig = () => {},
}: {
  kind: 'conditional' | 'script';
  initial?: Record<string, unknown>;
  onConfig?: (config: Record<string, unknown>) => void;
}) {
  const [config, setConfig] = useState<Record<string, unknown>>(initial);
  const change = (next: Record<string, unknown>) => {
    setConfig(next);
    onConfig(next);
  };
  return kind === 'conditional' ? (
    <ConditionalStepConfig config={config} onChange={change} />
  ) : (
    <ScriptStepConfig config={config} schema={SCRIPT_SCHEMA} onChange={change} />
  );
}

beforeEach(() => {
  api.post.mockReset();
  api.post.mockResolvedValue({ data: { valid: true, code: null, params: {}, message: null } });
});

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('ConditionalStepConfig', () => {
  it('edits the condition and explains the branches and the syntax', async () => {
    const onConfig = vi.fn();
    render(<Editable kind="conditional" onConfig={onConfig} />);

    fireEvent.change(screen.getByLabelText('Condition'), { target: { value: "obj.status = 'active'" } });

    expect(onConfig).toHaveBeenLastCalledWith({ condition: "obj.status = 'active'" });
    expect(screen.getByText(/follows the Pass branch; when it is false, the Fail branch/)).toBeInTheDocument();
    expect(screen.getByText("obj.name CONTAINS 'email' OR obj.name CONTAINS 'phone'")).toBeInTheDocument();
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/api/workflows/check-condition', { condition: "obj.status = 'active'" }),
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows where a condition does not parse, in the UI language', async () => {
    await i18n.changeLanguage('pt');
    api.post.mockResolvedValue({
      data: {
        valid: false,
        code: 'condition_syntax_error',
        params: { line: 1, column: 13 },
        message: 'Parser error at line 1, column 13: Unexpected token: =',
      },
    });
    render(<Editable kind="conditional" />);

    fireEvent.change(screen.getByLabelText('Condição'), { target: { value: "obj.status == 'active'" } });

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'A condição não pôde ser interpretada (linha 1, coluna 13).',
    );
  });

  it('asks for a condition once it is cleared', () => {
    render(<Editable kind="conditional" initial={{ condition: 'x' }} />);

    fireEvent.change(screen.getByLabelText('Condition'), { target: { value: '' } });

    expect(screen.getByRole('alert')).toHaveTextContent('Enter a condition.');
  });

  it('keeps an existing condition when it loads', () => {
    render(<Editable kind="conditional" initial={{ condition: "obj.name CONTAINS 'email'" }} />);

    expect(screen.getByLabelText('Condition')).toHaveValue("obj.name CONTAINS 'email'");
  });
});

describe('ScriptStepConfig', () => {
  it('starts as Python with the schema timeout, and documents the variables', () => {
    render(<Editable kind="script" />);

    expect(screen.getByTestId('script-language')).toHaveTextContent('Python');
    expect(screen.getByLabelText('Timeout (seconds)')).toHaveValue(60);
    const variables = screen.getByTestId('script-python-variables');
    for (const name of ['entity', 'entity_type', 'entity_id', 'entity_name', 'user_email', 'step_results']) {
      expect(variables).toHaveTextContent(name);
    }
    expect(variables).toHaveTextContent("result = {'passed': False, 'message': '...'} follows the Fail branch");
  });

  it('edits the code and the timeout', () => {
    const onConfig = vi.fn();
    render(<Editable kind="script" onConfig={onConfig} />);

    fireEvent.change(screen.getByLabelText('Code'), { target: { value: "result = {'passed': True}" } });
    fireEvent.change(screen.getByLabelText('Timeout (seconds)'), { target: { value: '15' } });

    expect(onConfig).toHaveBeenLastCalledWith({ code: "result = {'passed': True}", timeout_seconds: 15 });
  });

  it('rejects a timeout below the schema minimum', () => {
    render(<Editable kind="script" initial={{ code: 'x = 1' }} />);

    fireEvent.change(screen.getByLabelText('Timeout (seconds)'), { target: { value: '0' } });

    expect(screen.getByRole('alert')).toHaveTextContent('Enter a whole number of seconds, at least 1.');
  });

  it('shows the SQL help and template variables for a SQL script', () => {
    render(<Editable kind="script" initial={{ language: 'sql', code: 'SELECT 1' }} />);

    expect(screen.getByTestId('script-language')).toHaveTextContent('SQL');
    expect(screen.getByText(/Runs on the SQL warehouse set in Settings/)).toBeInTheDocument();
    expect(screen.getByTestId('template-vars-inspector')).toBeInTheDocument();
    expect(screen.queryByLabelText('Timeout (seconds)')).not.toBeInTheDocument();
  });

  it('asks for code once it is cleared, in the UI language', async () => {
    await i18n.changeLanguage('de');
    render(<Editable kind="script" initial={{ code: 'x = 1' }} />);

    fireEvent.change(screen.getByLabelText('Code'), { target: { value: '' } });

    expect(screen.getByRole('alert')).toHaveTextContent('Geben Sie den Code des Skripts ein.');
  });
});

describe('step config checks', () => {
  const step = (step_type: string, config: Record<string, unknown>) =>
    ({ step_id: 's', name: 'S', step_type, config, order: 0 }) as never;

  it('finds a missing condition or code and a bad timeout', () => {
    expect(localStepConfigIssue(step('conditional', {}))?.code).toBe('condition_required');
    expect(localStepConfigIssue(step('script', { code: ' ' }))?.code).toBe('script_code_required');
    expect(localStepConfigIssue(step('script', { code: 'x', timeout_seconds: 2.5 }), SCRIPT_SCHEMA)?.code).toBe(
      'script_timeout_invalid',
    );
    expect(localStepConfigIssue(step('conditional', { condition: "obj.a = 'b'" }))).toBeNull();
    expect(localStepConfigIssue(step('script', { code: 'x = 1' }), SCRIPT_SCHEMA)).toBeNull();
    expect(localStepConfigIssue(step('validation', {}))).toBeNull();
  });

  it('does not check the timeout of a SQL script, which has no timeout field', () => {
    expect(
      localStepConfigIssue(step('script', { code: 'SELECT 1', language: 'sql', timeout_seconds: 0 }), SCRIPT_SCHEMA),
    ).toBeNull();
    expect(
      localStepConfigIssue(step('script', { code: 'x = 1', language: 'python', timeout_seconds: 0 }), SCRIPT_SCHEMA)
        ?.code,
    ).toBe('script_timeout_invalid');
  });

  it('translates the too long and too complex condition codes', async () => {
    await i18n.changeLanguage('pt');
    expect(stepConfigIssueText({ code: 'condition_too_long', params: { maximum: 10000 } }, i18n.t)).toContain('10000');
    expect(stepConfigIssueText({ code: 'condition_too_complex' }, i18n.t)).toContain('aninhamento');
    await i18n.changeLanguage('en');
  });

  it('falls back to the English text for an unknown code', () => {
    expect(stepConfigIssueText({ code: 'condition_new_kind', message: 'Something new' }, i18n.t)).toBe(
      'Something new',
    );
  });
});
