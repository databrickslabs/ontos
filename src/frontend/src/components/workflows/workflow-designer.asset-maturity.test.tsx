/**
 * The Evaluate Asset Maturity step in the designer (#1414 follow-up): its catalog and
 * schema fields are saved as the step config, a schema without a catalog is refused before
 * the save, a trigger other than scheduled or manual is flagged, the Settings permission
 * refusal is shown translated, and a run's counts are shown in the execution view.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import i18n from '@/i18n/config';
import WorkflowDesigner from './workflow-designer';
import { getAssetMaturitySummary } from './workflow-execution-dialog';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), toast: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: api.get, post: api.post, put: api.put }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('./template-vars-inspector', () => ({ default: () => null }));

const STORED = {
  id: 'wf-1', name: 'Nightly maturity', description: '', workflow_type: 'process',
  is_active: false, is_default: false, version: 1, scope: { type: 'all', ids: [] },
  trigger: { type: 'scheduled', entity_types: [], schedule: '0 0 2 * * ?', timezone: 'UTC' },
  steps: [{
    id: 's-1', workflow_id: 'wf-1', step_id: 'evaluate', name: 'Evaluate assets',
    step_type: 'evaluate_asset_maturity', config: { catalog: 'main', schema_name: 'sales' },
    order: 0,
  }],
};

function renderDesigner(workflowId = 'new') {
  const path = workflowId === 'new' ? '/workflows/new?type=process' : `/workflows/${workflowId}`;
  return render(
    <MemoryRouter initialEntries={[path]}>
      <WorkflowDesigner workflowId={workflowId} />
    </MemoryRouter>,
  );
}

async function addMaturityStep() {
  fireEvent.click(await screen.findByRole('button', { name: 'Evaluate Asset Maturity' }));
  return screen.findByRole('dialog');
}

const saveButton = () => screen.getByRole('button', { name: /^(Save|Salvar)/, hidden: true });
const postedWorkflow = () =>
  api.post.mock.calls.find(([url]) => url === '/api/workflows')?.[1];

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.get.mockImplementation(async (url: string) => ({
    data: url === '/api/workflows/wf-1' ? STORED : [],
  }));
  api.post.mockImplementation(async () => ({ data: {} }));
  api.put.mockImplementation(async () => ({ data: { id: 'wf-1' } }));
});

afterEach(async () => {
  await act(async () => {
    await i18n.changeLanguage('en');
  });
});

describe('WorkflowDesigner Evaluate Asset Maturity step', () => {
  it('saves the catalog and schema typed in the step as its config', async () => {
    renderDesigner();
    fireEvent.change(await screen.findByPlaceholderText(/workflow name/i), {
      target: { value: 'Evaluate sales' },
    });
    const dialog = await addMaturityStep();
    fireEvent.change(within(dialog).getByLabelText('Catalog'), { target: { value: 'main' } });
    fireEvent.change(within(dialog).getByLabelText('Schema'), { target: { value: 'sales' } });
    fireEvent.click(within(dialog).getByTestId('step-config-done'));

    fireEvent.click(saveButton());

    await waitFor(() => expect(postedWorkflow()).toBeDefined());
    const [step] = postedWorkflow().steps;
    expect(step.step_type).toBe('evaluate_asset_maturity');
    expect(step.config).toEqual({ catalog: 'main', schema_name: 'sales' });
  });

  it('leaves a cleared field out of the config, so the step covers every catalog', async () => {
    renderDesigner();
    fireEvent.change(await screen.findByPlaceholderText(/workflow name/i), {
      target: { value: 'Evaluate all' },
    });
    const dialog = await addMaturityStep();
    const catalog = within(dialog).getByLabelText('Catalog');
    fireEvent.change(catalog, { target: { value: 'main' } });
    fireEvent.change(catalog, { target: { value: '' } });
    fireEvent.click(within(dialog).getByTestId('step-config-done'));

    fireEvent.click(saveButton());

    await waitFor(() => expect(postedWorkflow()).toBeDefined());
    expect(postedWorkflow().steps[0].config).toEqual({});
  });

  it('flags an event trigger and refuses a schema without a catalog before saving', async () => {
    renderDesigner();
    fireEvent.change(await screen.findByPlaceholderText(/workflow name/i), {
      target: { value: 'No catalog' },
    });
    const dialog = await addMaturityStep();
    // A new workflow starts on on_create, which the step does not run on
    expect(within(dialog).getByTestId('asset-maturity-trigger')).toHaveTextContent(
      'This step runs on scheduled and manual workflows only.',
    );
    fireEvent.change(within(dialog).getByLabelText('Schema'), { target: { value: 'sales' } });
    expect(within(dialog).getByTestId('asset-maturity-scope-issue')).toHaveTextContent(
      'Enter a catalog for the schema, without dots or backticks.',
    );
    fireEvent.click(within(dialog).getByTestId('step-config-done'));

    fireEvent.click(saveButton());

    await waitFor(() => expect(api.toast).toHaveBeenCalled());
    expect(api.toast.mock.calls[0][0].description).toContain('Enter a catalog for the schema');
    expect(postedWorkflow()).toBeUndefined();
  });

  it('shows the stored scope on the node and the translated Settings refusal', async () => {
    await act(async () => {
      await i18n.changeLanguage('pt');
    });
    api.put.mockImplementation(async () => ({
      error: 'requires write access to Settings', errorCode: 'workflow_step_requires_settings_write',
      errorParams: { stepType: 'evaluate_asset_maturity', feature: 'settings' }, status: 403,
    }));
    renderDesigner('wf-1');

    expect(await screen.findByTestId('asset-maturity-node-scope')).toHaveTextContent('main.sales');
    fireEvent.click(saveButton());

    await waitFor(() => expect(api.toast).toHaveBeenCalled());
    expect(api.toast.mock.calls[0][0].description).toBe(
      'Este workflow executa a avaliação de maturidade dos ativos. '
      + 'Salvá-lo, ativá-lo ou executá-lo exige acesso de escrita em Configurações.',
    );
  });
});

describe('getAssetMaturitySummary', () => {
  const run = {
    result_data: {
      run_id: 'r-1', state: 'completed', total: 5, processed: 5, evaluated: 3, changed: 1,
      skipped: { maturity_bulk_skipped_not_found: 1, maturity_bulk_skipped_asset_type: 1 },
      error_count: 0,
    },
  };

  it('counts the evaluated, changed, skipped and failed assets of the run', () => {
    expect(getAssetMaturitySummary(run, i18n.t)).toBe(
      'Evaluated 3 of 5 assets: 1 changed level, 2 skipped, 0 errors',
    );
  });

  it('is translated, and absent for a step without the counts', async () => {
    await act(async () => {
      await i18n.changeLanguage('pt');
    });
    expect(getAssetMaturitySummary(run, i18n.t)).toBe(
      '3 de 5 ativos avaliados: 1 mudaram de nível, 2 ignorados, 0 erros',
    );
    expect(getAssetMaturitySummary({ result_data: { error_code: 'x' } }, i18n.t)).toBeUndefined();
    expect(getAssetMaturitySummary(undefined, i18n.t)).toBeUndefined();
  });
});
