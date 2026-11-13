import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mockGet = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { count?: number }) =>
      opts?.count !== undefined ? `${key}:${opts.count}` : key,
    i18n: { language: 'en' },
  }),
}));

const modalProps = vi.fn();
vi.mock('@/components/compliance/compliance-modal', () => ({
  default: (props: { open: boolean; canWrite: boolean; onSaved?: () => void }) => {
    modalProps(props);
    return props.open ? (
      <div data-testid="compliance-modal" data-can-write={String(props.canWrite)}>
        <button onClick={() => props.onSaved?.()}>save</button>
      </div>
    ) : null;
  },
}));

import EntityComplianceButton from './entity-compliance-button';

const completeness = (applicable: boolean, missing: string[] = []) => ({
  data: { applicable, passed: missing.length === 0, missing, messages: [] },
});

describe('EntityComplianceButton', () => {
  beforeEach(() => {
    mockGet.mockReset();
    modalProps.mockReset();
  });

  it('renders nothing when no template is active', async () => {
    mockGet.mockResolvedValue(completeness(false));
    const { container } = render(
      <EntityComplianceButton entityType="asset" entityId="a-1" canWrite />,
    );
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(mockGet).toHaveBeenCalledWith(
      '/api/compliance-templates/entities/asset/a-1/completeness',
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when the status can not be read', async () => {
    mockGet.mockResolvedValue({ data: {}, error: 'forbidden' });
    const { container } = render(
      <EntityComplianceButton entityType="asset" entityId="a-1" canWrite={false} />,
    );
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the missing mandatory field count as an advisory badge', async () => {
    mockGet.mockResolvedValue(completeness(true, ['Limitations', 'Intended use']));
    render(<EntityComplianceButton entityType="asset" entityId="a-1" canWrite />);
    const button = await screen.findByRole('button', { name: /complianceTemplates.button/ });
    expect(button).toHaveAttribute('title', 'complianceTemplates.missingFields:2');
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('shows no badge when every mandatory field is filled', async () => {
    mockGet.mockResolvedValue(completeness(true));
    render(<EntityComplianceButton entityType="asset" entityId="a-1" canWrite />);
    const button = await screen.findByRole('button', { name: /complianceTemplates.button/ });
    expect(button).toHaveAttribute('title', 'complianceTemplates.complete');
    expect(button.querySelector('.ml-2')).toBeNull();
  });

  it('opens the modal read-only for readers and refreshes the status after a save', async () => {
    mockGet.mockResolvedValueOnce(completeness(true, ['Limitations']));
    mockGet.mockResolvedValueOnce(completeness(true));
    render(<EntityComplianceButton entityType="asset" entityId="a-1" canWrite={false} />);
    await userEvent.click(
      await screen.findByRole('button', { name: /complianceTemplates.button/ }),
    );
    expect(screen.getByTestId('compliance-modal')).toHaveAttribute('data-can-write', 'false');
    await userEvent.click(screen.getByRole('button', { name: 'save' }));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText('1')).not.toBeInTheDocument());
  });
});
