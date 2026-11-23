import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ComplianceTrendMini from './compliance-trend-mini';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe('ComplianceTrendMini', () => {
  it('shows "No score" when no day has a score', () => {
    render(<ComplianceTrendMini data={[null, null, null]} />);
    expect(screen.getByText('runScoreCoverage.noScore')).toBeInTheDocument();
  });

  it('breaks the line on a day without a score instead of dropping to 0', () => {
    const { container } = render(<ComplianceTrendMini data={[80, null, 90]} />);
    const line = container.querySelector('path[fill="none"]');
    // two segments: one "M" per scored run of days
    expect((line?.getAttribute('d') ?? '').match(/M/g)).toHaveLength(2);
    // no point is drawn for the missing day
    expect(container.querySelectorAll('circle[r="2"]')).toHaveLength(2);
    expect(container.innerHTML).not.toContain('NaN');
  });
});
