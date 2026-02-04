/**
 * Tests for QualityRuleFormDialog component
 */
import { screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import QualityRuleFormDialog from './quality-rule-form-dialog';
import type { QualityRule } from '@/types/data-contract';

// Mock hooks
const mockToast = vi.fn();
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({
    toast: mockToast
  })
}));

describe('QualityRuleFormDialog', () => {
  const mockOnOpenChange = vi.fn();
  const mockOnSubmit = vi.fn();

  const sampleRule: QualityRule = {
    name: 'Check for nulls',
    description: 'Validates no null values in critical fields',
    level: 'property',
    dimension: 'completeness',
    businessImpact: 'operational',
    severity: 'error',
    type: 'sql',
    query: 'SELECT COUNT(*) FROM table WHERE field IS NULL',
    rule: 'COUNT(*) = 0',
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Create Mode', () => {
    it('renders with create title and empty form', () => {
      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
        />
      );

      expect(screen.getByText('Add Quality Rule')).toBeInTheDocument();
      expect(screen.getByText('Define a data quality check for this contract.')).toBeInTheDocument();
    });

    it('shows required field indicator for name', () => {
      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
        />
      );

      const nameLabel = screen.getByText(/Rule Name/);
      expect(nameLabel).toBeInTheDocument();
      // Check for required asterisk
      expect(nameLabel.querySelector('.text-destructive')).toBeInTheDocument();
    });

    it('validates required name field', async () => {
      const user = userEvent.setup();

      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
        />
      );

      // Try to submit without name
      const saveButton = screen.getByRole('button', { name: /Add Rule/i });
      await user.click(saveButton);

      // Should show validation error
      await waitFor(() => {
        expect(mockToast).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Validation Error',
            description: 'Rule name is required',
            variant: 'destructive',
          })
        );
      });

      expect(mockOnSubmit).not.toHaveBeenCalled();
    });

    it('creates a new quality rule successfully', async () => {
      const user = userEvent.setup();
      mockOnSubmit.mockResolvedValue(undefined);

      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
        />
      );

      // Fill in required field
      const nameInput = screen.getByLabelText(/Rule Name/);
      await user.type(nameInput, 'Test Rule');

      // Fill in description
      const descInput = screen.getByLabelText(/Description/i);
      await user.type(descInput, 'Test description');

      // Submit
      const saveButton = screen.getByRole('button', { name: /Add Rule/i });
      await user.click(saveButton);

      await waitFor(() => {
        expect(mockOnSubmit).toHaveBeenCalledWith(
          expect.objectContaining({
            name: 'Test Rule',
            description: 'Test description',
          })
        );
      });

      expect(mockOnOpenChange).toHaveBeenCalledWith(false);
    });

    it('includes default values for selects', async () => {
      const user = userEvent.setup();
      mockOnSubmit.mockResolvedValue(undefined);

      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
        />
      );

      const nameInput = screen.getByLabelText(/Rule Name/);
      await user.type(nameInput, 'Test Rule');

      const saveButton = screen.getByRole('button', { name: /Add Rule/i });
      await user.click(saveButton);

      await waitFor(() => {
        expect(mockOnSubmit).toHaveBeenCalledWith(
          expect.objectContaining({
            name: 'Test Rule',
            level: 'object',
            dimension: 'completeness',
            businessImpact: 'operational',
            severity: 'warning',
            type: 'library',
          })
        );
      });
    });

    it('handles submission errors', async () => {
      const user = userEvent.setup();
      const error = new Error('Submission failed');
      mockOnSubmit.mockRejectedValue(error);

      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
        />
      );

      const nameInput = screen.getByLabelText(/Rule Name/);
      await user.type(nameInput, 'Test Rule');

      const saveButton = screen.getByRole('button', { name: /Add Rule/i });
      await user.click(saveButton);

      await waitFor(() => {
        expect(mockToast).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Error',
            description: 'Submission failed',
            variant: 'destructive',
          })
        );
      });

      // Dialog should stay open on error
      expect(mockOnOpenChange).not.toHaveBeenCalled();
    });
  });

  describe('Edit Mode', () => {
    it('renders with edit title and populated form', () => {
      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
          initial={sampleRule}
        />
      );

      expect(screen.getByText('Edit Quality Rule')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Check for nulls')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Validates no null values in critical fields')).toBeInTheDocument();
    });

    it('populates all fields from initial rule', () => {
      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
          initial={sampleRule}
        />
      );

      expect(screen.getByDisplayValue(sampleRule.name!)).toBeInTheDocument();
      expect(screen.getByDisplayValue(sampleRule.description!)).toBeInTheDocument();
      expect(screen.getByDisplayValue(sampleRule.query!)).toBeInTheDocument();
      expect(screen.getByDisplayValue(sampleRule.rule!)).toBeInTheDocument();
    });

    it('updates an existing quality rule', async () => {
      const user = userEvent.setup();
      mockOnSubmit.mockResolvedValue(undefined);

      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
          initial={sampleRule}
        />
      );

      // Modify name
      const nameInput = screen.getByDisplayValue('Check for nulls');
      await user.clear(nameInput);
      await user.type(nameInput, 'Updated Rule');

      // Submit - in edit mode button is "Save Changes"
      const saveButton = screen.getByRole('button', { name: /Save Changes/i });
      await user.click(saveButton);

      await waitFor(() => {
        expect(mockOnSubmit).toHaveBeenCalledWith(
          expect.objectContaining({
            name: 'Updated Rule',
          })
        );
      });
    });
  });

  describe('Form Fields', () => {
    it('allows filling text fields', async () => {
      const user = userEvent.setup();

      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
        />
      );

      // Fill always-visible fields
      await user.type(screen.getByLabelText(/Rule Name/), 'Test Rule');
      await user.type(screen.getByLabelText(/Description/i), 'Test Description');
      await user.type(screen.getByLabelText(/Rule Expression/i), 'COUNT(*) > 0');

      expect(screen.getByDisplayValue('Test Rule')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Test Description')).toBeInTheDocument();
      expect(screen.getByDisplayValue('COUNT(*) > 0')).toBeInTheDocument();

      // Query field is only shown when type='sql', which is not the default
    });

    it('has select fields for level, dimension, type, severity, and business impact', () => {
      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
        />
      );

      expect(screen.getByLabelText(/Level/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Dimension/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Type/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Severity/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Business Impact/i)).toBeInTheDocument();
    });
  });

  describe('Dialog Behavior', () => {
    it('does not render when closed', () => {
      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={false}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
        />
      );

      expect(screen.queryByText('Add Quality Rule')).not.toBeInTheDocument();
    });

    it('calls onOpenChange when cancel is clicked', async () => {
      const user = userEvent.setup();

      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
        />
      );

      const cancelButton = screen.getByRole('button', { name: /Cancel/i });
      await user.click(cancelButton);

      expect(mockOnOpenChange).toHaveBeenCalledWith(false);
    });

    it('resets form when reopened without initial value', async () => {
      const { rerender } = renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
          initial={sampleRule}
        />
      );

      expect(screen.getByDisplayValue('Check for nulls')).toBeInTheDocument();

      // Close and reopen without initial
      rerender(
        <QualityRuleFormDialog
          isOpen={false}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
        />
      );

      rerender(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
        />
      );

      // Form should be empty
      const nameInput = screen.getByLabelText(/Rule Name/);
      expect(nameInput).toHaveValue('');
    });
  });

  describe('Disabled State', () => {
    it('disables buttons while submitting', async () => {
      const user = userEvent.setup();
      let resolveSubmit: () => void;
      const submitPromise = new Promise<void>((resolve) => {
        resolveSubmit = resolve;
      });
      mockOnSubmit.mockReturnValue(submitPromise);

      renderWithProviders(
        <QualityRuleFormDialog
          isOpen={true}
          onOpenChange={mockOnOpenChange}
          onSubmit={mockOnSubmit}
        />
      );

      const nameInput = screen.getByLabelText(/Rule Name/);
      await user.type(nameInput, 'Test Rule');

      const saveButton = screen.getByRole('button', { name: /Add Rule/i });
      await user.click(saveButton);

      // Button should be disabled while submitting
      await waitFor(() => {
        expect(saveButton).toBeDisabled();
      });

      // Resolve the promise
      resolveSubmit!();

      await waitFor(() => {
        expect(mockOnOpenChange).toHaveBeenCalledWith(false);
      });
    });
  });
});
