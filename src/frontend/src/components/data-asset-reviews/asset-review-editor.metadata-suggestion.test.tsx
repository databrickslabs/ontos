/**
 * A Metadata Generation suggestion under review (metagen://run/suggestion) is
 * decided in MetadataSuggestionReview; the editor maps its outcome onto the
 * ReviewedAsset status, keeping "needs clarification" apart from "rejected".
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import AssetReviewEditor from './asset-review-editor';
import { AssetType, ReviewedAssetStatus, type ReviewedAsset } from '@/types/data-asset-review';

vi.mock('@/components/metadata-generation/suggestion-review', () => ({
  default: ({ assetFqn, onReviewComplete }: { assetFqn: string; onReviewComplete: (s: string) => void }) => (
    <div>
      <span>suggestion {assetFqn}</span>
      {['approved', 'rejected', 'needs_clarification'].map((s) => (
        <button key={s} type="button" onClick={() => onReviewComplete(s)}>{s}</button>
      ))}
    </div>
  ),
}));

const ASSET: ReviewedAsset = {
  id: 'a-1', asset_fqn: 'metagen://run-1/s-1', asset_type: AssetType.METADATA_SUGGESTION,
  status: ReviewedAssetStatus.PENDING, updated_at: new Date().toISOString(),
};

describe('AssetReviewEditor for metadata suggestions', () => {
  it.each([
    ['approved', ReviewedAssetStatus.APPROVED],
    ['rejected', ReviewedAssetStatus.REJECTED],
    ['needs_clarification', ReviewedAssetStatus.NEEDS_CLARIFICATION],
  ])('maps %s onto the asset status', async (outcome, status) => {
    const onReviewSave = vi.fn();
    const api = { get: vi.fn().mockResolvedValue({ data: { enabled: false } }), post: vi.fn(), put: vi.fn(), delete: vi.fn() };
    render(
      <MemoryRouter>
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        <AssetReviewEditor requestId="r-1" asset={ASSET} api={api as any} onReviewSave={onReviewSave} />
      </MemoryRouter>,
    );

    expect(screen.getByText('suggestion metagen://run-1/s-1')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: outcome }));
    expect(onReviewSave).toHaveBeenCalledWith(expect.objectContaining({ id: 'a-1', status }));
  });
});
