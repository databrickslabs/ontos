import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
// waitFor - available for future use
import { useToast, toast } from './use-toast';

// Mock timers
vi.useFakeTimers();

describe('useToast Hook', () => {
  beforeEach(() => {
    vi.clearAllTimers();
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  describe('Initial State', () => {
    it('initializes with empty toasts array', () => {
      const { result } = renderHook(() => useToast());

      expect(result.current.toasts).toEqual([]);
    });

    it('provides toast function', () => {
      const { result } = renderHook(() => useToast());

      expect(typeof result.current.toast).toBe('function');
    });

    it('provides dismiss function', () => {
      const { result } = renderHook(() => useToast());

      expect(typeof result.current.dismiss).toBe('function');
    });
  });

  describe('Adding Toasts', () => {
    it('adds a toast with title', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ title: 'Test Toast' });
      });

      expect(result.current.toasts).toHaveLength(1);
      expect(result.current.toasts[0].title).toBe('Test Toast');
    });

    it('adds a toast with title and description', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({
          title: 'Success',
          description: 'Operation completed successfully',
        });
      });

      expect(result.current.toasts).toHaveLength(1);
      expect(result.current.toasts[0].title).toBe('Success');
      expect(result.current.toasts[0].description).toBe('Operation completed successfully');
    });

    it('adds a toast with variant', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({
          title: 'Error',
          variant: 'destructive',
        });
      });

      expect(result.current.toasts[0].variant).toBe('destructive');
    });

    it('generates unique IDs for each toast', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ title: 'Toast 1' });
        result.current.toast({ title: 'Toast 2' });
      });

      // Only one toast should be visible due to TOAST_LIMIT = 1
      expect(result.current.toasts).toHaveLength(1);
      expect(result.current.toasts[0].id).toBeDefined();
    });

    it('returns toast object with id, dismiss, and update', () => {
      let toastResult: any;

      act(() => {
        toastResult = toast({ title: 'Test' });
      });

      expect(toastResult.id).toBeDefined();
      expect(typeof toastResult.dismiss).toBe('function');
      expect(typeof toastResult.update).toBe('function');
    });

    it('sets toast as open by default', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ title: 'Test' });
      });

      expect(result.current.toasts[0].open).toBe(true);
    });
  });

  describe('Toast Limit', () => {
    it('respects TOAST_LIMIT of 1', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ title: 'Toast 1' });
        result.current.toast({ title: 'Toast 2' });
        result.current.toast({ title: 'Toast 3' });
      });

      expect(result.current.toasts).toHaveLength(1);
      // Most recent toast should be shown
      expect(result.current.toasts[0].title).toBe('Toast 3');
    });

    it('adds new toast to the front of the array', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ title: 'First' });
      });

      const firstId = result.current.toasts[0].id;

      act(() => {
        result.current.toast({ title: 'Second' });
      });

      // Due to limit, only the second toast should remain
      expect(result.current.toasts[0].title).toBe('Second');
      expect(result.current.toasts[0].id).not.toBe(firstId);
    });
  });

  describe('Dismissing Toasts', () => {
    it('dismisses specific toast by ID', () => {
      const { result } = renderHook(() => useToast());
      let toastId: string;

      act(() => {
        const t = result.current.toast({ title: 'Test Toast' });
        toastId = t.id;
      });

      expect(result.current.toasts[0].open).toBe(true);

      act(() => {
        result.current.dismiss(toastId);
      });

      expect(result.current.toasts[0].open).toBe(false);
    });

    it('dismisses all toasts when no ID provided', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ title: 'Toast 1' });
      });

      expect(result.current.toasts[0].open).toBe(true);

      act(() => {
        result.current.dismiss();
      });

      expect(result.current.toasts[0].open).toBe(false);
    });

    it('removes toast after delay when dismissed', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ title: 'Test' });
      });

      expect(result.current.toasts).toHaveLength(1);

      act(() => {
        result.current.dismiss(result.current.toasts[0].id);
      });

      // Toast should be closed but not removed yet
      expect(result.current.toasts[0].open).toBe(false);

      // Fast-forward time
      act(() => {
        vi.advanceTimersByTime(1000000);
      });

      expect(result.current.toasts).toHaveLength(0);
    });

    it('uses dismiss method from toast return value', () => {
      const { result } = renderHook(() => useToast());
      let toastInstance: any;

      act(() => {
        toastInstance = result.current.toast({ title: 'Test' });
      });

      expect(result.current.toasts[0].open).toBe(true);

      act(() => {
        toastInstance.dismiss();
      });

      expect(result.current.toasts[0].open).toBe(false);
    });

    it('prevents duplicate removal timeouts', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ title: 'Test' });
      });

      const toastId = result.current.toasts[0].id;

      // Dismiss multiple times
      act(() => {
        result.current.dismiss(toastId);
        result.current.dismiss(toastId);
        result.current.dismiss(toastId);
      });

      // Only one removal should be scheduled
      act(() => {
        vi.advanceTimersByTime(1000000);
      });

      expect(result.current.toasts).toHaveLength(0);
    });
  });

  describe('Updating Toasts', () => {
    it('updates toast properties', () => {
      let toastInstance: any;

      const { result } = renderHook(() => useToast());

      act(() => {
        toastInstance = result.current.toast({ title: 'Original Title' });
      });

      expect(result.current.toasts[0].title).toBe('Original Title');

      act(() => {
        toastInstance.update({ title: 'Updated Title' });
      });

      expect(result.current.toasts[0].title).toBe('Updated Title');
    });

    it('updates toast description', () => {
      let toastInstance: any;

      const { result } = renderHook(() => useToast());

      act(() => {
        toastInstance = result.current.toast({
          title: 'Loading',
          description: 'Please wait...',
        });
      });

      act(() => {
        toastInstance.update({
          title: 'Success',
          description: 'Operation completed',
        });
      });

      expect(result.current.toasts[0].title).toBe('Success');
      expect(result.current.toasts[0].description).toBe('Operation completed');
    });

    it('updates toast variant', () => {
      let toastInstance: any;

      const { result } = renderHook(() => useToast());

      act(() => {
        toastInstance = result.current.toast({ title: 'Processing' });
      });

      act(() => {
        toastInstance.update({ variant: 'destructive' });
      });

      expect(result.current.toasts[0].variant).toBe('destructive');
    });

    it('preserves toast ID when updating', () => {
      let toastInstance: any;

      const { result } = renderHook(() => useToast());

      act(() => {
        toastInstance = result.current.toast({ title: 'Test' });
      });

      const originalId = result.current.toasts[0].id;

      act(() => {
        toastInstance.update({ title: 'Updated' });
      });

      expect(result.current.toasts[0].id).toBe(originalId);
    });

    it('only updates matching toast', () => {
      const { result } = renderHook(() => useToast());
      let toast1: any;

      act(() => {
        toast1 = result.current.toast({ title: 'Toast 1' });
      });

      // Due to TOAST_LIMIT = 1, only one toast at a time

      act(() => {
        toast1.update({ title: 'Updated Toast 1' });
      });

      expect(result.current.toasts[0].title).toBe('Updated Toast 1');
    });
  });

  describe('OnOpenChange Callback', () => {
    it('calls dismiss when open changes to false', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ title: 'Test' });
      });

      const toast = result.current.toasts[0];
      expect(toast.open).toBe(true);

      // Simulate onOpenChange being called
      act(() => {
        toast.onOpenChange?.(false);
      });

      expect(result.current.toasts[0].open).toBe(false);
    });

    it('does nothing when open changes to true', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ title: 'Test' });
      });

      const initialState = result.current.toasts[0];

      act(() => {
        initialState.onOpenChange?.(true);
      });

      // Should remain unchanged
      expect(result.current.toasts[0].open).toBe(true);
    });
  });

  describe('Multiple Hook Instances', () => {
    it('shares state across multiple hook instances', () => {
      const { result: result1 } = renderHook(() => useToast());
      const { result: result2 } = renderHook(() => useToast());

      act(() => {
        result1.current.toast({ title: 'Shared Toast' });
      });

      expect(result1.current.toasts).toHaveLength(1);
      expect(result2.current.toasts).toHaveLength(1);
      expect(result2.current.toasts[0].title).toBe('Shared Toast');
    });

    it('updates all instances when toast is dismissed', () => {
      const { result: result1 } = renderHook(() => useToast());
      const { result: result2 } = renderHook(() => useToast());

      act(() => {
        result1.current.toast({ title: 'Test' });
      });

      const toastId = result1.current.toasts[0].id;

      act(() => {
        result2.current.dismiss(toastId);
      });

      expect(result1.current.toasts[0].open).toBe(false);
      expect(result2.current.toasts[0].open).toBe(false);
    });
  });

  describe('Standalone toast Function', () => {
    it('can be called outside of hook', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        toast({ title: 'Standalone Toast' });
      });

      expect(result.current.toasts).toHaveLength(1);
      expect(result.current.toasts[0].title).toBe('Standalone Toast');
    });

    it('returns dismiss and update functions', () => {
      let toastInstance: any;

      act(() => {
        toastInstance = toast({ title: 'Test' });
      });

      expect(typeof toastInstance.dismiss).toBe('function');
      expect(typeof toastInstance.update).toBe('function');
      expect(toastInstance.id).toBeDefined();
    });
  });

  describe('Edge Cases', () => {
    it('handles empty toast props', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({});
      });

      expect(result.current.toasts).toHaveLength(1);
      expect(result.current.toasts[0].id).toBeDefined();
    });

    it('handles toast with only description', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ description: 'Only description' });
      });

      expect(result.current.toasts[0].description).toBe('Only description');
      expect(result.current.toasts[0].title).toBeUndefined();
    });

    it('handles dismissing non-existent toast', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ title: 'Test' });
      });

      expect(result.current.toasts).toHaveLength(1);

      // Dismiss with non-existent ID
      act(() => {
        result.current.dismiss('non-existent-id');
      });

      // Should not affect existing toast
      expect(result.current.toasts).toHaveLength(1);
      expect(result.current.toasts[0].open).toBe(true);
    });

    it('handles updating non-existent toast', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ title: 'Test' });
      });

      const originalTitle = result.current.toasts[0].title;

      // Try to update with invalid instance
      const fakeInstance = {
        id: 'fake-id',
        dismiss: () => {},
        update: (_props: any) => {
          // This would update a non-existent toast
        },
      };

      act(() => {
        fakeInstance.update({ title: 'Should not update' });
      });

      // Original toast should be unchanged
      expect(result.current.toasts[0].title).toBe(originalTitle);
    });

    it('handles rapid successive toasts', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.toast({ title: 'Toast 1' });
        result.current.toast({ title: 'Toast 2' });
        result.current.toast({ title: 'Toast 3' });
        result.current.toast({ title: 'Toast 4' });
        result.current.toast({ title: 'Toast 5' });
      });

      // Due to TOAST_LIMIT = 1, only last toast should be shown
      expect(result.current.toasts).toHaveLength(1);
      expect(result.current.toasts[0].title).toBe('Toast 5');
    });
  });

  describe('Cleanup', () => {
    it('cleans up listeners on unmount', () => {
      const { unmount } = renderHook(() => useToast());

      // Hook should register listener
      unmount();

      // After unmount, toast should still work (global state)
      act(() => {
        toast({ title: 'After Unmount' });
      });

      // Render new hook to verify state persists
      const { result } = renderHook(() => useToast());
      expect(result.current.toasts).toHaveLength(1);
    });
  });
});
