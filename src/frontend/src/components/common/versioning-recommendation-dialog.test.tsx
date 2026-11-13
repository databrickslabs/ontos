import { screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import VersioningRecommendationDialog from './versioning-recommendation-dialog';

const analysis = {
  change_type: 'major',
  version_bump: 'major',
  summary: '**Breaking Changes (1):**\n- Removed output port: b',
  breaking_changes: ['Removed output port: b'],
  new_features: [],
  fixes: [],
};

const renderDialog = (overrides = {}) =>
  renderWithProviders(
    <VersioningRecommendationDialog
      isOpen
      onOpenChange={vi.fn()}
      analysis={{ ...analysis, ...overrides }}
      userCanOverride={false}
      onUpdateInPlace={vi.fn()}
      onCreateNewVersion={vi.fn()}
    />,
  );

describe('VersioningRecommendationDialog', () => {
  it('shows the bump label once', () => {
    renderDialog();

    expect(screen.getAllByText('MAJOR')).toHaveLength(1);
    expect(screen.queryByText(/MAJOR MAJOR/)).toBeNull();
  });

  it('falls back to the upper-cased value for an unknown bump', () => {
    renderDialog({ version_bump: 'custom' });

    expect(screen.getByText('CUSTOM')).toBeTruthy();
  });

  it('renders the summary markdown instead of raw markers', () => {
    renderDialog();

    expect(screen.getByText('Breaking Changes (1):').tagName).toBe('STRONG');
    expect(screen.queryByText(/\*\*Breaking Changes/)).toBeNull();
  });
});
