import { create } from 'zustand';
// Removed useApi import as we use direct fetch below
import { Notification } from '@/types/notification';

interface NotificationsState {
  notifications: Notification[];
  unreadCount: number;
  isLoading: boolean;
  error: string | null;
  fetchNotifications: () => Promise<void>;
  refreshNotifications: () => void; // Simple alias to trigger fetch
  markAsRead: (notificationId: string) => Promise<void>;
  deleteNotification: (notificationId: string) => Promise<void>;
  startPolling: () => void; // Action to start polling
  stopPolling: () => void; // Action to stop polling
  resumePollingInterval: () => void; // Internal: (re)start the interval + fetch now
  pausePollingInterval: () => void; // Internal: clear the interval, keep intent
}

// --- API Helper Functions (using fetch directly) ---
// Base URL - adjust if needed, or use environment variables
const API_BASE_URL = ''; // Assuming API routes start from the root

const apiGet = async <T>(endpoint: string): Promise<{ data?: T, error?: string }> => {
    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`);
        if (!response.ok) {
            throw new Error(`API Error: ${response.status} ${response.statusText}`);
        }
        // Handle potential empty response for GET (though list usually returns [])
        const text = await response.text();
        const data: T = text ? JSON.parse(text) : []; // Default to empty array for lists
        return { data };
    } catch (error: any) {
         console.error("[Store] API Error fetching", API_BASE_URL, endpoint, ":", error);
         return { error: error.message || 'Failed to fetch' };
    }
};

const apiPut = async (endpoint: string): Promise<{ error?: string }> => {
     try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, { method: 'PUT' });
        if (!response.ok) {
            throw new Error(`API Error: ${response.status} ${response.statusText}`);
        }
        return {}; // Success
    } catch (error: any) {
         console.error("[Store] API Error PUT", API_BASE_URL, endpoint, ":", error);
         return { error: error.message || 'Failed to update' };
    }
};

const apiDelete = async (endpoint: string): Promise<{ error?: string }> => {
     try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, { method: 'DELETE' });
         if (!response.ok && response.status !== 204) { // Allow 204 No Content
            throw new Error(`API Error: ${response.status} ${response.statusText}`);
        }
        return {}; // Success
    } catch (error: any) {
         console.error("[Store] API Error DELETE", API_BASE_URL, endpoint, ":", error);
         return { error: error.message || 'Failed to delete' };
    }
};

// Variable to hold the interval ID
let pollingIntervalId: NodeJS.Timeout | null = null;
const POLLING_INTERVAL = 60 * 1000; // 60 seconds

// Whether the app wants polling active (set by start/stopPolling). We only run
// the actual interval while the tab is visible so a backgrounded tab stops
// hitting /api/notifications — otherwise the constant traffic keeps the
// Lakebase compute from ever scaling down to idle.
let pollingDesired = false;
let visibilityHandler: (() => void) | null = null;

// Guard flag to prevent concurrent fetches
let isFetching = false;
// Store the current fetch promise so we can await it
let currentFetchPromise: Promise<void> | null = null;

export const useNotificationsStore = create<NotificationsState>((set, get) => ({
  notifications: [],
  unreadCount: 0,
  isLoading: false,
  error: null,

  fetchNotifications: async () => {
    // If a fetch is already in progress, wait for it to complete
    // Don't set loading state since we're just waiting
    if (isFetching && currentFetchPromise) {
      console.debug('[NotificationsStore] Fetch already in progress, waiting for completion');
      await currentFetchPromise;
      return;
    }
    
    // Set loading state immediately before creating the promise
    set({ isLoading: true, error: null });
    
    // Create the fetch promise
    const fetchPromise = (async () => {
      isFetching = true;
      
      try {
        
        const response = await apiGet<Notification[]>('/api/notifications');

        if (response.error || !response.data) {
          throw new Error(response.error || 'Failed to fetch notifications: No data received');
        }

        const fetchedNotifications = response.data;
        const unread = fetchedNotifications.filter(n => !n.read).length;

        // Always update with fetched data and reset loading state
        set({
          notifications: fetchedNotifications,
          unreadCount: unread,
          isLoading: false,
          error: null,
        });

      } catch (error: any) {
        console.error("Error fetching notifications:", error);
        const errorMessage = error.message || 'An unknown error occurred';
        // Always update error state and reset loading
        set({ isLoading: false, error: errorMessage });
      } finally {
        // Always reset the fetch guard flag and promise
        isFetching = false;
        currentFetchPromise = null;
      }
    })();
    
    // Store the promise so other calls can wait for it
    currentFetchPromise = fetchPromise;
    return fetchPromise;
  },

  refreshNotifications: () => {
    // Simply call fetchNotifications to refresh the data
    get().fetchNotifications();
  },

  markAsRead: async (notificationId: string) => {
    const originalNotifications = get().notifications;
    const notificationToMark = originalNotifications.find(n => n.id === notificationId);
    const originalUnreadCount = get().unreadCount;

    // Optimistic UI update
    set(state => ({
        notifications: state.notifications.map(n =>
            n.id === notificationId ? { ...n, read: true } : n
        ),
        unreadCount: notificationToMark && !notificationToMark.read
                     ? Math.max(0, state.unreadCount - 1)
                     : state.unreadCount,
    }));

    try {
       const response = await apiPut(`/api/notifications/${notificationId}/read`);
       if (response.error) {
            throw new Error(response.error);
       }
    } catch (error: any) {
       console.error("Error marking notification", notificationId, "as read:", error);
       // Revert optimistic update on error
       set({
            notifications: originalNotifications,
            unreadCount: originalUnreadCount,
            error: `Failed to mark as read: ${error.message}`
       });
       // Optionally trigger a toast notification here
    }
  },

  deleteNotification: async (notificationId: string) => {
    const originalNotifications = get().notifications;
    const notificationToDelete = originalNotifications.find(n => n.id === notificationId);
    const originalUnreadCount = get().unreadCount;

    // Optimistic UI update
    set(state => ({
        notifications: state.notifications.filter(n => n.id !== notificationId),
        unreadCount: notificationToDelete && !notificationToDelete.read
                     ? Math.max(0, state.unreadCount - 1)
                     : state.unreadCount,
    }));

    try {
       const response = await apiDelete(`/api/notifications/${notificationId}`);
        if (response.error) {
            throw new Error(response.error);
        }
       // Successfully deleted on backend
    } catch (error: any) {
        console.error("Error deleting notification", notificationId, ":", error);
        // Revert optimistic update on error
        set({
            notifications: originalNotifications,
            unreadCount: originalUnreadCount,
            error: `Failed to delete: ${error.message}`
        });
         // Optionally trigger a toast notification here
    }
  },
  
  // --- Polling Actions ---
  startPolling: () => {
      pollingDesired = true;

      // Pause the interval whenever the tab is hidden and resume (with an
      // immediate refresh) when it becomes visible again. Registered once.
      if (visibilityHandler === null && typeof document !== 'undefined') {
          visibilityHandler = () => {
              if (!pollingDesired) return;
              if (document.visibilityState === 'visible') {
                  get().resumePollingInterval();
              } else {
                  get().pausePollingInterval();
              }
          };
          document.addEventListener('visibilitychange', visibilityHandler);
      }

      // Only run the interval if the tab is currently visible; otherwise wait
      // for the visibility handler to start it when the user returns.
      if (typeof document === 'undefined' || document.visibilityState === 'visible') {
          get().resumePollingInterval();
      }
  },

  // Start the interval and fetch immediately. Idempotent — clears any existing
  // interval first so we never end up with two running.
  resumePollingInterval: () => {
      if (pollingIntervalId) {
          clearInterval(pollingIntervalId);
          pollingIntervalId = null;
      }
      pollingIntervalId = setInterval(() => {
          get().fetchNotifications();
      }, POLLING_INTERVAL);
      // Fetch immediately so returning to the tab shows fresh data at once.
      get().fetchNotifications();
  },

  // Stop the interval but keep pollingDesired/listener so we resume on focus.
  pausePollingInterval: () => {
      if (pollingIntervalId) {
          clearInterval(pollingIntervalId);
          pollingIntervalId = null;
      }
  },

  stopPolling: () => {
      pollingDesired = false;
      get().pausePollingInterval();
      if (visibilityHandler !== null && typeof document !== 'undefined') {
          document.removeEventListener('visibilitychange', visibilityHandler);
          visibilityHandler = null;
      }
  },
}));

// --- Auto-start Polling (Optional) ---
// This starts polling as soon as the store is initialized.
// Alternatively, call startPolling() from a main component (e.g., App.tsx) after user logs in.
// useNotificationsStore.getState().startPolling(); 


// Previous notes kept for context:
// Note: We need a type definition for Notification
// Create src/types/notification.ts if it doesn't exist
/* Example src/types/notification.ts
export interface Notification {
  id: string;
  type: 'info' | 'success' | 'warning' | 'error' | 'action_required';
  title: string;
  subtitle?: string | null;
  description?: string | null;
  link?: string | null; // Added optional link field
  created_at: string; // ISO date string
  read: boolean;
  can_delete: boolean;
  recipient?: string | null;
  action_type?: string | null;
  action_payload?: Record<string, any> | null;
}
*/ 