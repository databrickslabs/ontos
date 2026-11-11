/**
 * The designer keeps the layout the user arranged (#1419): a workflow whose
 * steps all have a position opens and saves as stored, older workflows are
 * auto-arranged once (and that layout is saved), and "Rearrange" replaces the
 * layout only after the user confirms.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import i18n from '@/i18n/config';
import WorkflowDesigner from './workflow-designer';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), toast: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, post: api.post, put: api.put }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('./template-vars-inspector', () => ({ default: () => null }));

type Pos = { x: number; y: number } | null;

function workflow(positions: Record<string, Pos>) {
  const step = (step_id: string, step_type: string, order: number, extra: Record<string, unknown> = {}) => ({
    id: `row-${step_id}`, workflow_id: 'w1', step_id, name: step_id, step_type, config: {},
    on_pass: null, on_fail: null, order, position: positions[step_id] ?? null,
    created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z', ...extra,
  });
  return {
    id: 'w1', name: 'Layout', description: '', workflow_type: 'process', is_active: true, is_default: false,
    version: 1, trigger: { type: 'manual', entity_types: ['data_product'] }, scope: { type: 'all' },
    steps: [
      step('notify', 'notification', 0, {
        config: { recipients: 'requester', template: 'validation_passed' }, on_pass: 'done',
      }),
      step('done', 'pass', 1),
    ],
    created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z',
  };
}

function renderDesigner(positions: Record<string, Pos>) {
  const wf = workflow(positions);
  api.get.mockImplementation(async (url: string) => ({
    data: url === '/api/workflows/w1' ? wf : [],
  }));
  return render(
    <MemoryRouter initialEntries={['/workflows/w1']}>
      <WorkflowDesigner workflowId="w1" />
    </MemoryRouter>,
  );
}

async function save() {
  fireEvent.click(await screen.findByRole('button', { name: /^save/i }));
  await waitFor(() => expect(api.put).toHaveBeenCalled());
  const body = api.put.mock.calls[api.put.mock.calls.length - 1]?.[1] as { steps: { step_id: string; position?: Pos }[] };
  return Object.fromEntries(body.steps.map(s => [s.step_id, s.position]));
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.put.mockResolvedValue({ data: workflow({}) });
  api.post.mockResolvedValue({ data: { valid: true, errors: [], warnings: [] } });
});

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('WorkflowDesigner layout', () => {
  it('saves the stored positions as they are, without auto-arranging', async () => {
    renderDesigner({ notify: { x: 400, y: 40 }, done: { x: -250, y: 520 } });

    expect(await save()).toEqual({ notify: { x: 400, y: 40 }, done: { x: -250, y: 520 } });
  });

  it('shows the steps where they were stored', async () => {
    const { container } = renderDesigner({ notify: { x: 400, y: 40 }, done: { x: -250, y: 520 } });

    await waitFor(() => expect(container.querySelector('.react-flow__node[data-id="done"]')).not.toBeNull());
    const transformOf = (id: string) =>
      (container.querySelector(`.react-flow__node[data-id="${id}"]`) as HTMLElement).style.transform;
    expect(transformOf('notify')).toBe('translate(400px,40px)');
    expect(transformOf('done')).toBe('translate(-250px,520px)');
    // The trigger sits above the first step.
    expect(transformOf('trigger')).toBe('translate(400px,-110px)');
  });

  it('auto-arranges a workflow without stored positions and saves that layout', async () => {
    renderDesigner({ notify: null, done: null });

    const saved = await save();

    expect(saved.notify).toEqual({ x: expect.any(Number), y: expect.any(Number) });
    expect(saved.done).toEqual({ x: expect.any(Number), y: expect.any(Number) });
    // Top to bottom: the step after "notify" is below it.
    expect(saved.done!.y).toBeGreaterThan(saved.notify!.y);
  });

  it('auto-arranges when only some steps have a position', async () => {
    renderDesigner({ notify: { x: 400, y: 40 }, done: null });

    const saved = await save();

    expect(saved.notify).not.toEqual({ x: 400, y: 40 });
    expect(saved.done).toEqual({ x: expect.any(Number), y: expect.any(Number) });
  });

  it('keeps the layout when Rearrange is cancelled', async () => {
    renderDesigner({ notify: { x: 400, y: 40 }, done: { x: -250, y: 520 } });

    fireEvent.click(await screen.findByRole('button', { name: /rearrange/i }));
    const dialog = await screen.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByRole('button', { name: /cancel/i }));

    expect(await save()).toEqual({ notify: { x: 400, y: 40 }, done: { x: -250, y: 520 } });
  });

  it('replaces the layout after Rearrange is confirmed', async () => {
    renderDesigner({ notify: { x: 400, y: 40 }, done: { x: -250, y: 520 } });

    fireEvent.click(await screen.findByRole('button', { name: /rearrange/i }));
    const dialog = await screen.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByRole('button', { name: /rearrange/i }));

    const saved = await save();
    expect(saved.notify).not.toEqual({ x: 400, y: 40 });
    expect(saved.done).not.toEqual({ x: -250, y: 520 });
    expect(saved.done!.y).toBeGreaterThan(saved.notify!.y);
    expect(saved.done!.x).toBe(saved.notify!.x);
  });

  it('marks the workflow as changed after Rearrange', async () => {
    renderDesigner({ notify: { x: 400, y: 40 }, done: { x: -250, y: 520 } });

    fireEvent.click(await screen.findByRole('button', { name: /rearrange/i }));
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: /rearrange/i }));

    expect(await screen.findByRole('button', { name: /^save \*/i })).toBeInTheDocument();
  });
});
