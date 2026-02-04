/**
 * Tests for ProjectFormDialog component
 */
import { screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { ProjectFormDialog } from './project-form-dialog';
import { ProjectRead } from '@/types/project';
import { TeamSummary } from '@/types/team';

// Mock i18n
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: any) => {
      const translations: Record<string, string> = {
        'projects:form.dialog.createTitle': 'Create Project',
        'projects:form.dialog.editTitle': 'Edit Project',
        'projects:form.dialog.createDescription': 'Add a new project',
        'projects:form.dialog.editDescription': 'Edit existing project',
        'projects:form.labels.name': 'Name',
        'projects:form.labels.title': 'Title',
        'projects:form.labels.description': 'Description',
        'projects:form.labels.projectType': 'Project Type',
        'projects:form.labels.assignTeams': 'Assign Teams',
        'projects:form.labels.assignedTeams': 'Assigned Teams',
        'projects:form.placeholders.name': 'Enter project name',
        'projects:form.placeholders.title': 'Enter project title',
        'projects:form.placeholders.description': 'Enter description',
        'projects:form.placeholders.selectProjectType': 'Select project type',
        'projects:form.placeholders.assignTeams': 'Select teams',
        'projects:form.placeholders.noTeamsAvailable': 'No teams available',
        'projects:form.placeholders.allTeamsAssigned': 'All teams assigned',
        'projects:form.placeholders.noTagsHelp': 'No tags yet',
        'projects:form.placeholders.enterTag': 'Enter tag',
        'projects:form.types.PERSONAL': 'Personal',
        'projects:form.types.TEAM': 'Team',
        'projects:form.sections.info': 'Project Information',
        'projects:form.sections.teams': 'Team Assignments',
        'projects:form.sections.tags': 'Tags',
        'projects:form.buttons.create': 'Create',
        'projects:form.buttons.update': 'Update',
        'projects:form.buttons.addTag': 'Add Tag',
        'projects:form.toasts.createdTitle': 'Project Created',
        'projects:form.toasts.updatedTitle': 'Project Updated',
        'projects:form.toasts.createdDescription': `Created project ${params?.name || ''}`,
        'projects:form.toasts.updatedDescription': `Updated project ${params?.name || ''}`,
        'projects:form.toasts.createFailedTitle': 'Creation Failed',
        'projects:form.toasts.updateFailedTitle': 'Update Failed',
        'projects:form.toasts.failedDescription': 'Operation failed',
        'common:actions.cancel': 'Cancel',
      };
      return translations[key] || key;
    }
  })
}));

// Mock hooks
const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({
    get: mockGet,
    post: mockPost,
    put: mockPut,
    delete: vi.fn(),
  })
}));

const mockToast = vi.fn();
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({
    toast: mockToast
  })
}));

describe('ProjectFormDialog', () => {
  const mockOnOpenChange = vi.fn();
  const mockOnSubmitSuccess = vi.fn();

  const sampleTeams: TeamSummary[] = [
    {
      id: 'team-1',
      name: 'Engineering',
      title: 'Engineering Team',
      member_count: 5,
    },
    {
      id: 'team-2',
      name: 'Data Science',
      title: 'Data Science Team',
      member_count: 3,
    }
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue({ data: sampleTeams, error: null });
  });

  describe('Create Mode', () => {
    it('renders with create title and empty form', async () => {
      renderWithProviders(
        <ProjectFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      expect(screen.getByText('Create Project')).toBeInTheDocument();
      expect(screen.getByText('Add a new project')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Create/i })).toBeInTheDocument();

      // Wait for teams to be fetched
      await waitFor(() => {
        expect(mockGet).toHaveBeenCalledWith('/api/teams');
      });
    });

    it('creates a new project successfully', async () => {
      const user = userEvent.setup();
      const newProject: ProjectRead = {
        id: 'project-1',
        name: 'New Project',
        title: 'Test Project',
        description: 'Test description',
        tags: null,
        teams: [],
        project_type: 'TEAM',
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
        created_by: 'test-user',
        updated_by: 'test-user',
      };

      mockPost.mockResolvedValue({ data: newProject, error: null });

      renderWithProviders(
        <ProjectFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      // Wait for form to be ready
      await waitFor(() => {
        expect(screen.getByPlaceholderText('Enter project name')).toBeInTheDocument();
      });

      // Fill in form fields
      await user.type(screen.getByPlaceholderText('Enter project name'), 'New Project');
      await user.type(screen.getByPlaceholderText('Enter project title'), 'Test Project');
      await user.type(screen.getByPlaceholderText('Enter description'), 'Test description');

      // Submit form
      const submitButton = screen.getByRole('button', { name: /Create/i });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockPost).toHaveBeenCalledWith('/api/projects', expect.objectContaining({
          name: 'New Project',
          title: 'Test Project',
          description: 'Test description',
        }));
      });

      expect(mockToast).toHaveBeenCalledWith({
        title: 'Project Created',
        description: 'Created project New Project'
      });
      expect(mockOnSubmitSuccess).toHaveBeenCalledWith(newProject);
      expect(mockOnOpenChange).toHaveBeenCalledWith(false);
    });

    it('validates required name field', async () => {
      const user = userEvent.setup();

      renderWithProviders(
        <ProjectFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(screen.getByPlaceholderText('Enter project name')).toBeInTheDocument();
      });

      const submitButton = screen.getByRole('button', { name: /Create/i });
      await user.click(submitButton);

      // Check that API was NOT called
      await new Promise(resolve => setTimeout(resolve, 200));
      expect(mockPost).not.toHaveBeenCalled();
    });

    it('handles API errors', async () => {
      const user = userEvent.setup();
      mockPost.mockResolvedValue({ data: null, error: 'Project already exists' });

      renderWithProviders(
        <ProjectFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(screen.getByPlaceholderText('Enter project name')).toBeInTheDocument();
      });

      await user.type(screen.getByPlaceholderText('Enter project name'), 'Test Project');

      const submitButton = screen.getByRole('button', { name: /Create/i });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockToast).toHaveBeenCalledWith({
          variant: 'destructive',
          title: 'Creation Failed',
          description: 'Project already exists'
        });
      });

      expect(mockOnSubmitSuccess).not.toHaveBeenCalled();
      expect(mockOnOpenChange).not.toHaveBeenCalled();
    });
  });

  describe('Edit Mode', () => {
    const existingProject: ProjectRead = {
      id: 'project-1',
      name: 'Existing Project',
      title: 'Existing Title',
      description: 'Existing description',
      tags: null,
      teams: [{ id: 'team-1', name: 'Engineering', title: 'Engineering Team', member_count: 5 }],
      project_type: 'TEAM',
      created_at: '2024-01-01',
      updated_at: '2024-01-01',
      created_by: 'test-user',
      updated_by: 'test-user',
    };

    it('renders with edit title and pre-filled form', async () => {
      renderWithProviders(
        <ProjectFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
          project={existingProject}
        />
      );

      expect(screen.getByText('Edit Project')).toBeInTheDocument();
      expect(screen.getByText('Edit existing project')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Update/i })).toBeInTheDocument();

      await waitFor(() => {
        expect(screen.getByDisplayValue('Existing Project')).toBeInTheDocument();
        expect(screen.getByDisplayValue('Existing Title')).toBeInTheDocument();
        expect(screen.getByDisplayValue('Existing description')).toBeInTheDocument();
      });
    });

    it('updates an existing project successfully', async () => {
      const user = userEvent.setup();
      const updatedProject = { ...existingProject, name: 'Updated Project' };
      mockPut.mockResolvedValue({ data: updatedProject, error: null });

      renderWithProviders(
        <ProjectFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
          project={existingProject}
        />
      );

      await waitFor(() => {
        expect(screen.getByDisplayValue('Existing Project')).toBeInTheDocument();
      });

      const nameInput = screen.getByDisplayValue('Existing Project');
      await user.clear(nameInput);
      await user.type(nameInput, 'Updated Project');

      const submitButton = screen.getByRole('button', { name: /Update/i });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockPut).toHaveBeenCalledWith(`/api/projects/${existingProject.id}`, expect.objectContaining({
          name: 'Updated Project',
        }));
      });

      expect(mockToast).toHaveBeenCalledWith({
        title: 'Project Updated',
        description: 'Updated project Updated Project'
      });
      expect(mockOnSubmitSuccess).toHaveBeenCalledWith(updatedProject);
    });

    it('displays existing tags', async () => {
      renderWithProviders(
        <ProjectFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
          project={existingProject}
        />
      );

      await waitFor(() => {
        expect(screen.getByText('tag1')).toBeInTheDocument();
        expect(screen.getByText('tag2')).toBeInTheDocument();
      });
    });
  });

  describe('Team Management', () => {
    it('displays available teams', async () => {
      renderWithProviders(
        <ProjectFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(mockGet).toHaveBeenCalledWith('/api/teams');
      });
    });

    it('handles empty teams list', async () => {
      mockGet.mockResolvedValue({ data: [], error: null });

      renderWithProviders(
        <ProjectFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(mockGet).toHaveBeenCalledWith('/api/teams');
      });
    });

    it('handles team fetch errors gracefully', async () => {
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
      mockGet.mockRejectedValue(new Error('Failed to fetch teams'));

      renderWithProviders(
        <ProjectFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(mockGet).toHaveBeenCalledWith('/api/teams');
      });

      consoleError.mockRestore();
    });
  });

  describe('Tag Management', () => {
    it('allows adding tags', async () => {
      const user = userEvent.setup();

      renderWithProviders(
        <ProjectFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(screen.getByPlaceholderText('Enter project name')).toBeInTheDocument();
      });

      // Click "Add Tag" button
      const addTagButton = screen.getByRole('button', { name: /Add Tag/i });
      await user.click(addTagButton);

      // An input field should appear for the new tag
      await waitFor(() => {
        const tagInputs = screen.getAllByPlaceholderText('Enter tag');
        expect(tagInputs.length).toBeGreaterThan(0);
      });
    });

    it('filters out empty tags on submission', async () => {
      const user = userEvent.setup();
      mockPost.mockResolvedValue({
        data: { id: 'project-1', name: 'Test', tags: [] },
        error: null
      });

      renderWithProviders(
        <ProjectFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(screen.getByPlaceholderText('Enter project name')).toBeInTheDocument();
      });

      await user.type(screen.getByPlaceholderText('Enter project name'), 'Test Project');

      // Add a tag button, but don't fill it
      const addTagButton = screen.getByRole('button', { name: /Add Tag/i });
      await user.click(addTagButton);

      const submitButton = screen.getByRole('button', { name: /Create/i });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockPost).toHaveBeenCalledWith('/api/projects', expect.objectContaining({
          tags: [], // Empty tags should be filtered out
        }));
      });
    });
  });

  describe('Loading States', () => {
    it('disables buttons while submitting', async () => {
      const user = userEvent.setup();
      mockPost.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve({ data: {}, error: null }), 100)));

      renderWithProviders(
        <ProjectFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await waitFor(() => {
        expect(screen.getByPlaceholderText('Enter project name')).toBeInTheDocument();
      });

      await user.type(screen.getByPlaceholderText('Enter project name'), 'Test');

      const submitButton = screen.getByRole('button', { name: /Create/i });
      await user.click(submitButton);

      // Button should be disabled while submitting
      await waitFor(() => {
        expect(submitButton).toBeDisabled();
      });
    });
  });
});
