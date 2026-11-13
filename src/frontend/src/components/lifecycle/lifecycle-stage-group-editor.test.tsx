/**
 * The Lifecycle Stage Group editor (#1214): stage table, transition matrix,
 * graph preview and the backend's coded validation errors inline.
 */
import { screen, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import LifecycleStageGroupEditor, { slugKey } from './lifecycle-stage-group-editor';
import type { LifecycleStageGroup } from '@/types/lifecycle-stage-groups';

const LOOP: LifecycleStageGroup = {
  id: 'g-loop', name: 'Authority resolution', entity_type: 'data_product',
  is_default_for_type: false,
  stages: [
    { key: 'draft', label: 'Draft', category: 'draft', color: 'gray', order: 0, is_initial: true },
    {
      key: 'active', label: 'Active', category: 'active', color: 'green', order: 1,
      is_initial: false,
    },
    {
      key: 'needs_review', label: 'Needs Review', category: 'review', color: 'amber', order: 2,
      is_initial: false,
    },
  ],
  transitions: [
    { from_key: 'draft', to_key: 'active' },
    { from_key: 'active', to_key: 'needs_review' },
    { from_key: 'needs_review', to_key: 'active' },
  ],
};

const response = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400, status, statusText: '',
    headers: new Headers({ 'Content-Type': 'application/json' }),
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });

function renderEditor(group: LifecycleStageGroup | null, onSaved = vi.fn()) {
  renderWithProviders(
    <LifecycleStageGroupEditor
      open onOpenChange={vi.fn()} entityType="data_product" group={group} onSaved={onSaved}
    />,
  );
  return onSaved;
}

const lastCall = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];

const sentBody = (fetchMock: ReturnType<typeof vi.fn>) =>
  JSON.parse(lastCall(fetchMock)[1].body as string);

describe('LifecycleStageGroupEditor', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn((_url: string, init?: RequestInit) =>
      response(init?.method === 'POST' ? 201 : 200, { ...LOOP, id: 'g-new' }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it('derives stage keys from labels', () => {
    expect(slugKey('Needs Review')).toBe('needs_review');
    expect(slugKey('  Revisão técnica! ')).toBe('revisao_tecnica');
  });

  it('shows a looping group in the matrix and the graph preview', () => {
    renderEditor(LOOP);

    expect(screen.getByRole('checkbox', { name: 'Allow Active → Needs Review' }))
      .toHaveAttribute('data-state', 'checked');
    expect(screen.getByRole('checkbox', { name: 'Allow Needs Review → Active' }))
      .toHaveAttribute('data-state', 'checked');
    expect(screen.getByRole('checkbox', { name: 'Allow Draft → Needs Review' }))
      .toHaveAttribute('data-state', 'unchecked');
    const graph = screen.getByRole('img', { name: /Graph of the stages/ });
    expect(graph.querySelector('[data-edge="active->needs_review"]'))
      .toHaveAttribute('data-direction', 'forward');
    expect(graph.querySelector('[data-edge="needs_review->active"]'))
      .toHaveAttribute('data-direction', 'back');
    // Stored keys are immutable: entities store them in their status
    expect(screen.getByRole('textbox', { name: 'Key of stage 3' })).toBeDisabled();
  });

  it('creates a group with a new stage, its key from the label and the ticked moves', async () => {
    const onSaved = renderEditor(null);

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Authority resolution' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add stage' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Label of stage 3' }), {
      target: { value: 'Needs Review' },
    });
    expect(screen.getByRole('textbox', { name: 'Key of stage 3' })).toHaveValue('needs_review');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Allow Active → Needs Review' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Allow Needs Review → Active' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const [url, init] = lastCall(fetchMock);
    expect(url).toBe('/api/lifecycle-stage-groups');
    expect(init.method).toBe('POST');
    const body = sentBody(fetchMock);
    expect(body).toMatchObject({
      name: 'Authority resolution', entity_type: 'data_product', is_default_for_type: false,
    });
    expect(body.stages.map((s: any) => [s.key, s.category, s.order, s.is_initial])).toEqual([
      ['draft', 'draft', 0, true],
      ['active', 'active', 1, false],
      ['needs_review', 'review', 2, false],
    ]);
    expect(body.transitions).toEqual(expect.arrayContaining([
      { from_key: 'draft', to_key: 'active' },
      { from_key: 'active', to_key: 'needs_review' },
      { from_key: 'needs_review', to_key: 'active' },
    ]));
    expect(body.transitions).toHaveLength(3);
  });

  it('reorders stages and moves the first stage', async () => {
    renderEditor(LOOP);

    fireEvent.click(screen.getByRole('button', { name: 'Move Needs Review up' }));
    fireEvent.click(screen.getByRole('radio', { name: 'Active is the first stage' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = lastCall(fetchMock);
    expect(url).toBe('/api/lifecycle-stage-groups/g-loop');
    expect(init.method).toBe('PUT');
    expect(sentBody(fetchMock).stages.map((s: any) => [s.key, s.order, s.is_initial])).toEqual([
      ['draft', 0, false],
      ['needs_review', 1, false],
      ['active', 2, true],
    ]);
  });

  it('shows the backend validation error inline and marks the stages it names', async () => {
    fetchMock.mockImplementation(() => response(400, {
      detail: {
        code: 'lifecycle_group_unreachable_stages',
        message: "Stages not reachable from 'draft': needs_review",
        params: { stages: ['needs_review'] },
      },
    }));
    const onSaved = renderEditor(LOOP);

    fireEvent.click(screen.getByRole('checkbox', { name: 'Allow Active → Needs Review' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(
      'These stages can’t be reached from the first stage: needs_review.',
    );
    expect(screen.getByTestId('stage-row-needs_review')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByTestId('stage-row-active')).not.toHaveAttribute('aria-invalid');
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('removing a stage drops its moves', async () => {
    renderEditor(LOOP);

    fireEvent.click(screen.getByRole('button', { name: 'Remove Needs Review' }));
    expect(within(screen.getByRole('table', { name: 'Transition matrix' }))
      .queryByText('Needs Review')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sentBody(fetchMock).transitions).toEqual([{ from_key: 'draft', to_key: 'active' }]);
  });
});
