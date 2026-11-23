/**
 * The Authority Relation editor for a non-editable (active or earlier) version:
 * definition fields are disabled, metadata stays editable, and an invalid weight
 * blocks save before any request is sent.
 */
import { screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import CreateAuthorityRelationDialog from './create-authority-relation-dialog';
import type { AuthorityRelation } from '@/types/authority-resolution';

const mockGet = vi.fn();
const mockPut = vi.fn();
const mockPost = vi.fn();
const mockToast = vi.fn();
// Toggled per test: the override and the schedule are Admin-only.
let mockIsAdmin = true;

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: mockPost, put: mockPut }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mockToast }) }));
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => mockIsAdmin, isLoading: false }),
}));
vi.mock('@/hooks/use-teams', () => ({ useTeams: () => ({ teams: [] }) }));
vi.mock('@/stores/project-store', () => ({
  useProjectContext: () => ({ currentProject: null, availableProjects: [], fetchUserProjects: () => {} }),
}));
vi.mock('@/components/ui/domain-multi-selector', () => ({ default: () => null }));
vi.mock('@/components/ui/tag-selector', () => ({ default: () => null }));
vi.mock('@/components/authority-resolution/schedule-select', () => ({ default: () => null }));
vi.mock('@/components/authority-resolution/mcp-ref-editor', () => ({ default: () => null }));

const tr = (key: string) => i18n.t(`authority-resolution:${key}`);

const relation = {
  id: 'ar-1',
  name: 'Discount approval',
  status: 'active',
  version: '1.0.0',
  editable: false,
  dna_max_threshold: 0.3,
  resolver_auth: 'obo',
  affirmations: [],
  prerequisites: [],
  resource_refs: [],
  domains: [],
  tags: [],
  evidence_slice: null,
  criteria: [
    {
      id: 'c1', name: 'Approver allowlist', rule: "obj.actor_identity IN ['a']",
      direction: 'actual-exceeds-documented', weight: 1, order: 0, enabled: true,
      copied_from: null,
    },
  ],
} as unknown as AuthorityRelation;

function renderDialog(rel: AuthorityRelation) {
  return renderWithProviders(
    <CreateAuthorityRelationDialog open onOpenChange={() => {}} onCreated={() => {}} relation={rel} />,
  );
}

describe('CreateAuthorityRelationDialog for a non-editable version', () => {
  beforeEach(() => {
    mockIsAdmin = true;
    mockGet.mockResolvedValue({ data: [] });
    mockPut.mockResolvedValue({ data: relation });
    mockPost.mockResolvedValue({ data: {} });
  });

  afterEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage('en');
  });

  it('disables the definition fields and shows the immutable notice', () => {
    renderDialog(relation);

    expect(screen.getByText(tr('editor.immutableNotice'))).toBeInTheDocument();
    expect(screen.getByPlaceholderText(tr('editor.fields.name.placeholder'))).toBeDisabled();
    expect(screen.getByDisplayValue('Approver allowlist')).toBeDisabled();
  });

  it('keeps the fields editable for an editable version', () => {
    renderDialog({ ...relation, editable: true });

    expect(screen.queryByText(tr('editor.immutableNotice'))).toBeNull();
    expect(screen.getByPlaceholderText(tr('editor.fields.name.placeholder'))).not.toBeDisabled();
  });

  it('blocks save with a field error when a weight is not a number of 0 or more', () => {
    renderDialog({ ...relation, editable: true });

    fireEvent.change(screen.getByDisplayValue('1'), { target: { value: 'abc' } });
    expect(screen.getByText(tr('criteria.errors.weightInvalid'))).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: i18n.t('common:actions.save') }));

    expect(mockPut).not.toHaveBeenCalled();
    expect(mockToast).toHaveBeenCalledWith(expect.objectContaining({ title: tr('criteria.errors.weightInvalid') }));
  });
});

describe('CreateAuthorityRelationDialog evidence slice and ADM schema', () => {
  const editable = { ...relation, editable: true } as AuthorityRelation;

  beforeEach(() => {
    mockIsAdmin = true;
    mockGet.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/authority/adm-schema')) return { data: { schema: 'demo.arf_adm', adm_version: 'ADM v0.4', conformance: null } };
      return { data: [] };
    });
    mockPut.mockResolvedValue({ data: editable });
    mockPost.mockResolvedValue({ data: editable });
  });

  afterEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage('en');
  });

  it('enables the ADM schema override for an admin', async () => {
    renderDialog({ ...editable, adm_schema_override: null });

    expect(await screen.findByText(i18n.t('authority-resolution:editor.admSchema.shared', { schema: 'demo.arf_adm' }))).toBeInTheDocument();
    expect(document.getElementById('adm-schema-override')).not.toBeDisabled();
  });

  it('disables the ADM schema override for a non-admin and shows the effective schema read-only', () => {
    mockIsAdmin = false;
    renderDialog({ ...editable, adm_schema: 'other.arf_adm', adm_schema_override: null });

    const input = document.getElementById('adm-schema-override') as HTMLInputElement;
    expect(input).toBeDisabled();
    expect(input.value).toBe('other.arf_adm');
    expect(screen.getByText(tr('editor.admSchema.adminOnly'))).toBeInTheDocument();
  });

  it('sends the stored override unchanged for a non-admin on save', async () => {
    mockIsAdmin = false;
    renderDialog({ ...editable, adm_schema_override: 'team.custom_adm' });

    fireEvent.click(screen.getByRole('button', { name: i18n.t('common:actions.save') }));

    await vi.waitFor(() => expect(mockPut).toHaveBeenCalled());
    expect(mockPut.mock.calls[0][1]).toEqual(expect.objectContaining({ adm_schema_override: 'team.custom_adm' }));
  });

  it('blocks save with an invalid action code before any request is sent', () => {
    renderDialog(editable);

    const input = document.getElementById('evidence-action-codes') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Bad Code' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(screen.getByText(tr('editor.evidenceSlice.errors.actionCodeInvalid'))).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: i18n.t('common:actions.save') }));

    expect(mockPut).not.toHaveBeenCalled();
    expect(mockPost).not.toHaveBeenCalled();
    expect(mockToast).toHaveBeenCalledWith(expect.objectContaining({ title: tr('editor.evidenceSlice.invalidToast') }));
  });

  it('rejects a window outside 1 to 3650 days', () => {
    renderDialog(editable);

    fireEvent.change(document.getElementById('evidence-window-days') as HTMLInputElement, { target: { value: '0' } });

    expect(screen.getByText(i18n.t('authority-resolution:editor.evidenceSlice.errors.windowDaysRange', { min: 1, max: 3650 }))).toBeInTheDocument();
  });

  it('sends the evidence slice shape on save', async () => {
    renderDialog({
      ...editable,
      action: 'approve',
      evidence_slice: { action_codes: ['approve', 'escalate'], object_refs: ['promo-1'], domain_scope: false, window_days: 30, sample_size: 200 },
    });

    fireEvent.click(screen.getByRole('button', { name: i18n.t('common:actions.save') }));

    await vi.waitFor(() => expect(mockPut).toHaveBeenCalled());
    expect(mockPut.mock.calls[0][1].evidence_slice).toEqual({
      action_codes: ['approve', 'escalate'], object_refs: ['promo-1'], domain_scope: false, window_days: 30, sample_size: 200,
    });
    expect(mockPut.mock.calls[0][1]).not.toHaveProperty('evidence_sources');
  });

  it('lists the findings of a refused non-conformant override', async () => {
    mockPut.mockResolvedValue({
      data: {}, error: 'not conformant', errorCode: 'adm_nonconformant',
      errorParams: { schema: 'team.bad', findings: [{ code: 'missing_column', table: 'decisions', column: 'approved_at' }] },
      status: 422,
    });
    renderDialog(editable);

    fireEvent.click(screen.getByRole('button', { name: i18n.t('common:actions.save') }));

    expect(await screen.findByText('approved_at', { exact: false })).toBeInTheDocument();
    expect(mockToast).toHaveBeenCalledWith(expect.objectContaining({
      description: tr('adm.errors.nonconformant'), variant: 'destructive',
    }));
  });
});

