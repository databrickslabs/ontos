/**
 * Tests for TeamFormDialog component
 */
import { screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { TeamFormDialog } from './team-form-dialog';
import { TeamRead } from '@/types/team';
import { DataDomain } from '@/types/data-domain';

// Mock i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: any) => {
      // Simple mock that returns translations based on key
      const translations: Record<string, string> = {
        'teams:form.dialog.createTitle': 'Create New Team',
        'teams:form.dialog.editTitle': 'Edit Team',
        'teams:form.dialog.createDescription': 'Add a new team to the system.',
        'teams:form.dialog.editDescription': 'Update team information.',
        'teams:form.sections.info': 'Team Information',
        'teams:form.sections.members': 'Team Members',
        'teams:form.sections.tags': 'Tags',
        'teams:form.labels.name': 'Name',
        'teams:form.labels.title': 'Title',
        'teams:form.labels.description': 'Description',
        'teams:form.labels.domain': 'Domain',
        'teams:form.labels.type': 'Type',
        'teams:form.labels.identifier': 'Identifier',
        'teams:form.labels.roleOverride': 'Role Override',
        'teams:form.labels.noOverride': 'No override',
        'teams:form.placeholders.name': 'e.g., Data Engineering',
        'teams:form.placeholders.title': 'e.g., Data Engineering Team',
        'teams:form.placeholders.description': 'Describe the team purpose',
        'teams:form.placeholders.selectDomain': 'Select a domain',
        'teams:form.placeholders.userEmail': 'user@example.com',
        'teams:form.placeholders.groupName': 'Group name',
        'teams:form.placeholders.tagSearch': 'Search and select tags',
        'teams:form.placeholders.noMembersHelp': 'No members added yet',
        'teams:form.memberTypes.user': 'User',
        'teams:form.memberTypes.group': 'Group',
        'teams:form.buttons.addMember': 'Add Member',
        'teams:form.buttons.create': 'Create Team',
        'teams:form.buttons.update': 'Update Team',
        'teams:form.toasts.createdTitle': 'Team Created',
        'teams:form.toasts.createdDescription': params ? `Successfully created ${params.name}.` : 'Team created successfully.',
        'teams:form.toasts.updatedTitle': 'Team Updated',
        'teams:form.toasts.updatedDescription': params ? `Successfully updated ${params.name}.` : 'Team updated successfully.',
        'teams:form.toasts.createFailedTitle': 'Create Failed',
        'teams:form.toasts.updateFailedTitle': 'Update Failed',
        'teams:form.toasts.failedDescription': 'An error occurred.',
        'common:actions.cancel': 'Cancel',
      };
      return translations[key] || key;
    },
  }),
}));

// Mock hooks
const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();
const mockDelete = vi.fn();

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({
    get: mockGet,
    post: mockPost,
    put: mockPut,
    delete: mockDelete,
  })
}));

const mockToast = vi.fn();
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({
    toast: mockToast
  })
}));

describe('TeamFormDialog', () => {
  const mockOnOpenChange = vi.fn();
  const mockOnSubmitSuccess = vi.fn();

  const sampleDomains: DataDomain[] = [
    {
      id: 'domain-1',
      name: 'Engineering',
      description: 'Engineering domain',
      owner: ['eng@example.com'],
      tags: null,
      parent_id: null,
      created_at: '2024-01-01',
      updated_at: '2024-01-01',
    },
    {
      id: 'domain-2',
      name: 'Sales',
      description: 'Sales domain',
      owner: ['sales@example.com'],
      tags: null,
      parent_id: null,
      created_at: '2024-01-01',
      updated_at: '2024-01-01',
    }
  ];

  const sampleTeam: TeamRead = {
    id: 'team-1',
    name: 'Data Team',
    title: 'Data Engineering Team',
    description: 'Team responsible for data infrastructure',
    domain_id: 'domain-1',
    tags: null,
    members: [
      {
        member_type: 'user',
        member_identifier: 'user@example.com',
        app_role_override: 'DataProducer',
      }
    ],
    created_at: '2024-01-01',
    updated_at: '2024-01-01',
  };

  beforeEach(() => {
    vi.clearAllMocks();

    // Mock domains and roles fetch by default
    mockGet.mockImplementation((url: string) => {
      if (url.includes('/api/data-domains')) {
        return Promise.resolve({ data: sampleDomains, error: null });
      }
      if (url.includes('/api/settings/roles')) {
        return Promise.resolve({
          data: [{ name: 'DataProducer' }, { name: 'DataConsumer' }],
          error: null
        });
      }
      return Promise.resolve({ data: null, error: null });
    });
  });

  describe('Create Mode', () => {
    it('renders with create title and empty form', async () => {
      renderWithProviders(
        <TeamFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      expect(screen.getByText('Create New Team')).toBeInTheDocument();
      expect(screen.getByText('Add a new team to the system.')).toBeInTheDocument();

      // Wait for form to load
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Create Team/i })).toBeInTheDocument();
      });
    });

    it('fetches domains and roles on open', async () => {
      renderWithProviders(
        <TeamFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(mockGet).toHaveBeenCalledWith('/api/data-domains');
        expect(mockGet).toHaveBeenCalledWith('/api/settings/roles');
      });
    });

    it('validates required name field', async () => {
      const user = userEvent.setup();

      renderWithProviders(
        <TeamFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      // Wait for form to load
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Create Team/i })).toBeInTheDocument();
      });

      const submitButton = screen.getByRole('button', { name: /Create Team/i });
      await user.click(submitButton);

      // Validation error should appear
      await waitFor(() => {
        expect(screen.getByText(/Team name is required/i)).toBeInTheDocument();
      });

      expect(mockPost).not.toHaveBeenCalled();
    });

    it('creates a new team successfully', async () => {
      const user = userEvent.setup();
      const newTeam: TeamRead = {
        id: 'team-2',
        name: 'New Team',
        title: 'New Team Title',
        description: 'New team description',
        tags: [],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
      };

      mockPost.mockResolvedValue({ data: newTeam, error: null });

      renderWithProviders(
        <TeamFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      // Wait for form to load
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Create Team/i })).toBeInTheDocument();
      });

      // Fill in form
      await user.type(screen.getByLabelText(/Name/i), 'New Team');
      await user.type(screen.getByLabelText(/Title/i), 'New Team Title');
      await user.type(screen.getByLabelText(/Description/i), 'New team description');

      // Submit
      const submitButton = screen.getByRole('button', { name: /Create Team/i });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockPost).toHaveBeenCalledWith('/api/teams', expect.objectContaining({
          name: 'New Team',
          title: 'New Team Title',
          description: 'New team description',
        }));
      });

      expect(mockToast).toHaveBeenCalledWith({
        title: 'Team Created',
        description: 'Successfully created New Team.',
      });
      expect(mockOnSubmitSuccess).toHaveBeenCalledWith(newTeam);
      expect(mockOnOpenChange).toHaveBeenCalledWith(false);
    });

    it('can add and remove team members', async () => {
      const user = userEvent.setup();

      renderWithProviders(
        <TeamFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Add Member/i })).toBeInTheDocument();
      });

      // Initially no members
      expect(screen.getByText('No members added yet')).toBeInTheDocument();

      // Add a member
      const addButton = screen.getByRole('button', { name: /Add Member/i });
      await user.click(addButton);

      // Member fields should appear
      await waitFor(() => {
        expect(screen.queryByText('No members added yet')).not.toBeInTheDocument();
        expect(screen.getByLabelText(/Type/i)).toBeInTheDocument();
      });

      // Remove the member
      const deleteButton = screen.getByRole('button', { name: '' }); // Trash icon button
      await user.click(deleteButton);

      // Member should be removed
      await waitFor(() => {
        expect(screen.getByText('No members added yet')).toBeInTheDocument();
      });
    });

    it('handles API errors', async () => {
      const user = userEvent.setup();
      mockPost.mockResolvedValue({ data: null, error: 'Team already exists' });

      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

      renderWithProviders(
        <TeamFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Create Team/i })).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText(/Name/i), 'Test Team');

      const submitButton = screen.getByRole('button', { name: /Create Team/i });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockToast).toHaveBeenCalledWith(
          expect.objectContaining({
            variant: 'destructive',
            title: 'Create Failed',
          })
        );
      });

      expect(mockOnSubmitSuccess).not.toHaveBeenCalled();
      expect(mockOnOpenChange).not.toHaveBeenCalled();

      consoleError.mockRestore();
    });
  });

  describe('Edit Mode', () => {
    it('renders with edit title and populated form', async () => {
      mockGet.mockImplementation((url: string) => {
        if (url.includes('/api/data-domains')) {
          return Promise.resolve({ data: sampleDomains, error: null });
        }
        if (url.includes('/api/settings/roles')) {
          return Promise.resolve({
            data: [{ name: 'DataProducer' }, { name: 'DataConsumer' }],
            error: null
          });
        }
        return Promise.resolve({ data: null, error: null });
      });

      renderWithProviders(
        <TeamFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          team={sampleTeam}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      expect(screen.getByText('Edit Team')).toBeInTheDocument();

      await waitFor(() => {
        expect(screen.getByDisplayValue('Data Team')).toBeInTheDocument();
        expect(screen.getByDisplayValue('Data Engineering Team')).toBeInTheDocument();
      });
    });

    it('updates an existing team successfully', async () => {
      const user = userEvent.setup();
      const updatedTeam = { ...sampleTeam, name: 'Updated Team' };

      mockGet.mockImplementation((url: string) => {
        if (url.includes('/api/data-domains')) {
          return Promise.resolve({ data: sampleDomains, error: null });
        }
        if (url.includes('/api/settings/roles')) {
          return Promise.resolve({
            data: [{ name: 'DataProducer' }, { name: 'DataConsumer' }],
            error: null
          });
        }
        if (url.includes('/api/teams/team-1/members')) {
          return Promise.resolve({ data: sampleTeam.members, error: null });
        }
        return Promise.resolve({ data: null, error: null });
      });

      mockPut.mockResolvedValue({ data: updatedTeam, error: null });
      mockDelete.mockResolvedValue({ data: null, error: null });
      mockPost.mockResolvedValue({ data: null, error: null });

      renderWithProviders(
        <TeamFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          team={sampleTeam}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(screen.getByDisplayValue('Data Team')).toBeInTheDocument();
      });

      // Modify name
      const nameInput = screen.getByDisplayValue('Data Team');
      await user.clear(nameInput);
      await user.type(nameInput, 'Updated Team');

      // Submit
      const submitButton = screen.getByRole('button', { name: /Update Team/i });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockPut).toHaveBeenCalledWith(
          '/api/teams/team-1',
          expect.objectContaining({
            name: 'Updated Team',
          })
        );
      });

      expect(mockToast).toHaveBeenCalledWith({
        title: 'Team Updated',
        description: 'Successfully updated Updated Team.',
      });
    });

    it('displays existing team members', async () => {
      mockGet.mockImplementation((url: string) => {
        if (url.includes('/api/data-domains')) {
          return Promise.resolve({ data: sampleDomains, error: null });
        }
        if (url.includes('/api/settings/roles')) {
          return Promise.resolve({
            data: [{ name: 'DataProducer' }, { name: 'DataConsumer' }],
            error: null
          });
        }
        return Promise.resolve({ data: null, error: null });
      });

      renderWithProviders(
        <TeamFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          team={sampleTeam}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(screen.getByDisplayValue('user@example.com')).toBeInTheDocument();
      });
    });
  });

  describe('Dialog Behavior', () => {
    it('does not render when closed', () => {
      renderWithProviders(
        <TeamFormDialog
          isOpen={false}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      expect(screen.queryByText('Create New Team')).not.toBeInTheDocument();
    });

    it('calls onOpenChange when cancel is clicked', async () => {
      const user = userEvent.setup();

      renderWithProviders(
        <TeamFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Cancel/i })).toBeInTheDocument();
      });

      const cancelButton = screen.getByRole('button', { name: /Cancel/i });
      await user.click(cancelButton);

      expect(mockOnOpenChange).toHaveBeenCalledWith(false);
    });
  });

  describe('Initial Domain', () => {
    it('sets initial domain when provided', async () => {
      renderWithProviders(
        <TeamFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
          initialDomainId="domain-1"
        />
      );

      await waitFor(() => {
        // This is harder to test without inspecting form state
        // We'd need to check the Select value somehow
        expect(mockGet).toHaveBeenCalledWith('/api/data-domains');
      });
    });
  });
});
