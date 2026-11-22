/**
 * Authority Resolution details: the immutable notice for active and earlier
 * versions, the stale affirmation badge, and coded status-change errors.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithRouter } from '@/test/utils';
import AuthorityRelationDetails from './authority-relation-details';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockDelete = vi.fn();
const mockToast = vi.fn();

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: mockPost, delete: mockDelete }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mockToast }) }));
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => true, isLoading: false }),
}));
vi.mock('@/components/comments', () => ({ CommentSidebar: () => null }));
vi.mock('@/components/common/ownership-panel', () => ({ OwnershipPanel: () => null }));
vi.mock('@/components/metadata/entity-metadata-panel', () => ({ default: () => null }));
vi.mock('@/components/common/maturity-inline', () => ({ MaturityInline: () => null }));
vi.mock('@/components/common/version-navigator', () => ({ default: () => null }));
vi.mock('@/components/authority-resolution/ar-concept-links', () => ({ default: () => null }));
vi.mock('@/components/authority-resolution/authority-relation-review', () => ({ default: () => null }));
vi.mock('@/components/authority-resolution/request-authority-action-dialog', () => ({ default: () => null }));
vi.mock('@/components/authority-resolution/create-authority-relation-dialog', () => ({ default: () => null }));

const RELATION_ID = 'ar-1';

const relation = {
  id: RELATION_ID,
  name: 'Discount approval',
  status: 'draft',
  version: '1.0.0',
  editable: false,
  dna_max_threshold: 0.3,
  dna_magnitude: 0.2,
  dna_direction: 'actual-exceeds-documented',
  dna_current: false,
  fully_affirmed: false,
  affirmations: [
    {
      id: 'aff-1', role: 'Owner', principal: 'alice@example.com', principal_type: 'user',
      required: true, affirmed: true, stale: true, is_approver: true, is_reviewer: false, sort_order: 0,
    },
  ],
  criteria: [],
  prerequisites: [],
  resource_refs: [],
  domains: [],
  tags: [],
  evidence_sources: [],
};

const tr = (key: string) => i18n.t(`authority-resolution:${key}`);

function renderDetails() {
  return renderWithRouter(
    <Routes>
      <Route path="/authority-resolution/:relationId" element={<AuthorityRelationDetails />} />
    </Routes>,
    { route: `/authority-resolution/${RELATION_ID}` },
  );
}

describe('AuthorityRelationDetails', () => {
  const serveRelation = (value: unknown) => {
    mockGet.mockImplementation(async (url: string) => {
      if (url.endsWith(`/relations/${RELATION_ID}`)) return { data: value };
      if (url.includes('review-tracking')) return { data: { relation_id: RELATION_ID, reviews: [], workflows: [] } };
      return { data: [] };
    });
  };

  beforeEach(() => {
    serveRelation(relation);
    mockPost.mockResolvedValue({ data: {} });
  });

  afterEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage('en');
  });

  it('shows the immutable notice and the New Version action for a non-editable AR', async () => {
    renderDetails();

    expect(await screen.findByText(tr('editor.immutableNotice'))).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: tr('details.buttonNewVersion') }).length).toBeGreaterThan(0);
  });

  it('shows an editable AR without the notice', async () => {
    serveRelation({ ...relation, editable: true });
    renderDetails();

    await screen.findByText('Discount approval');
    expect(screen.queryByText(tr('editor.immutableNotice'))).toBeNull();
  });

  it('marks a stale affirmation as affirmed on an earlier draft and asks for a fresh affirm', async () => {
    renderDetails();

    expect(await screen.findByText(tr('details.affirmedEarlierDraft'))).toBeInTheDocument();
    expect(screen.queryByText(tr('details.affirmed'))).toBeNull();
    expect(screen.getByRole('button', { name: tr('details.buttonAffirm') })).toBeInTheDocument();
  });

  it('shows the DNA value measured on an earlier draft with a recompute hint', async () => {
    renderDetails();

    expect(await screen.findByText(tr('details.dnaStale'))).toBeInTheDocument();
  });

  it('maps a coded status conflict on activate to the translated reason', async () => {
    mockPost.mockResolvedValue({
      data: {}, error: 'Affirmations are stale', errorCode: 'authority_status_conflict',
      errorParams: { reason: 'affirmations_stale' }, status: 409,
    });
    renderDetails();

    fireEvent.click(await screen.findByRole('button', { name: tr('details.buttonActivate') }));

    await waitFor(() => expect(mockToast).toHaveBeenCalled());
    expect(mockToast).toHaveBeenCalledWith(expect.objectContaining({
      description: tr('errors.statusConflict.affirmations_stale'),
      variant: 'destructive',
    }));
  });
});
