/**
 * Forms of the Conditional and Script steps in the workflow designer (#943, #942).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';

import i18n from '@/i18n/config';
import { ConditionalStepConfig, ScriptStepConfig } from './step-config-forms';
import {
  LEGACY_SCRIPT_LANGUAGE,
  localStepConfigIssue,
  scriptLanguageOf,
  stepConfigIssueText,
} from './step-config-checks';

const api = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ post: api.post, get: vi.fn() }) }));
vi.mock('./template-vars-inspector', () => ({
  default: () => <div data-testid="template-vars-inspector" />,
}));

const SCRIPT_SCHEMA = {
  type: 'object',
  properties: {
    language: { type: 'string', enum: ['sql'], default: 'sql' },
    code: { type: 'string' },
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
  it('starts as SQL, with the help, the placeholder rules and the variables', () => {
    render(<Editable kind="script" initial={{ language: 'sql' }} />);

    expect(screen.getByTestId('script-language')).toHaveTextContent('SQL');
    expect(screen.getByText(/Runs on the SQL warehouse set in Settings/)).toBeInTheDocument();
    expect(screen.getByTestId('script-sql-placeholder-help')).toHaveTextContent(
      "A placeholder can't be inside quotes or backticks",
    );
    expect(screen.getByTestId('template-vars-inspector')).toBeInTheDocument();
    expect(screen.queryByTestId('script-language-issue')).not.toBeInTheDocument();
  });

  it('has no timeout field and no Python variables', () => {
    render(<Editable kind="script" initial={{ language: 'sql', code: 'SELECT 1' }} />);

    expect(screen.queryByLabelText('Timeout (seconds)')).not.toBeInTheDocument();
    expect(screen.queryByTestId('script-python-variables')).not.toBeInTheDocument();
  });

  it('edits the code and keeps the language', () => {
    const onConfig = vi.fn();
    render(<Editable kind="script" initial={{ language: 'sql' }} onConfig={onConfig} />);

    fireEvent.change(screen.getByLabelText('Code'), { target: { value: 'SELECT 1' } });

    expect(onConfig).toHaveBeenLastCalledWith({ language: 'sql', code: 'SELECT 1' });
  });

  it('shows a stored Python step as a disabled Python option, with what to do', () => {
    render(<Editable kind="script" initial={{ language: 'python', code: 'x = 1' }} />);

    expect(screen.getByTestId('script-language')).toHaveTextContent('Python');
    expect(screen.getByTestId('script-language-issue')).toHaveTextContent(
      'Python script steps are disabled: rewrite the step in SQL or remove it.',
    );
    // Not SQL: no SQL help, no variables inspector
    expect(screen.queryByTestId('script-sql-placeholder-help')).not.toBeInTheDocument();
    expect(screen.queryByTestId('template-vars-inspector')).not.toBeInTheDocument();
  });

  it('treats a stored step without a language as Python (the old default)', () => {
    const stored = { code: "result = {'passed': True}", timeout_seconds: 30 };
    render(<Editable kind="script" initial={stored} />);

    expect(screen.getByTestId('script-language')).toHaveTextContent('Python');
    expect(screen.getByTestId('script-language-issue')).toHaveTextContent(
      'Python script steps are disabled',
    );
  });

  it('explains the disabled Python step in the UI language', async () => {
    await i18n.changeLanguage('pt');
    render(<Editable kind="script" initial={{ code: 'x = 1' }} />);

    expect(screen.getByTestId('script-language-issue')).toHaveTextContent(
      'Etapas de script Python estão desativadas: reescreva a etapa em SQL ou remova-a.',
    );
  });

  it('asks for code once it is cleared, in the UI language', async () => {
    await i18n.changeLanguage('de');
    render(<Editable kind="script" initial={{ language: 'sql', code: 'SELECT 1' }} />);

    fireEvent.change(screen.getByLabelText('Code'), { target: { value: '' } });

    expect(screen.getByRole('alert')).toHaveTextContent('Geben Sie den Code des Skripts ein.');
  });
});

describe('step config checks', () => {
  const step = (step_type: string, config: Record<string, unknown>) =>
    ({ step_id: 's', name: 'S', step_type, config, order: 0 }) as never;

  it('finds a missing condition or code', () => {
    expect(localStepConfigIssue(step('conditional', {}))?.code).toBe('condition_required');
    expect(localStepConfigIssue(step('script', { language: 'sql', code: ' ' }))?.code).toBe(
      'script_code_required',
    );
    expect(localStepConfigIssue(step('script', {}))?.code).toBe('script_code_required');
    expect(localStepConfigIssue(step('conditional', { condition: "obj.a = 'b'" }))).toBeNull();
    expect(localStepConfigIssue(step('script', { language: 'sql', code: 'SELECT 1' }))).toBeNull();
    expect(localStepConfigIssue(step('validation', {}))).toBeNull();
  });

  it('refuses a Python script, and a script without a language (the old default)', () => {
    expect(localStepConfigIssue(step('script', { language: 'python', code: 'x = 1' }))).toEqual({
      code: 'script_python_disabled',
    });
    expect(localStepConfigIssue(step('script', { code: 'x = 1' }))).toEqual({
      code: 'script_python_disabled',
    });
    expect(localStepConfigIssue(step('script', { language: '', code: 'x = 1' }))?.code).toBe(
      'script_python_disabled',
    );
  });

  it('does not check the timeout of a SQL script', () => {
    expect(
      localStepConfigIssue(
        step('script', { code: 'SELECT 1', language: 'sql', timeout_seconds: 0 }),
      ),
    ).toBeNull();
  });

  it('knows a script language as the backend reads it', () => {
    expect(scriptLanguageOf({ language: 'sql' })).toBe('sql');
    expect(scriptLanguageOf({})).toBe(LEGACY_SCRIPT_LANGUAGE);
    expect(scriptLanguageOf({ language: '' })).toBe('python');
    expect(scriptLanguageOf({ language: 7 })).toBe('python');
  });

  it.each([
    [
      'script_python_disabled',
      {},
      'Python script steps are disabled: rewrite the step in SQL or remove it.',
    ],
    [
      'script_sql_placeholder_in_quotes',
      { placeholder: '${entity_name}' },
      "The placeholder ${entity_name} is inside quotes or backticks, "
        + "where its value can't be sent as a parameter.",
    ],
    [
      'script_sql_placeholder_in_identifier',
      { placeholder: '${entity_id}' },
      'The placeholder ${entity_id} is part of a longer name.',
    ],
    [
      'script_sql_placeholder_as_list',
      { placeholder: '${ids}' },
      'The placeholder ${ids} is the whole list of an IN (...), but its value is a single text.',
    ],
  ])('translates %s from designer.scriptStepSafety.errors', (code, params, text) => {
    const issue = { code, params, message: 'English from the backend' };
    expect(stepConfigIssueText(issue, i18n.t)).toContain(text);
  });

  it('translates the new script codes in the UI language', async () => {
    await i18n.changeLanguage('pt');
    const issue = { code: 'script_sql_placeholder_in_quotes', params: { placeholder: '${x}' } };
    expect(stepConfigIssueText(issue, i18n.t)).toContain(
      'O marcador ${x} está entre aspas ou crases',
    );
    await i18n.changeLanguage('en');
  });

  it('keeps the script texts of the other script codes', () => {
    expect(stepConfigIssueText({ code: 'script_code_required' }, i18n.t)).toBe(
      "Enter the script's code.",
    );
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
