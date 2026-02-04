import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import usePermissionsStore, { usePermissions } from './permissions-store';
import { FeatureAccessLevel } from '@/types/settings';

// Mock fetch globally
global.fetch = vi.fn();

describe('Permissions Store', () => {
  beforeEach(() => {
    // Reset store state before each test
    act(() => {
      usePermissionsStore.setState({
        permissions: {},
        actualPermissions: {},
        isLoading: false,
        error: null,
        availableRoles: [],
        requestableRoles: [],
        appliedRoleId: null,
        _isInitializing: false,
      });
    });

    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('Initial State', () => {
    it('has correct initial state', () => {
      const { result } = renderHook(() => usePermissionsStore());

      expect(result.current.permissions).toEqual({});
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.availableRoles).toEqual([]);
      expect(result.current.appliedRoleId).toBeNull();
    });
  });

  describe('fetchPermissions', () => {
    it('fetches and sets permissions successfully', async () => {
      // Arrange
      const mockPermissions = {
        'data-products': FeatureAccessLevel.READ_WRITE,
        'data-contracts': FeatureAccessLevel.READ_ONLY,
      };

      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => mockPermissions,
      });

      const { result } = renderHook(() => usePermissionsStore());

      // Act
      await act(async () => {
        await result.current.fetchPermissions();
      });

      // Assert
      expect(result.current.permissions).toEqual(mockPermissions);
      expect(result.current.error).toBeNull();
    });

    it('handles fetch errors gracefully', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ detail: 'Server error' }),
      });

      const { result } = renderHook(() => usePermissionsStore());

      // Act - The function throws but sets error state first
      try {
        await act(async () => {
          await result.current.fetchPermissions();
        });
      } catch (e) {
        // Ignore throw - we're testing error state
      }

      // Access store state directly to bypass React hook observation layer
      const storeState = usePermissionsStore.getState();

      // Error state should be set even though function threw
      expect(storeState.error).toBeTruthy();
      expect(storeState.error).toContain('Server error');
      expect(storeState.permissions).toEqual({});
    });

    it('handles network errors', async () => {
      // Arrange
      (global.fetch as any).mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => usePermissionsStore());

      // Act - The function throws but sets error state first
      await expect(
        act(async () => {
          await result.current.fetchPermissions();
        })
      ).rejects.toThrow();

      // Access store state directly to bypass React hook observation layer
      const storeState = usePermissionsStore.getState();

      // Error state should be set even though function threw
      expect(storeState.error).toBeTruthy();
      expect(storeState.error).toContain('Network error');
      expect(storeState.permissions).toEqual({});
    });
  });

  describe('fetchAvailableRoles', () => {
    it('fetches and sets available roles', async () => {
      // Arrange
      const mockRoles = [
        {
          id: 'role-1',
          name: 'Admin',
          feature_permissions: {
            'data-products': FeatureAccessLevel.ADMIN,
          },
        },
        {
          id: 'role-2',
          name: 'Viewer',
          feature_permissions: {
            'data-products': FeatureAccessLevel.READ_ONLY,
          },
        },
      ];

      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => mockRoles,
      });

      const { result } = renderHook(() => usePermissionsStore());

      // Act
      await act(async () => {
        await result.current.fetchAvailableRoles();
      });

      // Assert
      expect(result.current.availableRoles).toEqual(mockRoles);
      expect(result.current.error).toBeNull();
    });

    it('handles errors when fetching roles', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 403,
      });

      const { result } = renderHook(() => usePermissionsStore());

      // Act - The function throws but sets error state first
      await expect(
        act(async () => {
          await result.current.fetchAvailableRoles();
        })
      ).rejects.toThrow();

      // Access store state directly to bypass React hook observation layer
      const storeState = usePermissionsStore.getState();

      // Error state should be set even though function threw
      expect(storeState.error).toBeTruthy();
      expect(storeState.error).toContain('403');
      expect(storeState.availableRoles).toEqual([]);
    });
  });

  describe('fetchAppliedOverride', () => {
    it('fetches and sets applied role override', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ role_id: 'role-1' }),
      });

      const { result } = renderHook(() => usePermissionsStore());

      // Act
      await act(async () => {
        await result.current.fetchAppliedOverride();
      });

      // Assert
      expect(result.current.appliedRoleId).toBe('role-1');
    });

    it('handles missing override gracefully', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ role_id: null }),
      });

      const { result } = renderHook(() => usePermissionsStore());

      // Act
      await act(async () => {
        await result.current.fetchAppliedOverride();
      });

      // Assert
      expect(result.current.appliedRoleId).toBeNull();
    });

    it('silently handles fetch errors', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 404,
      });

      const { result } = renderHook(() => usePermissionsStore());

      // Act (should not throw)
      await act(async () => {
        await result.current.fetchAppliedOverride();
      });

      // Assert - should not update state
      expect(result.current.appliedRoleId).toBeNull();
    });
  });

  describe('initializeStore', () => {
    it('fetches all data on initialization', async () => {
      // Arrange
      const mockPermissions = { 'data-products': FeatureAccessLevel.READ_WRITE };
      const mockActualPermissions = { 'data-products': FeatureAccessLevel.READ_WRITE };
      const mockRoles = [{ id: 'role-1', name: 'Admin', feature_permissions: {}, assigned_groups: [] }];
      const mockRequestableRoles: any[] = [];
      const mockOverride = { role_id: null };

      // Store makes 5 parallel fetch calls
      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('/api/user/permissions')) {
          return Promise.resolve({ ok: true, json: async () => mockPermissions });
        }
        if (url.includes('/api/user/actual-permissions')) {
          return Promise.resolve({ ok: true, json: async () => mockActualPermissions });
        }
        if (url.includes('/api/settings/roles')) {
          return Promise.resolve({ ok: true, json: async () => mockRoles });
        }
        if (url.includes('/api/user/requestable-roles')) {
          return Promise.resolve({ ok: true, json: async () => mockRequestableRoles });
        }
        if (url.includes('/api/user/role-override')) {
          return Promise.resolve({ ok: true, json: async () => mockOverride });
        }
        return Promise.resolve({ ok: true, json: async () => ({}) });
      });

      const { result } = renderHook(() => usePermissionsStore());

      // Act
      await act(async () => {
        await result.current.initializeStore();
      });

      // Assert
      expect(result.current.permissions).toEqual(mockPermissions);
      expect(result.current.availableRoles).toEqual(mockRoles);
      expect(result.current.isLoading).toBe(false);
      expect(result.current._isInitializing).toBe(false);
    });

    it('prevents concurrent initialization', async () => {
      // Arrange
      (global.fetch as any).mockImplementation(
        () => new Promise(resolve => setTimeout(() => resolve({ ok: true, json: async () => ({}) }), 100))
      );

      const { result } = renderHook(() => usePermissionsStore());

      // Act - Call initialize multiple times concurrently
      const promises = [
        result.current.initializeStore(),
        result.current.initializeStore(),
        result.current.initializeStore(),
      ];

      await act(async () => {
        await Promise.all(promises);
      });

      // Assert - Should only call fetch once per endpoint (5 total: permissions, actualPermissions, roles, requestableRoles, override)
      expect(global.fetch).toHaveBeenCalledTimes(5);
    });

    it('skips initialization if already loaded', async () => {
      // Arrange - Pre-populate store
      const { result } = renderHook(() => usePermissionsStore());

      act(() => {
        usePermissionsStore.setState({
          permissions: { 'data-products': FeatureAccessLevel.READ_ONLY },
          availableRoles: [{ id: 'role-1', name: 'Test', feature_permissions: {}, assigned_groups: [] }],
        });
      });

      // Act
      await act(async () => {
        await result.current.initializeStore();
      });

      // Assert - Should not call fetch
      expect(global.fetch).not.toHaveBeenCalled();
    });

    it('handles initialization errors', async () => {
      // Arrange - Make all fetches fail
      (global.fetch as any).mockImplementation(() => {
        return Promise.reject(new Error('Init error'));
      });

      const { result } = renderHook(() => usePermissionsStore());

      // Act
      await act(async () => {
        await result.current.initializeStore();
      });

      // Assert
      expect(result.current.error).toBeTruthy();
      expect(result.current.isLoading).toBe(false);
      expect(result.current._isInitializing).toBe(false);
    });
  });

  describe('setRoleOverride', () => {
    it('sets role override and posts to API', async () => {
      // Arrange
      const mockPermissions = { 'data-products': FeatureAccessLevel.READ_ONLY };

      (global.fetch as any).mockResolvedValue({
        ok: true,
        json: async () => mockPermissions,
      });

      const { result } = renderHook(() => usePermissionsStore());

      // Act
      act(() => {
        result.current.setRoleOverride('role-1');
      });

      // Wait for async operations
      await waitFor(() => {
        expect(result.current.appliedRoleId).toBe('role-1');
      });

      // Assert API was called
      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith(
          '/api/user/role-override',
          expect.objectContaining({
            method: 'POST',
            body: JSON.stringify({ role_id: 'role-1' }),
          })
        );
      });
    });

    it('clears role override when set to null', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValue({ ok: true, json: async () => ({}) });

      const { result } = renderHook(() => usePermissionsStore());

      act(() => {
        usePermissionsStore.setState({ appliedRoleId: 'role-1' });
      });

      // Act
      act(() => {
        result.current.setRoleOverride(null);
      });

      // Wait for state update
      await waitFor(() => {
        expect(result.current.appliedRoleId).toBeNull();
      });
    });

    it('handles API errors silently', async () => {
      // Arrange
      (global.fetch as any).mockRejectedValue(new Error('API error'));

      const { result } = renderHook(() => usePermissionsStore());

      // Act (should not throw)
      act(() => {
        result.current.setRoleOverride('role-1');
      });

      // Assert - should still update local state
      await waitFor(() => {
        expect(result.current.appliedRoleId).toBe('role-1');
      });
    });
  });

  describe('hasPermission', () => {
    it('returns true when user has sufficient permission', () => {
      // Arrange
      const { result } = renderHook(() => usePermissionsStore());

      act(() => {
        usePermissionsStore.setState({
          permissions: {
            'data-products': FeatureAccessLevel.READ_WRITE,
          },
        });
      });

      // Act & Assert
      expect(result.current.hasPermission('data-products', FeatureAccessLevel.READ_ONLY)).toBe(true);
      expect(result.current.hasPermission('data-products', FeatureAccessLevel.READ_WRITE)).toBe(true);
    });

    it('returns false when user lacks permission', () => {
      // Arrange
      const { result } = renderHook(() => usePermissionsStore());

      act(() => {
        usePermissionsStore.setState({
          permissions: {
            'data-products': FeatureAccessLevel.READ_ONLY,
          },
        });
      });

      // Act & Assert
      expect(result.current.hasPermission('data-products', FeatureAccessLevel.READ_WRITE)).toBe(false);
      expect(result.current.hasPermission('data-products', FeatureAccessLevel.ADMIN)).toBe(false);
    });

    it('returns false for features not in permissions', () => {
      // Arrange
      const { result } = renderHook(() => usePermissionsStore());

      act(() => {
        usePermissionsStore.setState({
          permissions: {},
        });
      });

      // Act & Assert
      expect(result.current.hasPermission('unknown-feature', FeatureAccessLevel.READ_ONLY)).toBe(false);
    });

    it('uses role override when set', () => {
      // Arrange
      const { result } = renderHook(() => usePermissionsStore());

      act(() => {
        usePermissionsStore.setState({
          permissions: {
            'data-products': FeatureAccessLevel.READ_ONLY,
          },
          appliedRoleId: 'admin-role',
          availableRoles: [
            {
              id: 'admin-role',
              name: 'Admin',
              feature_permissions: {
                'data-products': FeatureAccessLevel.ADMIN,
              },
              assigned_groups: [],
            },
          ],
        });
      });

      // Act & Assert - Should use override (ADMIN), not actual permission (READ_ONLY)
      expect(result.current.hasPermission('data-products', FeatureAccessLevel.ADMIN)).toBe(true);
    });
  });

  describe('getPermissionLevel', () => {
    it('returns correct permission level', () => {
      // Arrange
      const { result } = renderHook(() => usePermissionsStore());

      act(() => {
        usePermissionsStore.setState({
          permissions: {
            'data-products': FeatureAccessLevel.READ_WRITE,
          },
        });
      });

      // Act
      const level = result.current.getPermissionLevel('data-products');

      // Assert
      expect(level).toBe(FeatureAccessLevel.READ_WRITE);
    });

    it('returns NONE for missing features', () => {
      // Arrange
      const { result } = renderHook(() => usePermissionsStore());

      // Act
      const level = result.current.getPermissionLevel('unknown-feature');

      // Assert
      expect(level).toBe(FeatureAccessLevel.NONE);
    });

    it('returns role override level when set', () => {
      // Arrange
      const { result } = renderHook(() => usePermissionsStore());

      act(() => {
        usePermissionsStore.setState({
          permissions: {
            'data-products': FeatureAccessLevel.READ_ONLY,
          },
          appliedRoleId: 'admin-role',
          availableRoles: [
            {
              id: 'admin-role',
              name: 'Admin',
              feature_permissions: {
                'data-products': FeatureAccessLevel.ADMIN,
              },
              assigned_groups: [],
            },
          ],
        });
      });

      // Act
      const level = result.current.getPermissionLevel('data-products');

      // Assert
      expect(level).toBe(FeatureAccessLevel.ADMIN);
    });
  });

  describe('usePermissions hook', () => {
    it('initializes store on first use', async () => {
      // Arrange
      const mockPermissions = { 'data-products': FeatureAccessLevel.READ_ONLY };
      const mockActualPermissions = { 'data-products': FeatureAccessLevel.READ_ONLY };
      const mockRoles = [{ id: 'role-1', name: 'Test', feature_permissions: {}, assigned_groups: [] }];
      const mockRequestableRoles: any[] = [];
      const mockOverride = { role_id: null };

      // Store makes 5 parallel fetch calls
      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('/api/user/permissions')) {
          return Promise.resolve({ ok: true, json: async () => mockPermissions });
        }
        if (url.includes('/api/user/actual-permissions')) {
          return Promise.resolve({ ok: true, json: async () => mockActualPermissions });
        }
        if (url.includes('/api/settings/roles')) {
          return Promise.resolve({ ok: true, json: async () => mockRoles });
        }
        if (url.includes('/api/user/requestable-roles')) {
          return Promise.resolve({ ok: true, json: async () => mockRequestableRoles });
        }
        if (url.includes('/api/user/role-override')) {
          return Promise.resolve({ ok: true, json: async () => mockOverride });
        }
        return Promise.resolve({ ok: true, json: async () => ({}) });
      });

      // Act
      const { result } = renderHook(() => usePermissions());

      // Wait for initialization
      await waitFor(() => {
        expect(result.current.permissions).toEqual(mockPermissions);
      });

      // Assert
      expect(result.current.availableRoles).toEqual(mockRoles);
      expect(result.current.isLoading).toBe(false);
    });

    it('does not re-initialize if data already loaded', async () => {
      // Arrange - Pre-populate
      act(() => {
        usePermissionsStore.setState({
          permissions: { 'data-products': FeatureAccessLevel.READ_ONLY },
          availableRoles: [{ id: 'role-1', name: 'Test', feature_permissions: {}, assigned_groups: [] }],
        });
      });

      // Act
      renderHook(() => usePermissions());

      // Wait a bit
      await new Promise(resolve => setTimeout(resolve, 100));

      // Assert - No fetch calls
      expect(global.fetch).not.toHaveBeenCalled();
    });
  });
});
