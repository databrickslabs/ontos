/**
 * Lifecycle Stage Group assignment (#1215): the group picker of create dialogs,
 * the group next to the status, "Change lifecycle" and its confirmation, and
 * badges drawn from the stage data.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import i18n from '@/i18n/config';
import LifecycleGroupPicker from './lifecycle-group-picker';
import EntityLifecycleStatus from './entity-lifecycle-status';
import { buildStageLookup } from '@/hooks/use-lifecycle-stage-groups';
import { lifecycleErrorText, stageColorClass, stageLabel } from '@/lib/lifecycle-stages';
import type { LifecycleStageGroup } from '@/types/lifecycle-stage-groups';

const st = (key: string, label: string, category: string, order: number, color: string) => ({
  key, label, category, color, order, is_initial: order === 0,
}) as any;

const DEFAULT: LifecycleStageGroup = {
  id: 'g-default', name: 'Default data product lifecycle', entity_type: 'data_product',
  is_default_for_type: true,
  stages: [st('draft', 'Draft', 'draft', 0, 'gray'), st('active', 'Active', 'active', 1, 'green')],
  transitions: [{ from_key: 'draft', to_key: 'active' }],
};
const LOOP: LifecycleStageGroup = {
  id: 'g-loop', name: 'Authority resolution', entity_type: 'data_product',
  is_default_for_type: false,
  stages: [
    st('ideation', 'Ideation', 'draft', 0, 'purple'),
    st('active', 'Active', 'active', 1, 'green'),
    st('needs_review', 'Needs Review', 'review', 2, 'amber'),
  ],
  transitions: [
    { from_key: 'ideation', to_key: 'active' },
    { from_key: 'active', to_key: 'needs_review' },
    { from_key: 'needs_review', to_key: 'active' },
  ],
};

const reply = (status: number, body: unknown) => Promise.resolve({
  ok: status < 400, status, statusText: '',
  headers: new Headers({ 'Content-Type': 'application/json' }),
  json: () => Promise.resolve(body),
});

describe('stage helpers', () => {
  it('translates seeded labels while unchanged and keeps custom ones', async () => {
    await i18n.changeLanguage('pt');
    expect(stageLabel({ key: 'draft', label: 'Draft' }, i18n.t)).toBe('Rascunho');
    expect(stageLabel({ key: 'draft', label: 'Ideia' }, i18n.t)).toBe('Ideia');
    expect(stageLabel({ key: 'needs_review', label: 'Needs Review' }, i18n.t))
      .toBe('Needs Review');
    await i18n.changeLanguage('en');
  });

  it('colours a badge from its stage, else from its category', () => {
    expect(stageColorClass({ color: 'amber', category: 'review' })).toContain('bg-amber-100');
    expect(stageColorClass({ color: null, category: 'retired' })).toContain('bg-red-100');
  });

  it('finds a stage in the entity’s own group, else in the default', () => {
    const lookup = buildStageLookup([DEFAULT, LOOP]);
    expect(lookup('g-loop', 'needs_review')?.label).toBe('Needs Review');
    expect(lookup(null, 'active')?.color).toBe('green');
    expect(lookup('g-loop', 'draft')).toBeNull();
    expect(lookup('unknown', 'draft')?.key).toBe('draft');
  });

  it('translates coded lifecycle errors with their parameters', () => {
    expect(lifecycleErrorText({
      error: 'raw', errorCode: 'lifecycle_stage_in_workflow',
      errorParams: { key: 'proposed', workflows: ['Review gate', 'Notify'] },
    }, i18n.t)).toBe('Stage “proposed” can’t be removed: workflows use it (Review gate, Notify).');
    expect(lifecycleErrorText({ error: 'raw', errorCode: 'other' }, i18n.t)).toBe('raw');
  });
});

describe('LifecycleGroupPicker', () => {
  it('is hidden while the entity type has one group, and picks the default', () => {
    const onChange = vi.fn();
    renderWithProviders(
      <LifecycleGroupPicker groups={[DEFAULT]} value={null} onChange={onChange} />,
    );
    expect(screen.queryByRole('combobox', { name: 'Lifecycle' })).not.toBeInTheDocument();
    expect(onChange).toHaveBeenCalledWith('g-default');
  });

  it('offers every group when there are several, the default preselected', () => {
    const onChange = vi.fn();
    renderWithProviders(
      <LifecycleGroupPicker groups={[DEFAULT, LOOP]} value={null} onChange={onChange} />,
    );
    expect(screen.getByRole('combobox', { name: 'Lifecycle' })).toBeInTheDocument();
    expect(onChange).toHaveBeenCalledWith('g-default');
  });
});

describe('EntityLifecycleStatus', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  const lifecycle = (overrides: Record<string, unknown> = {}) => ({
    entity_type: 'data_product', entity_id: 'p1', status: 'active',
    group: { id: 'g-default', name: DEFAULT.name, entity_type: 'data_product',
      is_default_for_type: true },
    stage: DEFAULT.stages[1], allowed_transitions: [], can_change_group: true, ...overrides,
  });

  beforeEach(() => {
    fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.startsWith('/api/lifecycle-stage-groups')) return reply(200, [DEFAULT, LOOP]);
      if (init?.method === 'POST') {
        return reply(409, { detail: {
          code: 'lifecycle_change_pending_request',
          message: "The lifecycle can't change while a workflow request is pending for it",
          params: { entityId: 'p1', requestId: 'r1' },
        } });
      }
      return reply(200, lifecycle());
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it('shows the stage and the group, and confirms a change with the reset stage', async () => {
    renderWithProviders(<EntityLifecycleStatus entityType="data_product" entityId="p1" />);

    expect(await screen.findByText('Default data product lifecycle')).toBeInTheDocument();
    expect(screen.getByText('Active').className).toContain('bg-green-100');
    fireEvent.click(await screen.findByRole('button', { name: 'Change lifecycle' }));

    // The only other group is preselected; its first stage is where the status resets to
    expect(await screen.findByText(/The status resets to the first stage/)).toBeInTheDocument();
    expect(screen.getByText('Ideation')).toBeInTheDocument();
    const buttons = screen.getAllByRole('button', { name: 'Change lifecycle' });
    fireEvent.click(buttons[buttons.length - 1]);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/lifecycle/data_product/p1/change-group', expect.objectContaining({ method: 'POST' }),
    ));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')!;
    expect(JSON.parse(post[1].body)).toEqual({ group_id: 'g-loop' });
    expect(await screen.findByText(
      'The lifecycle can’t change while a workflow request is pending for it.',
    )).toBeInTheDocument();
  });

  it('offers no change to whom the API refuses it', async () => {
    fetchMock.mockImplementation((url: string) => url.startsWith('/api/lifecycle-stage-groups')
      ? reply(200, [DEFAULT, LOOP]) : reply(200, lifecycle({ can_change_group: false })));
    renderWithProviders(<EntityLifecycleStatus entityType="data_product" entityId="p1" />);

    expect(await screen.findByText('Default data product lifecycle')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Change lifecycle' })).not.toBeInTheDocument();
  });
});
