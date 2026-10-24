import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, defaultValue: string) => defaultValue || key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

const getMock = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: getMock }),
}));

import { VersionHistoryPanel } from './version-history-panel';

const IRI = 'http://example.org/concepts/Customer';

describe('VersionHistoryPanel', () => {
  beforeEach(() => {
    getMock.mockReset();
  });

  it('shows the empty state (not "unavailable") when there are no version rows', async () => {
    getMock.mockResolvedValue({
      data: { iri: IRI, label: 'Customer', current_version: null, versions: [], replaced_by_iris: [] },
      error: null,
    });
    render(<VersionHistoryPanel conceptIri={IRI} />);
    expect(await screen.findByText('No previous versions yet.')).toBeInTheDocument();
    expect(screen.queryByText('Version history is unavailable.')).not.toBeInTheDocument();
  });

  it('treats a not-found version lookup as an empty history', async () => {
    getMock.mockResolvedValue({ data: {}, error: 'Concept not found' });
    render(<VersionHistoryPanel conceptIri={IRI} />);
    expect(await screen.findByText('No previous versions yet.')).toBeInTheDocument();
  });

  it('still reports unavailable on a genuine failure', async () => {
    getMock.mockResolvedValue({ data: {}, error: 'Failed to retrieve version info' });
    render(<VersionHistoryPanel conceptIri={IRI} />);
    expect(await screen.findByText('Version history is unavailable.')).toBeInTheDocument();
  });

  it('renders the read-only note when provided', async () => {
    getMock.mockResolvedValue({
      data: { iri: IRI, label: 'Customer', current_version: 1, versions: [], replaced_by_iris: [] },
      error: null,
    });
    render(<VersionHistoryPanel conceptIri={IRI} readOnlyNote="Versioning applies to governed schemes." />);
    expect(await screen.findByTestId('version-history-readonly-note')).toHaveTextContent(
      'Versioning applies to governed schemes.',
    );
  });
});
