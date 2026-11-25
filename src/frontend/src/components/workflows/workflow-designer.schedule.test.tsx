/**
 * The schedule and timezone of a `scheduled` trigger in the designer (#1310): shown only for
 * that trigger type, loaded from the stored trigger, sent on save, and the backend's coded
 * schedule error shown (translated) at the field.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import i18n from '@/i18n/config';
import WorkflowDesigner from './workflow-designer';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), toast: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: api.get, post: api.post, put: api.put }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('./template-vars-inspector', () => ({ default: () => null }));
// The Radix select of the real picker hangs in jsdom (see trigger-picker.test.tsx)
vi.mock('./trigger-picker', () => ({
  TriggerPicker: ({ value, onChange }: { value: string; onChange: (v: string) => void }) => (
    <select aria-label="Trigger type" value={value} onChange={e => onChange(e.target.value)}>
      <option value="manual">manual</option>
      <option value="scheduled">scheduled</option>
    </select>
  ),
}));

const STEP = {
  id: 's-1', workflow_id: 'wf-1', step_id: 'ok', name: 'OK', step_type: 'pass', config: {},
  order: 0,
};
const workflow = (trigger: Record<string, unknown>) => ({
  id: 'wf-1', name: 'Nightly check', description: '', workflow_type: 'process',
  is_active: false, is_default: false, version: 1, scope: { type: 'all', ids: [] },
  trigger: { entity_types: [], ...trigger }, steps: [STEP],
});
const SCHEDULED = workflow({
  type: 'scheduled', schedule: '0 30 2 * * ?', timezone: 'Europe/Berlin',
});
const MANUAL = workflow({ type: 'manual' });

let stored: ReturnType<typeof workflow>;

function renderDesigner() {
  return render(
    <MemoryRouter initialEntries={['/workflows/wf-1']}>
      <WorkflowDesigner workflowId="wf-1" />
    </MemoryRouter>,
  );
}

const saveButton = () => screen.getByRole('button', { name: /^Save/, hidden: true });
const putBodies = () => api.put.mock.calls
  .filter(([url]) => url === '/api/workflows/wf-1').map(call => call[1]);

async function openTrigger(container: HTMLElement) {
  const node = await waitFor(() => {
    const found = container.querySelector('.react-flow__node-trigger');
    expect(found).not.toBeNull();
    return found as HTMLElement;
  });
  fireEvent.click(node);
  return screen.findByRole('combobox', { name: 'Trigger type' });
}

function invalid(code: string, params: Record<string, unknown>, message: string) {
  return {
    error: message, errorCode: 'workflow_invalid',
    errorParams: { issues: [{ code, params, message }] },
  };
}

beforeEach(() => {
  stored = SCHEDULED;
  for (const fn of Object.values(api)) fn.mockReset();
  api.get.mockImplementation(async (url: string) => {
    if (url === '/api/workflows/wf-1') return { data: stored };
    return { data: [] };
  });
  api.put.mockImplementation(async () => ({ data: { id: 'wf-1' } }));
});

afterEach(async () => {
  await act(async () => {
    await i18n.changeLanguage('en');
  });
});

describe('WorkflowDesigner schedule fields', () => {
  it('loads the stored schedule and timezone and sends them back on save', async () => {
    const { container } = renderDesigner();
    await openTrigger(container);
    expect(screen.getByLabelText('Schedule (Quartz cron)')).toHaveValue('0 30 2 * * ?');
    expect(screen.getByLabelText('Timezone')).toHaveValue('Europe/Berlin');

    fireEvent.click(saveButton());

    await waitFor(() => expect(putBodies()).toHaveLength(1));
    expect(putBodies()[0].trigger).toMatchObject({
      type: 'scheduled', schedule: '0 30 2 * * ?', timezone: 'Europe/Berlin',
    });
  });

  it('sends an edited schedule, and an empty timezone as null (UTC)', async () => {
    const { container } = renderDesigner();
    await openTrigger(container);
    fireEvent.change(screen.getByLabelText('Schedule (Quartz cron)'), {
      target: { value: ' 0 0 6 * * ? ' },
    });
    fireEvent.change(screen.getByLabelText('Timezone'), { target: { value: '' } });

    fireEvent.click(saveButton());

    await waitFor(() => expect(putBodies()).toHaveLength(1));
    expect(putBodies()[0].trigger).toMatchObject({ schedule: '0 0 6 * * ?', timezone: null });
  });

  it('shows no schedule field for another trigger type and sends no schedule', async () => {
    stored = MANUAL;
    const { container } = renderDesigner();
    await openTrigger(container);
    expect(screen.queryByTestId('trigger-schedule-fields')).toBeNull();

    fireEvent.click(saveButton());

    await waitFor(() => expect(putBodies()).toHaveLength(1));
    expect(putBodies()[0].trigger).not.toHaveProperty('schedule');
    expect(putBodies()[0].trigger).not.toHaveProperty('timezone');
  });

  it('shows the translated schedule_required error at the field after a switch', async () => {
    stored = MANUAL;
    api.put.mockImplementation(async () => invalid(
      'schedule_required', {}, 'A scheduled trigger requires a cron expression (schedule)',
    ));
    const { container } = renderDesigner();
    const picker = await openTrigger(container);
    fireEvent.change(picker, { target: { value: 'scheduled' } });
    expect(screen.getByLabelText('Schedule (Quartz cron)')).toHaveValue('');
    expect(screen.getByLabelText('Timezone')).toHaveValue('');

    fireEvent.click(saveButton());

    await waitFor(() => expect(putBodies()).toHaveLength(1));
    expect(putBodies()[0].trigger).toMatchObject({ type: 'scheduled', schedule: '' });
    expect(await screen.findByTestId('schedule-error')).toHaveTextContent(
      'A scheduled trigger needs a cron expression.',
    );
  });

  it('shows a cron error with its params in the user language and clears it on edit',
    async () => {
      await act(async () => {
        await i18n.changeLanguage('pt');
      });
      api.put.mockImplementation(async () => invalid(
        'cron_invalid_field', { field: 'hour', value: '25' }, "'25' is not valid in the hour",
      ));
      const { container } = renderDesigner();
      await openTrigger(container);
      const input = screen.getByLabelText('Agendamento (cron Quartz)');
      fireEvent.change(input, { target: { value: '0 0 25 * * ?' } });

      fireEvent.click(screen.getByRole('button', { name: /^Salvar/, hidden: true }));

      expect(await screen.findByTestId('schedule-error')).toHaveTextContent(
        '"25" não é válido no campo hora.',
      );
      expect(api.toast.mock.calls[0][0].description).toBe('"25" não é válido no campo hora.');
      fireEvent.change(input, { target: { value: '0 0 5 * * ?' } });
      expect(screen.queryByTestId('schedule-error')).toBeNull();
    });

  it('shows a timezone error at the timezone field', async () => {
    api.put.mockImplementation(async () => invalid(
      'timezone_invalid', { timezone: 'Mars/Base' }, "Unknown timezone 'Mars/Base'",
    ));
    const { container } = renderDesigner();
    await openTrigger(container);
    fireEvent.change(screen.getByLabelText('Timezone'), { target: { value: 'Mars/Base' } });

    fireEvent.click(saveButton());

    expect(await screen.findByTestId('timezone-error')).toHaveTextContent(
      'Unknown timezone "Mars/Base": use an IANA name such as Europe/Berlin.',
    );
    expect(screen.queryByTestId('schedule-error')).toBeNull();
  });
});
