/**
 * The DNA-Coefficient display: the two-dimension line, the bars for three or more dimensions,
 * the legacy magnitude-only fallback, the magnitude against its ceiling, and the loading and empty states.
 */
import { screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import DnaPositionDisplay from './dna-position-display';

const tr = (key: string, opts?: Record<string, unknown>) => i18n.t(`authority-resolution:${key}`, opts);

/** The element with a data-testid (the display's markers and bars are not labelled by role). */
const byTestId = (id: string): HTMLElement => document.querySelector(`[data-testid="${id}"]`) as HTMLElement;

describe('DnaPositionDisplay', () => {
  it('draws two dimensions on one -1 to +1 line with a marker each and the combined position', () => {
    renderWithProviders(
      <DnaPositionDisplay
        magnitude={0.2}
        position={0.1}
        ceiling={0.3}
        dimensions={{
          people: { position: -0.5, magnitude: 0.1, weight: 1 },
          policy: { position: 0.7, magnitude: 0.3, weight: 1 },
        }}
      />,
    );

    // -0.5 -> 25%, +0.7 -> 85%, +0.1 -> 55% (floating point, so compare numerically)
    expect(parseFloat(byTestId('dna-line-marker-people').style.left)).toBeCloseTo(25);
    expect(parseFloat(byTestId('dna-line-marker-policy').style.left)).toBeCloseTo(85);
    expect(parseFloat(byTestId('dna-line-combined').style.left)).toBeCloseTo(55);
    expect(document.querySelector('[data-testid^="dna-bar-"]')).toBeNull();
  });

  it('keeps the definition entry off the line: two signed dimensions plus structural', () => {
    renderWithProviders(
      <DnaPositionDisplay
        magnitude={0.2}
        position={0.1}
        ceiling={0.3}
        dimensions={{
          people: { position: -0.5, magnitude: 0.1, weight: 1 },
          policy: { position: 0.7, magnitude: 0.3, weight: 1 },
          structural: { position: 0, magnitude: 0.8, weight: 0.5, kind: 'definition' },
        }}
      />,
    );

    expect(byTestId('dna-line-marker-people')).toBeInTheDocument();
    expect(byTestId('dna-line-marker-structural')).toBeNull();
    expect(byTestId('dna-definition-bar-structural')).toBeInTheDocument();
    expect(screen.getByText(tr('dna.definitionNote'))).toBeInTheDocument();
  });

  it('draws one signed bar per dimension for three or more signed dimensions', () => {
    renderWithProviders(
      <DnaPositionDisplay
        magnitude={0.4}
        position={0.2}
        ceiling={0.3}
        dimensions={{
          people: { position: -0.4, magnitude: 0.2, weight: 1 },
          policy: { position: 0.6, magnitude: 0.4, weight: 1 },
          process: { position: 0.1, magnitude: 0.1, weight: 1 },
          structural: { position: 0, magnitude: 0.8, weight: 0.5, kind: 'definition' },
        }}
      />,
    );

    expect(byTestId('dna-bar-people')).toBeInTheDocument();
    expect(byTestId('dna-bar-policy')).toBeInTheDocument();
    expect(byTestId('dna-bar-process')).toBeInTheDocument();
    expect(byTestId('dna-definition-bar-structural')).toBeInTheDocument();
    expect(byTestId('dna-line-combined')).toBeNull();
  });

  it('falls back to magnitude-only bars and labels the run legacy for number-valued dimensions', () => {
    renderWithProviders(
      <DnaPositionDisplay magnitude={0.2} position={null} ceiling={0.3} dimensions={{ people: 0.15, policy: 0.2 }} />,
    );

    expect(byTestId('dna-legacy-note')).toHaveTextContent(tr('dna.legacyNote'));
    expect(byTestId('dna-legacy-bar-people')).toBeInTheDocument();
    expect(document.querySelector('[data-testid^="dna-line-marker-"]')).toBeNull();
    expect(document.querySelector('[data-testid^="dna-bar-"]')).toBeNull();
  });

  it('shows the magnitude against the ceiling and flags a value above it', () => {
    renderWithProviders(<DnaPositionDisplay magnitude={0.4} position={null} ceiling={0.3} dimensions={null} />);

    expect(screen.getByText(tr('dna.magnitudeOfCeiling', { magnitude: '0.40', ceiling: '0.30' }))).toBeInTheDocument();
    expect(screen.getByText(tr('dna.overCeiling'))).toBeInTheDocument();
  });

  it('shows a value within the ceiling as within', () => {
    renderWithProviders(<DnaPositionDisplay magnitude={0.15} position={null} ceiling={0.3} dimensions={null} />);

    expect(screen.getByText(tr('dna.magnitudeOfCeiling', { magnitude: '0.15', ceiling: '0.30' }))).toBeInTheDocument();
    expect(screen.getByText(tr('dna.withinCeiling'))).toBeInTheDocument();
    expect(screen.queryByText(tr('dna.overCeiling'))).toBeNull();
  });

  it('renders a skeleton while the measurement is computing', () => {
    const { container } = renderWithProviders(
      <DnaPositionDisplay magnitude={null} position={null} ceiling={0.3} dimensions={null} loading />,
    );

    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(screen.queryByText(tr('dna.empty'))).toBeNull();
  });

  it('shows the empty state when the AR was never measured', () => {
    renderWithProviders(<DnaPositionDisplay magnitude={null} position={null} ceiling={0.3} dimensions={null} />);

    expect(screen.getByText(tr('dna.empty'))).toBeInTheDocument();
  });
});
