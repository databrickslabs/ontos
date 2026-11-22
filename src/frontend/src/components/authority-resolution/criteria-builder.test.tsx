/**
 * Criteria rows of an Authority Resolution: weight validation, the payload sent
 * on save (no policy_id, provenance kept as a label), and the read-only state.
 */
import { screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { fireEvent } from '@testing-library/react';
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
  ...emptyCriterionRow(),
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

describe('variable picker and sample validation', () => {
  beforeEach(() => {
    mockGet.mockImplementation(async () => ({ data: [] }));
    mockPost.mockResolvedValue({ data: { passed: true, message: null } });
  });

  afterEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage('en');
  });

  it('offers the AR parameters as ctx.<key> and the scope and request fields as req.<key>', () => {
    renderWithProviders(
      <CriteriaBuilder rows={[row()]} onChange={() => {}} params={{ threshold: 100 }} scopeKeys={['market']} />,
    );
    expect(screen.getByRole('button', { name: 'ctx.threshold' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'req.market' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'req.actor_identity' })).toBeInTheDocument();
  });

  it('inserts a variable at the cursor, keeping the text on both sides', () => {
    const onChange = vi.fn();
    renderWithProviders(
      <CriteriaBuilder rows={[row({ rawRule: 'obj.value <= 1' })]} onChange={onChange}
                       params={{ threshold: 100 }} />,
    );
    const area = screen.getByDisplayValue('obj.value <= 1') as HTMLTextAreaElement;
    area.setSelectionRange(0, 0);
    fireEvent.click(screen.getByRole('button', { name: 'ctx.threshold' }));
    expect(onChange.mock.calls[0][0][0].rawRule).toBe('ctx.threshold obj.value <= 1');
  });

  it('inserts after the text at the end when the cursor is there', () => {
    const onChange = vi.fn();
    renderWithProviders(
      <CriteriaBuilder rows={[row({ rawRule: 'obj.value <=' })]} onChange={onChange} params={{ threshold: 1 }} />,
    );
    const area = screen.getByDisplayValue('obj.value <=') as HTMLTextAreaElement;
    area.setSelectionRange(area.value.length, area.value.length);
    fireEvent.click(screen.getByRole('button', { name: 'ctx.threshold' }));
    expect(onChange.mock.calls[0][0][0].rawRule).toBe('obj.value <= ctx.threshold');
  });

  it('validates on a sample with the AR parameters as ctx and its scope keys as req', async () => {
    renderWithProviders(
      <CriteriaBuilder rows={[row({ rawRule: 'obj.value <= ctx.threshold' })]} onChange={() => {}}
                       params={{ threshold: 100 }} scopeKeys={['market']} />,
    );
    fireEvent.click(screen.getByRole('button', { name: t('criteria.validation.validateButton') }));
    await screen.findByText(t('criteria.validation.ruleValid'));
    expect(mockPost).toHaveBeenCalledWith('/api/authority/criteria/validate', expect.objectContaining({
      rule: 'obj.value <= ctx.threshold',
      params: { threshold: 100 },
      context: { market: '' },
    }));
  });

  it('validates an ARF template rule that reads a parameter, without offering edits to it', async () => {
    const tplRow = row({
      rawRule: 'ASSERT obj.value <= ctx.threshold', name: 'Amount within threshold',
      templateKey: 'amount_within_threshold', copiedFrom: { kind: 'template', label: 'Amount within threshold', key: 'amount_within_threshold' },
    });
    renderWithProviders(<CriteriaBuilder rows={[tplRow]} onChange={() => {}} params={{ threshold: 100 }} />);
    expect(screen.queryByRole('button', { name: 'ctx.threshold' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: t('criteria.validation.validateButton') }));
    await screen.findByText(t('criteria.validation.ruleValid'));
    expect(mockPost).toHaveBeenCalledWith('/api/authority/criteria/validate', expect.objectContaining({
      rule: 'ASSERT obj.value <= ctx.threshold', params: { threshold: 100 },
    }));
  });
});

