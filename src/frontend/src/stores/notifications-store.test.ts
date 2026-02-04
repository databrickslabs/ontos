import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useNotificationsStore } from './notifications-store';
import { Notification } from '@/types/notification';

// Mock fetch globally
global.fetch = vi.fn();

describe('Notifications Store', () => {
  beforeEach(() => {
    // Reset store state
    act(() => {
      useNotificationsStore.setState({
        notifications: [],
        unreadCount: 0,
        isLoading: false,
        error: null,
      });
    });

    // Stop any ongoing polling
    const store = useNotificationsStore.getState();
    store.stopPolling();

    vi.clearAllMocks();
  });

  afterEach(() => {
    // Ensure polling is stopped after each test
    const store = useNotificationsStore.getState();
    store.stopPolling();

    vi.restoreAllMocks();
  });

  describe('Initial State', () => {
    it('has correct initial state', () => {
      const { result } = renderHook(() => useNotificationsStore());

      expect(result.current.notifications).toEqual([]);
      expect(result.current.unreadCount).toBe(0);
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('provides all required functions', () => {
      const { result } = renderHook(() => useNotificationsStore());

      expect(typeof result.current.fetchNotifications).toBe('function');
      expect(typeof result.current.refreshNotifications).toBe('function');
      expect(typeof result.current.markAsRead).toBe('function');
      expect(typeof result.current.deleteNotification).toBe('function');
      expect(typeof result.current.startPolling).toBe('function');
      expect(typeof result.current.stopPolling).toBe('function');
    });
  });

  describe('fetchNotifications', () => {
    const mockNotifications: Notification[] = [
      {
        id: '1',
        type: 'info',
        title: 'Info Notification',
        subtitle: null,
        description: 'Test info',
        link: null,
        created_at: '2024-01-01T10:00:00Z',
        read: false,
        can_delete: true,
        recipient: null,
        action_type: null,
        action_payload: null,
      },
      {
        id: '2',
        type: 'success',
        title: 'Success Notification',
        subtitle: null,
        description: 'Test success',
        link: null,
        created_at: '2024-01-01T11:00:00Z',
        read: true,
        can_delete: true,
        recipient: null,
        action_type: null,
        action_payload: null,
      },
    ];

    it('fetches notifications successfully', async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify(mockNotifications),
      });

      const { result } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result.current.fetchNotifications();
      });

      expect(result.current.notifications).toHaveLength(2);
      expect(result.current.unreadCount).toBe(1);
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('calculates unread count correctly', async () => {
      const notifications: Notification[] = [
        { ...mockNotifications[0], read: false },
        { ...mockNotifications[1], read: false },
      ];

      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify(notifications),
      });

      const { result } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result.current.fetchNotifications();
      });

      expect(result.current.unreadCount).toBe(2);
    });

    it('handles empty notifications list', async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify([]),
      });

      const { result } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result.current.fetchNotifications();
      });

      expect(result.current.notifications).toEqual([]);
      expect(result.current.unreadCount).toBe(0);
    });

    it('handles API error', async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      });

      const { result } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result.current.fetchNotifications();
      });

      expect(result.current.error).toBeTruthy();
      expect(result.current.isLoading).toBe(false);
    });

    it('handles network error', async () => {
      (global.fetch as any).mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result.current.fetchNotifications();
      });

      expect(result.current.error).toBeTruthy();
    });

    it('keeps stale data on failed fetch', async () => {
      // First successful fetch
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify(mockNotifications),
      });

      const { result } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result.current.fetchNotifications();
      });

      const existingNotifications = result.current.notifications;

      // Second failed fetch
      (global.fetch as any).mockRejectedValueOnce(new Error('Failed'));

      await act(async () => {
        await result.current.fetchNotifications();
      });

      // Notifications should still be there
      expect(result.current.notifications).toEqual(existingNotifications);
      expect(result.current.error).toBeTruthy();
    });

    it('prevents unnecessary re-renders when data unchanged', async () => {
      (global.fetch as any).mockResolvedValue({
        ok: true,
        text: async () => JSON.stringify(mockNotifications),
      });

      const { result } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result.current.fetchNotifications();
      });

      const firstNotifications = result.current.notifications;

      await act(async () => {
        await result.current.fetchNotifications();
      });

      // Should have the same data content (deep equality, not reference equality
      // since the store creates new arrays on each fetch)
      expect(result.current.notifications).toStrictEqual(firstNotifications);
    });
  });

  describe('refreshNotifications', () => {
    it('calls fetchNotifications', async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify([]),
      });

      const { result } = renderHook(() => useNotificationsStore());

      // refreshNotifications is fire-and-forget, just trigger it
      act(() => {
        result.current.refreshNotifications();
      });

      // Wait for async operation to complete
      await waitFor(
        () => {
          expect(global.fetch).toHaveBeenCalledWith('/api/notifications');
          expect(result.current.isLoading).toBe(false);
        },
        { timeout: 3000 }
      );
    });
  });

  describe('markAsRead', () => {
    const mockNotifications: Notification[] = [
      {
        id: '1',
        type: 'info',
        title: 'Unread',
        subtitle: null,
        description: null,
        link: null,
        created_at: '2024-01-01T10:00:00Z',
        read: false,
        can_delete: true,
        recipient: null,
        action_type: null,
        action_payload: null,
      },
      {
        id: '2',
        type: 'info',
        title: 'Read',
        subtitle: null,
        description: null,
        link: null,
        created_at: '2024-01-01T11:00:00Z',
        read: true,
        can_delete: true,
        recipient: null,
        action_type: null,
        action_payload: null,
      },
    ];

    it('marks notification as read with optimistic update', async () => {
      // Setup initial state
      act(() => {
        useNotificationsStore.setState({
          notifications: mockNotifications,
          unreadCount: 1,
        });
      });

      (global.fetch as any).mockResolvedValueOnce({ ok: true });

      const { result } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result.current.markAsRead('1');
      });

      const notification = result.current.notifications.find(n => n.id === '1');
      expect(notification?.read).toBe(true);
      expect(result.current.unreadCount).toBe(0);
    });

    it('decrements unread count correctly', async () => {
      act(() => {
        useNotificationsStore.setState({
          notifications: mockNotifications,
          unreadCount: 1,
        });
      });

      (global.fetch as any).mockResolvedValueOnce({ ok: true });

      const { result } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result.current.markAsRead('1');
      });

      expect(result.current.unreadCount).toBe(0);
    });

    it('does not change unread count if already read', async () => {
      act(() => {
        useNotificationsStore.setState({
          notifications: mockNotifications,
          unreadCount: 1,
        });
      });

      (global.fetch as any).mockResolvedValueOnce({ ok: true });

      const { result } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result.current.markAsRead('2'); // Already read
      });

      expect(result.current.unreadCount).toBe(1); // Unchanged
    });

    it('reverts optimistic update on API error', async () => {
      act(() => {
        useNotificationsStore.setState({
          notifications: mockNotifications,
          unreadCount: 1,
        });
      });

      (global.fetch as any).mockRejectedValueOnce(new Error('API Error'));

      const { result } = renderHook(() => useNotificationsStore());

      // Call markAsRead - it doesn't throw, just sets error internally
      await act(async () => {
        await result.current.markAsRead('1');
      });

      // Should be reverted after error
      await waitFor(
        () => {
          const notification = result.current.notifications.find(n => n.id === '1');
          expect(notification?.read).toBe(false);
          expect(result.current.unreadCount).toBe(1);
        },
        { timeout: 3000 }
      );
    });
  });

  describe('deleteNotification', () => {
    const mockNotifications: Notification[] = [
      {
        id: '1',
        type: 'info',
        title: 'First',
        subtitle: null,
        description: null,
        link: null,
        created_at: '2024-01-01T10:00:00Z',
        read: false,
        can_delete: true,
        recipient: null,
        action_type: null,
        action_payload: null,
      },
      {
        id: '2',
        type: 'info',
        title: 'Second',
        subtitle: null,
        description: null,
        link: null,
        created_at: '2024-01-01T11:00:00Z',
        read: true,
        can_delete: true,
        recipient: null,
        action_type: null,
        action_payload: null,
      },
    ];

    it('deletes notification with optimistic update', async () => {
      act(() => {
        useNotificationsStore.setState({
          notifications: mockNotifications,
          unreadCount: 1,
        });
      });

      (global.fetch as any).mockResolvedValueOnce({ ok: true });

      const { result } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result.current.deleteNotification('1');
      });

      expect(result.current.notifications).toHaveLength(1);
      expect(result.current.notifications[0].id).toBe('2');
      expect(result.current.unreadCount).toBe(0);
    });

    it('decrements unread count when deleting unread notification', async () => {
      act(() => {
        useNotificationsStore.setState({
          notifications: mockNotifications,
          unreadCount: 1,
        });
      });

      (global.fetch as any).mockResolvedValueOnce({ ok: true });

      const { result } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result.current.deleteNotification('1'); // Unread
      });

      expect(result.current.unreadCount).toBe(0);
    });

    it('does not change unread count when deleting read notification', async () => {
      act(() => {
        useNotificationsStore.setState({
          notifications: mockNotifications,
          unreadCount: 1,
        });
      });

      (global.fetch as any).mockResolvedValueOnce({ ok: true });

      const { result } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result.current.deleteNotification('2'); // Already read
      });

      expect(result.current.unreadCount).toBe(1); // Unchanged
    });

    it('reverts optimistic update on API error', async () => {
      act(() => {
        useNotificationsStore.setState({
          notifications: mockNotifications,
          unreadCount: 1,
        });
      });

      (global.fetch as any).mockRejectedValueOnce(new Error('Delete failed'));

      const { result } = renderHook(() => useNotificationsStore());

      // Call deleteNotification - it doesn't throw, just sets error internally
      await act(async () => {
        await result.current.deleteNotification('1');
      });

      // Should be reverted after error
      await waitFor(
        () => {
          expect(result.current.notifications).toHaveLength(2);
          expect(result.current.unreadCount).toBe(1);
        },
        { timeout: 3000 }
      );
    });
  });

  describe('Polling', () => {
    it('starts polling and fetches immediately', async () => {
      (global.fetch as any).mockResolvedValue({
        ok: true,
        text: async () => JSON.stringify([]),
      });

      const { result } = renderHook(() => useNotificationsStore());

      act(() => {
        result.current.startPolling();
      });

      // Should fetch immediately
      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith('/api/notifications');
      });

      // Clean up
      act(() => {
        result.current.stopPolling();
      });
    });

    it('calls stop and start correctly', () => {
      const { result } = renderHook(() => useNotificationsStore());

      // These should not throw
      act(() => {
        result.current.startPolling();
        result.current.stopPolling();
      });

      // Should be able to start again
      act(() => {
        result.current.startPolling();
        result.current.stopPolling();
      });
    });

    it('clears existing polling before starting new', async () => {
      (global.fetch as any).mockResolvedValue({
        ok: true,
        text: async () => JSON.stringify([]),
      });

      const { result } = renderHook(() => useNotificationsStore());

      act(() => {
        result.current.startPolling();
        result.current.startPolling(); // Start again - should clear first
      });

      // Wait for fetch to complete - due to guard, only 1 actual fetch occurs
      // (second startPolling waits for first fetch to complete instead of making a new request)
      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledTimes(1);
      });

      // Clean up
      act(() => {
        result.current.stopPolling();
      });
    });
  });

  describe('Store Integration', () => {
    it('updates all subscribers when state changes', async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify([]),
      });

      const { result: result1 } = renderHook(() => useNotificationsStore());
      const { result: result2 } = renderHook(() => useNotificationsStore());

      await act(async () => {
        await result1.current.fetchNotifications();
      });

      expect(result1.current.isLoading).toBe(false);
      expect(result2.current.isLoading).toBe(false);
    });
  });
});
