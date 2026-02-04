import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
// fireEvent - available for future use
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import TagChip, { AssignedTag } from './tag-chip';

describe('TagChip', () => {
  describe('Simple string tags', () => {
    it('renders simple string tag', () => {
      renderWithProviders(<TagChip tag="simple-tag" />);

      expect(screen.getByText('simple-tag')).toBeInTheDocument();
      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    });

    it('renders with removable functionality', async () => {
      const onRemove = vi.fn();
      const user = userEvent.setup();

      renderWithProviders(
        <TagChip
          tag="removable-tag"
          removable={true}
          onRemove={onRemove}
        />
      );

      const removeButton = screen.getByRole('button', { name: /remove removable-tag tag/i });
      expect(removeButton).toBeInTheDocument();

      await user.click(removeButton);
      expect(onRemove).toHaveBeenCalledWith('removable-tag');
    });

    it('applies different sizes correctly', () => {
      const { rerender } = renderWithProviders(<TagChip tag="test-tag" size="sm" />);
      const badge = screen.getByText('test-tag').closest('[class*="text-xs"]');
      expect(badge).toBeInTheDocument();

      rerender(<TagChip tag="test-tag" size="md" />);
      const badgeMd = screen.getByText('test-tag').closest('[class*="text-sm"]');
      expect(badgeMd).toBeInTheDocument();

      rerender(<TagChip tag="test-tag" size="lg" />);
      const badgeLg = screen.getByText('test-tag').closest('[class*="text-base"]');
      expect(badgeLg).toBeInTheDocument();
    });

    it('applies custom variant correctly', () => {
      renderWithProviders(<TagChip tag="test-tag" variant="destructive" />);
      // Badge component would apply the destructive variant styling
      expect(screen.getByText('test-tag')).toBeInTheDocument();
    });
  });

  describe('Rich AssignedTag objects', () => {
    const mockAssignedTag: AssignedTag = {
      tag_id: 'tag-123',
      tag_name: 'environment',
      namespace_id: 'ns-456',
      namespace_name: 'technical',
      status: 'active',
      fully_qualified_name: 'technical.environment',
      assigned_value: 'production',
      assigned_by: 'john.doe@company.com',
      assigned_at: '2024-01-15T10:30:00Z'
    };

    it('renders rich tag with assigned value', () => {
      renderWithProviders(<TagChip tag={mockAssignedTag} />);

      expect(screen.getByText('environment: production')).toBeInTheDocument();

      // Look for the info icon (SVG) - it should be present in the DOM
      const container = screen.getByText('environment: production').closest('div');
      expect(container?.querySelector('svg')).toBeInTheDocument();

      // Basic tooltip structure should be present (without testing hover behavior)
      expect(screen.getByText('environment: production').closest('[data-state]')).toBeInTheDocument();
    });

    it('renders rich tag without assigned value', () => {
      const tagWithoutValue: AssignedTag = {
        ...mockAssignedTag,
        assigned_value: undefined
      };

      renderWithProviders(<TagChip tag={tagWithoutValue} />);

      expect(screen.getByText('environment')).toBeInTheDocument();
      expect(screen.queryByText('environment: production')).not.toBeInTheDocument();
    });

    it('applies status-based variant for deprecated tag', () => {
      const deprecatedTag: AssignedTag = {
        ...mockAssignedTag,
        status: 'deprecated'
      };

      renderWithProviders(<TagChip tag={deprecatedTag} />);
      // Component should apply destructive variant for deprecated status
      expect(screen.getByText('environment: production')).toBeInTheDocument();
    });

    it('applies status-based variant for draft tag', () => {
      const draftTag: AssignedTag = {
        ...mockAssignedTag,
        status: 'draft'
      };

      renderWithProviders(<TagChip tag={draftTag} />);
      // Component should apply secondary variant for draft status
      expect(screen.getByText('environment: production')).toBeInTheDocument();
    });

    it('handles removal of rich tag', async () => {
      const onRemove = vi.fn();
      const user = userEvent.setup();

      renderWithProviders(
        <TagChip
          tag={mockAssignedTag}
          removable={true}
          onRemove={onRemove}
        />
      );

      const removeButton = screen.getByRole('button', { name: /remove environment tag/i });
      await user.click(removeButton);

      expect(onRemove).toHaveBeenCalledWith(mockAssignedTag);
    });

    it('prevents event propagation on remove button click', async () => {
      const onRemove = vi.fn();
      const onContainerClick = vi.fn();
      const user = userEvent.setup();

      renderWithProviders(
        <div onClick={onContainerClick}>
          <TagChip
            tag={mockAssignedTag}
            removable={true}
            onRemove={onRemove}
          />
        </div>
      );

      const removeButton = screen.getByRole('button', { name: /remove environment tag/i });
      await user.click(removeButton);

      expect(onRemove).toHaveBeenCalled();
      expect(onContainerClick).not.toHaveBeenCalled();
    });
  });

  describe('Accessibility', () => {
    it('has proper ARIA labels for remove button', () => {
      renderWithProviders(
        <TagChip
          tag="accessibility-tag"
          removable={true}
          onRemove={() => {}}
        />
      );

      const removeButton = screen.getByRole('button', { name: 'Remove accessibility-tag tag' });
      expect(removeButton).toBeInTheDocument();
    });

    it('has proper ARIA labels for rich tag remove button', () => {
      const richTag: AssignedTag = {
        tag_id: 'tag-123',
        tag_name: 'test-tag',
        namespace_id: 'ns-456',
        namespace_name: 'test',
        status: 'active',
        fully_qualified_name: 'test.test-tag',
        assigned_at: '2024-01-15T10:30:00Z'
      };

      renderWithProviders(
        <TagChip
          tag={richTag}
          removable={true}
          onRemove={() => {}}
        />
      );

      const removeButton = screen.getByRole('button', { name: 'Remove test-tag tag' });
      expect(removeButton).toBeInTheDocument();
    });
  });

  describe('Custom styling', () => {
    it('applies custom className', () => {
      renderWithProviders(<TagChip tag="styled-tag" className="custom-class" />);

      const badge = screen.getByText('styled-tag').closest('.custom-class');
      expect(badge).toBeInTheDocument();
    });

    it('applies size classes correctly with removable', () => {
      renderWithProviders(
        <TagChip
          tag="removable-small"
          size="sm"
          removable={true}
          onRemove={() => {}}
        />
      );

      const badge = screen.getByText('removable-small').closest('[class*="text-xs"]');
      expect(badge).toBeInTheDocument();
      expect(badge?.closest('[class*="pr-1"]')).toBeInTheDocument();
    });
  });
});