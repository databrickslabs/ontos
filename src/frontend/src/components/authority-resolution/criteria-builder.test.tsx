/**
 * Criteria rows of an Authority Resolution: weight validation, the payload sent
 * on save (no policy_id, provenance kept as a label), and the read-only state.
 */
import { screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import CriteriaBuilder, {
  emptyCriterionRow,
  hasInvalidWeight,
  parseWeight,
  rowsFromCriteria,
  rowsToPayload,
  type CriterionRow,
} from './criteria-builder';

const mockGet = vi.fn();
const mockPost = vi.fn();

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: mockGet, post: mockPost }) }));

const t = (key: string, options?: any) => i18n.t(key, { ns: 'authority-resolution', ...options }) as string;

const row = (patch: Partial<CriterionRow> = {}): CriterionRow => ({
  ...emptyCriterionRow(t),
  mode: 'raw',
  rawRule: "obj.actor_identity IN ['a']",
  name: 'Approver allowlist',
  ...patch,
});

describe('weight parsing', () => {
  it('keeps 0 as 0', () => {
    expect(parseWeight('0')).toBe(0);
    expect(hasInvalidWeight([row({ weight: '0' })])).toBe(false);
    expect(rowsToPayload([row({ weight: '0' })])[0].weight).toBe(0);
  });

  it('treats empty, non-numeric and negative weights as invalid', () => {
    for (const bad of ['', '   ', 'abc', '-1', 'Infinity', 'NaN']) {
      expect(parseWeight(bad)).toBeNull();
      expect(hasInvalidWeight([row({ weight: bad })])).toBe(true);
    }
  });

  it('accepts decimals', () => {
    expect(parseWeight('0.25')).toBe(0.25);
  });
});

describe('rowsToPayload', () => {
  it('never sends policy_id and sends copied_from as provenance only', () => {
    const payload = rowsToPayload([
      row({ copiedFrom: { kind: 'compliance', label: 'Approver allowlist', id: 'chk-1' } }),
    ]);
    expect(payload).toHaveLength(1);
    expect(payload[0]).not.toHaveProperty('policy_id');
    expect(payload[0].rule).toBe("obj.actor_identity IN ['a']");
    expect(payload[0].copied_from).toEqual({ kind: 'compliance', label: 'Approver allowlist', id: 'chk-1' });
  });

  it('sends template_key for an ARF template row and lets the server fill the rule', () => {
    const payload = rowsToPayload([
      row({ templateKey: 'mfa_required', copiedFrom: { kind: 'template', label: 'MFA required', key: 'mfa_required' } }),
    ]);
    expect(payload[0]).toMatchObject({ template_key: 'mfa_required', weight: 1 });
    expect(payload[0]).not.toHaveProperty('rule');
    expect(payload[0]).not.toHaveProperty('name');
  });

  it('round-trips saved criteria, including copied_from and enabled', () => {
    const rows = rowsFromCriteria([
      {
        id: 'c1', name: 'Migrated check', rule: "obj.escalated = True", failure_message: 'Needs escalation',
        direction: 'neutral', weight: 0, order: 0, enabled: false,
        copied_from: { kind: 'migrated', label: 'Old check' },
      },
    ]);
    const [payload] = rowsToPayload(rows);
    expect(payload).toMatchObject({ name: 'Migrated check', weight: 0, enabled: false });
    expect(payload.copied_from).toEqual({ kind: 'migrated', label: 'Old check' });
  });
});

describe('CriteriaBuilder', () => {
  beforeEach(() => {
    mockGet.mockImplementation(async (url: string) => {
      if (url.includes('/criteria/templates')) {
        return { data: [{ key: 'mfa_required', name: 'MFA required', rule: 'x', failure_message: 'y', dimension: 'people', direction: 'neutral', description: 'Needs MFA' }] };
      }
      return { data: [{ id: 'chk-1', name: 'SoD check', rule: "obj.a = 'b'", failure_message: 'nope' }] };
    });
  });

  afterEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage('en');
  });

  it('shows the copied-from note for a copied row and no policy link', () => {
    const rows = [row({ copiedFrom: { kind: 'compliance', label: 'SoD check', id: 'chk-1' } })];
    renderWithProviders(<CriteriaBuilder rows={rows} onChange={() => {}} />);

    expect(screen.getByText('Copied from SoD check')).toBeInTheDocument();
    // No live link: the row has no policy selector, only the copied label.
    expect(document.querySelector('select option[value="chk-1"]')).toBeNull();
  });

  it('shows the field error for an invalid weight', () => {
    renderWithProviders(<CriteriaBuilder rows={[row({ weight: 'abc' })]} onChange={() => {}} />);
    expect(screen.getByText('Weight must be a number of 0 or more.')).toBeInTheDocument();
  });

  it('offers the Add check menu only when editable', async () => {
    const { unmount } = renderWithProviders(<CriteriaBuilder rows={[]} onChange={() => {}} />);
    expect(screen.getByRole('button', { name: /Add check/ })).toBeInTheDocument();
    unmount();

    renderWithProviders(<CriteriaBuilder rows={[]} onChange={() => {}} readOnly />);
    expect(screen.queryByRole('button', { name: /Add check/ })).toBeNull();
  });
});
