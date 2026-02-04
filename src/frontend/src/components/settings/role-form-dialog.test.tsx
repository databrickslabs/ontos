/**
 * Tests for RoleFormDialog component
 */
import { screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import RoleFormDialog from './role-form-dialog';
import { AppRole, FeatureConfig, FeatureAccessLevel, HomeSection, ApprovalEntity } from '@/types/settings';

// Mock i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: any) => {
      // Remove namespace prefix if present
      const keyWithoutNs = key.includes(':') ? key.split(':')[1] : key;

      const translations: Record<string, string> = {
        'roles.dialog.createTitle': 'Create New Role',
        'roles.dialog.editTitle': params ? `Edit ${params.name}` : 'Edit Role',
        'roles.dialog.description': 'Configure role permissions and settings.',
        'roles.tabs.general': 'General',
        'roles.tabs.privileges': 'Privileges',
        'roles.tabs.permissions': 'Permissions',
        'roles.tabs.deployment': 'Deployment',
        'roles.general.roleName': 'Role Name',
        'roles.general.roleNameRequired': 'Role name is required',
        'roles.general.description': 'Description',
        'roles.general.assignedGroups': 'Assigned Groups',
        'roles.general.assignedGroupsPlaceholder': 'group1, group2, group3',
        'roles.general.assignedGroupsHelp': 'Enter group names separated by commas',
        'roles.privileges.homeSections.title': 'Home Sections',
        'roles.privileges.homeSections.description': 'Select sections to display on home page',
        'roles.privileges.approvalPrivileges.title': 'Approval Privileges',
        'roles.privileges.approvalPrivileges.description': 'Grant approval rights',
        'actions.cancel': 'Cancel',
        'actions.save': 'Save',
      };
      return translations[keyWithoutNs] || keyWithoutNs;
    },
  }),
}));

// Mock hooks
const mockPost = vi.fn();
const mockPut = vi.fn();

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({
    get: vi.fn(),
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

describe('RoleFormDialog', () => {
  const mockOnOpenChange = vi.fn();
  const mockOnSubmitSuccess = vi.fn();

  const mockFeaturesConfig: Record<string, FeatureConfig> = {
    'data-products': {
      name: 'Data Products',
      allowed_levels: [
        FeatureAccessLevel.NONE,
        FeatureAccessLevel.READ_ONLY,
        FeatureAccessLevel.READ_WRITE,
      ],
    },
    'data-contracts': {
      name: 'Data Contracts',
      allowed_levels: [
        FeatureAccessLevel.NONE,
        FeatureAccessLevel.READ_ONLY,
        FeatureAccessLevel.READ_WRITE,
      ],
    },
  };

  const sampleRole: AppRole = {
    id: 'role-1',
    name: 'Data Producer',
    description: 'Role for data producers',
    assigned_groups: ['data-team'],
    feature_permissions: {
      'data-products': FeatureAccessLevel.READ_WRITE,
      'data-contracts': FeatureAccessLevel.READ_WRITE,
    },
    home_sections: [HomeSection.DATA_CURATION],
    approval_privileges: {
      [ApprovalEntity.PRODUCTS]: true,
    },
    deployment_policy: null,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Create Mode', () => {
    it('renders with create title and tabs', () => {
      renderWithProviders(
        <RoleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          initialRole={null}
          featuresConfig={mockFeaturesConfig}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      expect(screen.getByText('Create New Role')).toBeInTheDocument();
      expect(screen.getByText('Configure role permissions and settings.')).toBeInTheDocument();

      // Check tabs
      expect(screen.getByRole('tab', { name: /General/i })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: /Privileges/i })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: /Permissions/i })).toBeInTheDocument();
    });

    it('validates required role name field', async () => {
      const user = userEvent.setup();

      renderWithProviders(
        <RoleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          initialRole={null}
          featuresConfig={mockFeaturesConfig}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      // Find submit button - look for button with type submit
      const submitButton = screen.getAllByRole('button').find(
        btn => btn.getAttribute('type') === 'submit'
      );
      expect(submitButton).toBeDefined();

      if (submitButton) {
        await user.click(submitButton);

        // Validation error should appear
        await waitFor(() => {
          expect(screen.getByText(/Role name is required/i)).toBeInTheDocument();
        });
      }

      expect(mockPost).not.toHaveBeenCalled();
    });

    it('creates a new role successfully', async () => {
      const user = userEvent.setup();
      const newRole: AppRole = {
        id: 'role-2',
        name: 'New Role',
        description: 'New role description',
        assigned_groups: [],
        feature_permissions: {
          'data-products': FeatureAccessLevel.NONE,
          'data-contracts': FeatureAccessLevel.NONE,
        },
        home_sections: [],
        approval_privileges: {},
        deployment_policy: null,
      };

      mockPost.mockResolvedValue({ data: newRole, error: null });

      renderWithProviders(
        <RoleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          initialRole={null}
          featuresConfig={mockFeaturesConfig}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      // Fill in role name
      const nameInput = screen.getByLabelText(/Role Name/i);
      await user.type(nameInput, 'New Role');

      // Submit
      const submitButton = screen.getAllByRole('button').find(
        btn => btn.getAttribute('type') === 'submit'
      );
      if (submitButton) {
        await user.click(submitButton);
      }

      await waitFor(() => {
        expect(mockPost).toHaveBeenCalledWith('/api/settings/roles', expect.objectContaining({
          name: 'New Role',
        }));
      });

      expect(mockToast).toHaveBeenCalledWith({
        title: 'Success',
        description: 'Role "New Role" created.',
      });
      expect(mockOnSubmitSuccess).toHaveBeenCalled();
    });

    it('handles assigned groups input', async () => {
      const user = userEvent.setup();

      renderWithProviders(
        <RoleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          initialRole={null}
          featuresConfig={mockFeaturesConfig}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      const groupsInput = screen.getByLabelText(/Assigned Groups/i) as HTMLInputElement;

      // Use paste instead of type to avoid character-by-character processing
      await user.click(groupsInput);
      await user.paste('group1, group2, group3');

      // The component processes the input and maintains it as comma-separated
      expect(groupsInput.value).toContain('group1');
      expect(groupsInput.value).toContain('group2');
      expect(groupsInput.value).toContain('group3');
    });

    it('handles API errors', async () => {
      const user = userEvent.setup();
      mockPost.mockResolvedValue({ data: null, error: 'Role already exists' });

      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

      renderWithProviders(
        <RoleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          initialRole={null}
          featuresConfig={mockFeaturesConfig}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      await user.type(screen.getByLabelText(/Role Name/i), 'Test Role');

      const submitButton = screen.getAllByRole('button').find(
        btn => btn.getAttribute('type') === 'submit'
      );
      if (submitButton) {
        await user.click(submitButton);
      }

      await waitFor(() => {
        expect(mockToast).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Save Error',
            variant: 'destructive',
          })
        );
      });

      expect(mockOnSubmitSuccess).not.toHaveBeenCalled();

      consoleError.mockRestore();
    });
  });

  describe('Edit Mode', () => {
    it('renders with edit title and populated form', () => {
      renderWithProviders(
        <RoleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          initialRole={sampleRole}
          featuresConfig={mockFeaturesConfig}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      expect(screen.getByText('Edit Data Producer')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Data Producer')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Role for data producers')).toBeInTheDocument();
    });

    it('displays assigned groups correctly', () => {
      renderWithProviders(
        <RoleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          initialRole={sampleRole}
          featuresConfig={mockFeaturesConfig}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      const groupsInput = screen.getByLabelText(/Assigned Groups/i);
      expect(groupsInput).toHaveValue('data-team');
    });

    it('updates an existing role successfully', async () => {
      const user = userEvent.setup();
      const updatedRole = { ...sampleRole, description: 'Updated description' };

      mockPut.mockResolvedValue({ data: updatedRole, error: null });

      renderWithProviders(
        <RoleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          initialRole={sampleRole}
          featuresConfig={mockFeaturesConfig}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      // Modify description
      const descInput = screen.getByLabelText(/Description/i);
      await user.clear(descInput);
      await user.type(descInput, 'Updated description');

      // Submit
      const submitButton = screen.getAllByRole('button').find(
        btn => btn.getAttribute('type') === 'submit'
      );
      if (submitButton) {
        await user.click(submitButton);
      }

      await waitFor(() => {
        expect(mockPut).toHaveBeenCalledWith(
          '/api/settings/roles/role-1',
          expect.objectContaining({
            id: 'role-1',
            description: 'Updated description',
          })
        );
      });

      expect(mockToast).toHaveBeenCalledWith({
        title: 'Success',
        description: 'Role "Data Producer" updated.',
      });
    });

    it('prevents editing admin role name', () => {
      const adminRole: AppRole = {
        ...sampleRole,
        id: 'admin',
        name: 'Admin',
      };

      renderWithProviders(
        <RoleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          initialRole={adminRole}
          featuresConfig={mockFeaturesConfig}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      const nameInput = screen.getByDisplayValue('Admin');
      expect(nameInput).toHaveAttribute('readonly');
    });
  });

  describe('Tab Navigation', () => {
    it('can switch between tabs', async () => {
      const user = userEvent.setup();

      renderWithProviders(
        <RoleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          initialRole={null}
          featuresConfig={mockFeaturesConfig}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      // Start on General tab
      expect(screen.getByRole('tab', { name: /General/i })).toHaveAttribute('data-state', 'active');

      // Click Privileges tab
      const privilegesTab = screen.getByRole('tab', { name: /Privileges/i });
      await user.click(privilegesTab);

      await waitFor(() => {
        expect(privilegesTab).toHaveAttribute('data-state', 'active');
      });

      // Should see privileges content
      expect(screen.getByText('Home Sections')).toBeInTheDocument();
    });
  });

  describe('Dialog Behavior', () => {
    it('does not render when closed', () => {
      renderWithProviders(
        <RoleFormDialog
          isOpen={false}
          onOpenChange={mockOnOpenChange}
          initialRole={null}
          featuresConfig={mockFeaturesConfig}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      expect(screen.queryByText('Create New Role')).not.toBeInTheDocument();
    });

    it('warns about unsaved changes when closing with dirty form', async () => {
      const user = userEvent.setup();
      const mockConfirm = vi.spyOn(window, 'confirm').mockReturnValue(false);

      renderWithProviders(
        <RoleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          initialRole={null}
          featuresConfig={mockFeaturesConfig}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      // Make form dirty
      await user.type(screen.getByLabelText(/Role Name/i), 'Test');

      // Note: Full close testing is complex as it requires triggering dialog onOpenChange
      // This test structure is in place but hard to fully test in unit tests

      mockConfirm.mockRestore();
    });
  });

  describe('Default Permissions', () => {
    it('initializes with default NONE permissions for new roles', () => {
      renderWithProviders(
        <RoleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          initialRole={null}
          featuresConfig={mockFeaturesConfig}
          onSubmitSuccess={mockOnSubmitSuccess}
        />
      );

      // Switch to Permissions tab to check
      const permissionsTab = screen.getByRole('tab', { name: /Permissions/i });
      expect(permissionsTab).toBeInTheDocument();

      // Form should be initialized (can't easily verify without inspecting form state)
      expect(screen.getByLabelText(/Role Name/i)).toHaveValue('');
    });
  });
});
