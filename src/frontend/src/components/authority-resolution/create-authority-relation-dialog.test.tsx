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

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: mockPost, put: mockPut }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mockToast }) }));
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => true, isLoading: false }),
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
  evidence_sources: [],
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
