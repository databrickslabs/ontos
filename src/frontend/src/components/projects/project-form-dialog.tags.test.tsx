/**
 * Editing a project keeps its tags (#1420): the dialog used to map loaded tags to
 * `tag.name`, which AssignedTag doesn't have, and saved '' for each of them.
 *
 * The Radix Select and the TagSelector hang in jsdom (see project-form-dialog.test.tsx),
 * so both are stubbed: the stub selector shows the selected tags by FQN.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: mockPost, put: mockPut, delete: vi.fn(), loading: false }),
}));

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en', changeLanguage: vi.fn() } }),
}));

vi.mock('@/components/ui/tag-selector', async () => {
  const actual = await vi.importActual<typeof import('@/components/ui/tag-selector')>('@/components/ui/tag-selector');
  return {
    ...actual,
    default: ({ value }: { value: { fqn: string }[] }) => (
      <ul aria-label="selected-tags">
        {value.map(tag => (
          <li key={tag.fqn}>{tag.fqn}</li>
        ))}
      </ul>
    ),
  };
});

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
  SelectContent: () => null,
  SelectItem: () => null,
}));

import { ProjectFormDialog } from './project-form-dialog';

const project = {
  id: 'p-1',
  name: 'customer-360',
  title: 'Customer 360',
  description: 'Customer data platform',
  project_type: 'TEAM',
  teams: [],
  tags: [
    {
      tag_id: 'tag-1',
      tag_name: 'classification',
      namespace_id: 'ns-1',
      namespace_name: 'default',
      status: 'active',
      fully_qualified_name: 'default/classification',
      assigned_value: 'confidential',
      assigned_at: '2026-01-01T00:00:00Z',
    },
    {
      tag_id: 'tag-2',
      tag_name: 'pii',
      namespace_id: 'ns-1',
      namespace_name: 'default',
      status: 'active',
      fully_qualified_name: 'default/pii',
      assigned_value: null,
      assigned_at: '2026-01-01T00:00:00Z',
    },
  ],
} as any;

beforeEach(() => {
  mockGet.mockReset().mockResolvedValue({ data: [] });
  mockPost.mockReset().mockResolvedValue({ data: {} });
  mockPut.mockReset().mockResolvedValue({ data: project });
});

describe('ProjectFormDialog tags', () => {
  it('shows the assigned tags by FQN', async () => {
    render(<ProjectFormDialog isOpen onOpenChange={vi.fn()} project={project} onSubmitSuccess={vi.fn()} />);

    const list = await screen.findByLabelText('selected-tags');
    expect(list).toHaveTextContent('default/classification');
    expect(list).toHaveTextContent('default/pii');
  });

  // Untouched values are left out, so the backend keeps them (#1420).
  it('saves the assigned tags by FQN', async () => {
    render(<ProjectFormDialog isOpen onOpenChange={vi.fn()} project={project} onSubmitSuccess={vi.fn()} />);

    await userEvent.click(await screen.findByRole('button', { name: 'projects:form.buttons.update' }));

    await waitFor(() => expect(mockPut).toHaveBeenCalled());
    const [url, body] = mockPut.mock.calls[0];
    expect(url).toBe('/api/projects/p-1');
    expect(body.tags).toEqual([{ tag_fqn: 'default/classification' }, { tag_fqn: 'default/pii' }]);
  });
});
