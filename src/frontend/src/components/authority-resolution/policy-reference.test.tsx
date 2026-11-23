/**
 * Policy references (ARF 1.2.0, metadata only): the link out is http(s) only, the
 * validity shows an informational "Expired" badge, the clause labels are free text
 * with the reference's clauses as suggestions, and the reference editor's clause
 * suggestions are trimmed and checked for duplicates.
 */
import { screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import PolicyCitationView, { ValidityLine, safeHttpUrl, formatDay } from './policy-citation-view';
import { parseClauseLabels } from './clause-labels-input';
import { clausesFromDrafts } from './authority-policy-dialog';

const t = (key: string, options?: any) => i18n.t(key, { ns: 'authority-resolution', ...options }) as string;

describe('safeHttpUrl', () => {
  it('keeps http and https links and drops every other scheme', () => {
    expect(safeHttpUrl('https://docs.example/doa.pdf')).toBe('https://docs.example/doa.pdf');
    expect(safeHttpUrl('http://docs.example/doa')).toBe('http://docs.example/doa');
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull();
    expect(safeHttpUrl('data:text/html,hi')).toBeNull();
    expect(safeHttpUrl('not a url')).toBeNull();
    expect(safeHttpUrl(null)).toBeNull();
  });
});

describe('formatDay', () => {
  it('shows the day of an ISO timestamp', () => {
    expect(formatDay('2024-01-01T00:00:00+00:00')).toBe('2024-01-01');
    expect(formatDay(undefined)).toBe('—');
  });
});

describe('ValidityLine', () => {
  it('shows an open-ended window and the expired badge as information', () => {
    renderWithProviders(<ValidityLine from="2024-01-01T00:00:00+00:00" to={null} expired={false} />);
    expect(screen.getByText(/2024-01-01/)).toBeInTheDocument();
    expect(screen.getByText(t('policy.validity.openEnded'), { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(t('policy.validity.expired'))).toBeNull();
  });

  it('marks a lapsed window as expired', () => {
    renderWithProviders(<ValidityLine from="2023-01-01T00:00:00+00:00" to="2024-01-01T00:00:00+00:00" expired />);
    expect(screen.getByText(t('policy.validity.expired'))).toBeInTheDocument();
  });
});

describe('PolicyCitationView', () => {
  it('lists the cited clause labels as typed and links out only for http(s)', () => {
    renderWithProviders(
      <PolicyCitationView
        citation={{
          authority_policy_id: 'p1',
          clause_refs: ['§9', '§7.1'],
          policy_key: 'POL-DOA',
          version: '2',
          title: 'Delegation',
          url: 'javascript:alert(1)',
          valid_from: '2024-01-01T00:00:00+00:00',
          valid_to: null,
          expired: false,
        }}
      />,
    );
    expect(screen.getByText('§9')).toBeInTheDocument();
    expect(screen.getByText('§7.1')).toBeInTheDocument();
    expect(screen.queryByText(t('policy.citation.link'))).toBeNull();
  });

  it('falls back to the legacy justification when no reference is cited', () => {
    renderWithProviders(<PolicyCitationView citation={null} legacy={{ note: 'board minute' }} />);
    expect(screen.getByText(t('policy.citation.legacy'))).toBeInTheDocument();
  });
});

describe('parseClauseLabels', () => {
  it('splits on commas, trims, and drops empties and repeats', () => {
    expect(parseClauseLabels(' §7.1, §7.2 ,, §7.1 ')).toEqual(['§7.1', '§7.2']);
    expect(parseClauseLabels('')).toEqual([]);
  });

  it('keeps labels the reference does not list (free text)', () => {
    expect(parseClauseLabels('§99')).toEqual(['§99']);
  });
});

describe('clausesFromDrafts (reference clause suggestions)', () => {
  it('trims, drops empty rows and reports a missing or repeated reference', () => {
    expect(clausesFromDrafts([
      { ref: ' §1 ', title: ' Award ', text: '' },
      { ref: '', title: '', text: '' },
    ])).toEqual({ value: [{ ref: '§1', title: 'Award' }] });
    expect(clausesFromDrafts([{ ref: '', title: 'no ref', text: '' }]).error).toBe('policy.editor.validation.clauseRef');
    expect(clausesFromDrafts([
      { ref: '§1', title: '', text: '' },
      { ref: '§1', title: '', text: '' },
    ]).error).toBe('policy.editor.validation.clauseDuplicate');
  });
});
