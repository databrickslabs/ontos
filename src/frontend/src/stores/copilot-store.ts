import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export interface CopilotEntity {
  type: string;
  name: string;
  id: string;
}

export interface CopilotPageContext {
  pageName: string;
  pageUrl: string;
  featureId?: string;
  selectedEntity?: CopilotEntity;
}

export const COPILOT_MIN_WIDTH = 320;
export const COPILOT_MAX_WIDTH = 900;
export const COPILOT_DEFAULT_WIDTH = 400;

interface CopilotState {
  isOpen: boolean;
  pageContext: CopilotPageContext | null;
  panelWidth: number;
  actions: {
    togglePanel: () => void;
    openPanel: () => void;
    closePanel: () => void;
    setPanelWidth: (w: number) => void;
    setContext: (pageName: string, pageUrl: string, selectedEntity?: CopilotEntity, featureId?: string) => void;
    clearContext: () => void;
  };
}

// `isOpen` is intentionally kept on its own legacy localStorage key
// (`copilot-sidebar-visited`) so the first-run "auto-open until dismissed"
// behavior is preserved. Only the resizable width is persisted via zustand.
const VISITED_KEY = 'copilot-sidebar-visited';

const clampWidth = (w: number): number =>
  Math.min(COPILOT_MAX_WIDTH, Math.max(COPILOT_MIN_WIDTH, Math.round(w)));

export const useCopilotStore = create<CopilotState>()(
  persist(
    (set) => ({
      isOpen: localStorage.getItem(VISITED_KEY) !== 'true',
      pageContext: null,
      panelWidth: COPILOT_DEFAULT_WIDTH,
      actions: {
        togglePanel: () => set((state) => {
          if (state.isOpen) localStorage.setItem(VISITED_KEY, 'true');
          return { isOpen: !state.isOpen };
        }),
        openPanel: () => set({ isOpen: true }),
        closePanel: () => {
          localStorage.setItem(VISITED_KEY, 'true');
          set({ isOpen: false });
        },
        setPanelWidth: (w) => set({ panelWidth: clampWidth(w) }),
        setContext: (pageName, pageUrl, selectedEntity, featureId) =>
          set({ pageContext: { pageName, pageUrl, featureId, selectedEntity } }),
        clearContext: () => set({ pageContext: null }),
      },
    }),
    {
      name: 'copilot-panel-storage',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ panelWidth: state.panelWidth }),
      merge: (persisted, current) => {
        const p = (persisted ?? {}) as Partial<CopilotState>;
        const width = typeof p.panelWidth === 'number' ? clampWidth(p.panelWidth) : current.panelWidth;
        return { ...current, panelWidth: width };
      },
    }
  )
);
