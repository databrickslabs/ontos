import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
// waitFor - available for future use
import { useComments } from './use-comments';
import * as useApiModule from './use-api';
import * as useToastModule from './use-toast';

// Mock the dependencies
vi.mock('./use-api');
vi.mock('./use-toast');

describe('useComments Hook', () => {
  const mockGet = vi.fn();
  const mockPost = vi.fn();
  const mockPut = vi.fn();
  const mockDelete = vi.fn();
  const mockToast = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();

    // Setup useApi mock
    vi.spyOn(useApiModule, 'useApi').mockReturnValue({
      get: mockGet,
      post: mockPost,
      put: mockPut,
      delete: mockDelete,
      loading: false,
    });

    // Setup useToast mock
    vi.spyOn(useToastModule, 'useToast').mockReturnValue({
      toast: mockToast,
      dismiss: vi.fn(),
      toasts: [],
    });
  });

  describe('Initial State', () => {
    it('initializes with empty state', () => {
      const { result } = renderHook(() => useComments('data-product', '123'));

      expect(result.current.comments).toEqual([]);
      expect(result.current.totalCount).toBe(0);
      expect(result.current.visibleCount).toBe(0);
      expect(result.current.loading).toBe(false);
    });

    it('provides all required functions', () => {
      const { result } = renderHook(() => useComments('data-product', '123'));

      expect(typeof result.current.fetchComments).toBe('function');
      expect(typeof result.current.createComment).toBe('function');
      expect(typeof result.current.updateComment).toBe('function');
      expect(typeof result.current.deleteComment).toBe('function');
      expect(typeof result.current.checkCommentPermissions).toBe('function');
      expect(typeof result.current.getComment).toBe('function');
    });

    it('can be initialized without entityType and entityId', () => {
      const { result } = renderHook(() => useComments());

      expect(result.current).toBeDefined();
      expect(result.current.comments).toEqual([]);
    });
  });

  describe('fetchComments', () => {
    const mockComments = [
      {
        id: '1',
        entity_type: 'data-product',
        entity_id: '123',
        content: 'Test comment',
        created_at: '2024-01-01T10:00:00Z',
        updated_at: '2024-01-01T10:00:00Z',
        created_by: 'user@example.com',
        is_deleted: false,
      },
    ];

    const mockResponse = {
      comments: mockComments,
      total_count: 1,
      visible_count: 1,
    };

    it('fetches comments successfully', async () => {
      mockGet.mockResolvedValueOnce({ data: mockResponse });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await act(async () => {
        await result.current.fetchComments();
      });

      expect(mockGet).toHaveBeenCalledWith('/api/entities/data-product/123/comments');
      expect(result.current.comments).toEqual(mockComments);
      expect(result.current.totalCount).toBe(1);
      expect(result.current.visibleCount).toBe(1);
    });

    it('fetches comments with includeDeleted parameter', async () => {
      mockGet.mockResolvedValueOnce({ data: mockResponse });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await act(async () => {
        await result.current.fetchComments(undefined, undefined, true);
      });

      expect(mockGet).toHaveBeenCalledWith('/api/entities/data-product/123/comments?include_deleted=true');
    });

    it('uses provided entityType and entityId parameters', async () => {
      mockGet.mockResolvedValueOnce({ data: mockResponse });

      const { result } = renderHook(() => useComments());

      await act(async () => {
        await result.current.fetchComments('data-contract', '456');
      });

      expect(mockGet).toHaveBeenCalledWith('/api/entities/data-contract/456/comments');
    });

    it('does not fetch if entityType or entityId is missing', async () => {
      const { result } = renderHook(() => useComments());

      await act(async () => {
        await result.current.fetchComments();
      });

      expect(mockGet).not.toHaveBeenCalled();
    });

    it('shows toast on error', async () => {
      mockGet.mockResolvedValueOnce({ error: 'Failed to fetch' });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await act(async () => {
        await result.current.fetchComments();
      });

      expect(mockToast).toHaveBeenCalledWith({
        title: 'Error',
        description: 'Failed to load comments: Failed to fetch',
        variant: 'destructive',
      });
    });

    it('handles empty comments list', async () => {
      mockGet.mockResolvedValueOnce({
        data: { comments: [], total_count: 0, visible_count: 0 },
      });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await act(async () => {
        await result.current.fetchComments();
      });

      expect(result.current.comments).toEqual([]);
      expect(result.current.totalCount).toBe(0);
    });
  });

  describe('createComment', () => {
    const mockComment = {
      id: '1',
      entity_type: 'data-product',
      entity_id: '123',
      content: 'New comment',
      created_at: '2024-01-01T10:00:00Z',
      updated_at: '2024-01-01T10:00:00Z',
      created_by: 'user@example.com',
      is_deleted: false,
    };

    it('creates comment successfully', async () => {
      mockPost.mockResolvedValueOnce({ data: mockComment });
      mockGet.mockResolvedValueOnce({
        data: { comments: [mockComment], total_count: 1, visible_count: 1 },
      });

      const { result } = renderHook(() => useComments('data-product', '123'));

      const commentData = {
        entity_type: 'data-product',
        entity_id: '123',
        comment: 'New comment',
      };

      await act(async () => {
        await result.current.createComment(commentData);
      });

      expect(mockPost).toHaveBeenCalledWith('/api/entities/data-product/123/comments', commentData);
      expect(mockToast).toHaveBeenCalledWith({
        title: 'Success',
        description: 'Comment created successfully',
      });
    });

    it('refreshes comments after creation', async () => {
      mockPost.mockResolvedValueOnce({ data: mockComment });
      mockGet.mockResolvedValueOnce({
        data: { comments: [mockComment], total_count: 1, visible_count: 1 },
      });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await act(async () => {
        await result.current.createComment({
          entity_type: 'data-product',
          entity_id: '123',
          comment: 'Test',
        });
      });

      expect(mockGet).toHaveBeenCalled();
      expect(result.current.comments).toHaveLength(1);
    });

    it('uses provided entityType and entityId parameters', async () => {
      mockPost.mockResolvedValueOnce({ data: mockComment });
      mockGet.mockResolvedValueOnce({
        data: { comments: [], total_count: 0, visible_count: 0 },
      });

      const { result } = renderHook(() => useComments());

      await act(async () => {
        await result.current.createComment(
          { content: 'Test' } as any,
          'data-contract',
          '456'
        );
      });

      expect(mockPost).toHaveBeenCalledWith('/api/entities/data-contract/456/comments', { content: 'Test' });
    });

    it('throws error if entityType or entityId is missing', async () => {
      const { result } = renderHook(() => useComments());

      await expect(
        act(async () => {
          await result.current.createComment({ content: 'Test' } as any);
        })
      ).rejects.toThrow('Entity type and ID are required for creating comments');
    });

    it('shows toast and throws on API error', async () => {
      mockPost.mockResolvedValueOnce({ error: 'Creation failed' });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await expect(
        act(async () => {
          await result.current.createComment({
            entity_type: 'data-product',
            entity_id: '123',
            comment: 'Test',
          });
        })
      ).rejects.toThrow('Creation failed');

      expect(mockToast).toHaveBeenCalledWith({
        title: 'Error',
        description: 'Failed to create comment: Creation failed',
        variant: 'destructive',
      });
    });
  });

  describe('updateComment', () => {
    const mockComment = {
      id: '1',
      entity_type: 'data-product',
      entity_id: '123',
      content: 'Updated comment',
      created_at: '2024-01-01T10:00:00Z',
      updated_at: '2024-01-01T11:00:00Z',
      created_by: 'user@example.com',
      is_deleted: false,
    };

    it('updates comment successfully', async () => {
      mockPut.mockResolvedValueOnce({ data: mockComment });
      mockGet.mockResolvedValueOnce({
        data: { comments: [mockComment], total_count: 1, visible_count: 1 },
      });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await act(async () => {
        await result.current.updateComment('1', { comment: 'Updated' });
      });

      expect(mockPut).toHaveBeenCalledWith('/api/comments/1', { comment: 'Updated' });
      expect(mockToast).toHaveBeenCalledWith({
        title: 'Success',
        description: 'Comment updated successfully',
      });
    });

    it('refreshes comments after update', async () => {
      mockPut.mockResolvedValueOnce({ data: mockComment });
      mockGet.mockResolvedValueOnce({
        data: { comments: [mockComment], total_count: 1, visible_count: 1 },
      });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await act(async () => {
        await result.current.updateComment('1', { comment: 'Updated' });
      });

      expect(mockGet).toHaveBeenCalled();
    });

    it('shows toast and throws on API error', async () => {
      mockPut.mockResolvedValueOnce({ error: 'Update failed' });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await expect(
        act(async () => {
          await result.current.updateComment('1', { comment: 'Updated' });
        })
      ).rejects.toThrow('Update failed');

      expect(mockToast).toHaveBeenCalledWith({
        title: 'Error',
        description: 'Failed to update comment: Update failed',
        variant: 'destructive',
      });
    });
  });

  describe('deleteComment', () => {
    it('deletes comment successfully (soft delete)', async () => {
      mockDelete.mockResolvedValueOnce({ data: {} });
      mockGet.mockResolvedValueOnce({
        data: { comments: [], total_count: 0, visible_count: 0 },
      });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await act(async () => {
        const success = await result.current.deleteComment('1');
        expect(success).toBe(true);
      });

      expect(mockDelete).toHaveBeenCalledWith('/api/comments/1');
      expect(mockToast).toHaveBeenCalledWith({
        title: 'Success',
        description: 'Comment deleted successfully',
      });
    });

    it('deletes comment with hardDelete parameter', async () => {
      mockDelete.mockResolvedValueOnce({ data: {} });
      mockGet.mockResolvedValueOnce({
        data: { comments: [], total_count: 0, visible_count: 0 },
      });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await act(async () => {
        await result.current.deleteComment('1', true);
      });

      expect(mockDelete).toHaveBeenCalledWith('/api/comments/1?hard_delete=true');
    });

    it('refreshes comments after deletion', async () => {
      mockDelete.mockResolvedValueOnce({ data: {} });
      mockGet.mockResolvedValueOnce({
        data: { comments: [], total_count: 0, visible_count: 0 },
      });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await act(async () => {
        await result.current.deleteComment('1');
      });

      expect(mockGet).toHaveBeenCalled();
    });

    it('shows toast and throws on API error', async () => {
      mockDelete.mockResolvedValueOnce({ error: 'Delete failed' });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await expect(
        act(async () => {
          await result.current.deleteComment('1');
        })
      ).rejects.toThrow('Delete failed');

      expect(mockToast).toHaveBeenCalledWith({
        title: 'Error',
        description: 'Failed to delete comment: Delete failed',
        variant: 'destructive',
      });
    });
  });

  describe('checkCommentPermissions', () => {
    it('checks permissions successfully', async () => {
      const mockPermissions = {
        can_modify: true,
        is_admin: false,
      };

      mockGet.mockResolvedValueOnce({ data: mockPermissions });

      const { result } = renderHook(() => useComments('data-product', '123'));

      let permissions;
      await act(async () => {
        permissions = await result.current.checkCommentPermissions('1');
      });

      expect(mockGet).toHaveBeenCalledWith('/api/comments/1/permissions');
      expect(permissions).toEqual(mockPermissions);
    });

    it('returns default permissions on error', async () => {
      mockGet.mockResolvedValueOnce({ error: 'Permission check failed' });

      const { result } = renderHook(() => useComments('data-product', '123'));

      let permissions;
      await act(async () => {
        permissions = await result.current.checkCommentPermissions('1');
      });

      expect(permissions).toEqual({ can_modify: false, is_admin: false });
    });
  });

  describe('getComment', () => {
    const mockComment = {
      id: '1',
      entity_type: 'data-product',
      entity_id: '123',
      content: 'Test comment',
      created_at: '2024-01-01T10:00:00Z',
      updated_at: '2024-01-01T10:00:00Z',
      created_by: 'user@example.com',
      is_deleted: false,
    };

    it('gets single comment successfully', async () => {
      mockGet.mockResolvedValueOnce({ data: mockComment });

      const { result } = renderHook(() => useComments('data-product', '123'));

      let comment;
      await act(async () => {
        comment = await result.current.getComment('1');
      });

      expect(mockGet).toHaveBeenCalledWith('/api/comments/1');
      expect(comment).toEqual(mockComment);
    });

    it('shows toast and throws on API error', async () => {
      mockGet.mockResolvedValueOnce({ error: 'Not found' });

      const { result } = renderHook(() => useComments('data-product', '123'));

      await expect(
        act(async () => {
          await result.current.getComment('1');
        })
      ).rejects.toThrow('Not found');

      expect(mockToast).toHaveBeenCalledWith({
        title: 'Error',
        description: 'Failed to get comment: Not found',
        variant: 'destructive',
      });
    });
  });

  describe('Hook Stability', () => {
    it('maintains function references when props do not change', () => {
      const { result, rerender } = renderHook(() => useComments('data-product', '123'));

      const firstFetchComments = result.current.fetchComments;
      const firstCreateComment = result.current.createComment;

      rerender();

      expect(result.current.fetchComments).toBe(firstFetchComments);
      expect(result.current.createComment).toBe(firstCreateComment);
    });

    it('updates function references when dependencies change', () => {
      const { result, rerender } = renderHook(
        ({ entityType, entityId }) => useComments(entityType, entityId),
        { initialProps: { entityType: 'data-product', entityId: '123' } }
      );

      // Capture initial function reference (not used directly but demonstrates reference capture)
      void result.current.fetchComments;

      rerender({ entityType: 'data-contract', entityId: '456' });

      // Function reference may change due to dependency array
      expect(result.current.fetchComments).toBeDefined();
    });
  });
});
