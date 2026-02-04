import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { FeatureMaturity } from '@/config/features';

interface FeatureVisibilityState {
  showBeta: boolean;
  showAlpha: boolean;
  actions: {
    toggleBeta: () => void;
    toggleAlpha: () => void;
  };
  // Computed property derived from state
  allowedMaturities: FeatureMaturity[];
}

export const useFeatureVisibilityStore = create<FeatureVisibilityState>()(
  persist(
    (set, _get) => ({
      showBeta: true,
      showAlpha: true,
      // Compute allowedMaturities whenever state changes
      allowedMaturities: ['ga'], // Initial value

      actions: {
        toggleBeta: () => set((state) => {
            const newShowBeta = !state.showBeta;
            const maturities: FeatureMaturity[] = ['ga'];
            if (newShowBeta) maturities.push('beta');
            if (state.showAlpha) maturities.push('alpha');
            return { showBeta: newShowBeta, allowedMaturities: maturities };
        }),
        toggleAlpha: () => set((state) => {
            const newShowAlpha = !state.showAlpha;
            const maturities: FeatureMaturity[] = ['ga'];
            if (state.showBeta) maturities.push('beta');
            if (newShowAlpha) maturities.push('alpha');
            return { showAlpha: newShowAlpha, allowedMaturities: maturities };
        }),
      },
      // This part recalculates allowedMaturities on initialization from storage
      // Note: We are deriving allowedMaturities directly within the state/actions
      // for simplicity and immediate update upon toggle.
      // Alternatively, this could be a separate selector outside the persisted state.
    }),
    {
      name: 'feature-visibility-storage', // Name for localStorage key
      storage: createJSONStorage(() => localStorage), // Use localStorage
      // Only persist the toggle states, not the derived array or actions
      partialize: (state) => ({
        showBeta: state.showBeta,
        showAlpha: state.showAlpha,
      }),
       // Recompute allowedMaturities after rehydration from storage
        onRehydrateStorage: () => (state, _error) => {
            if (state) {
                 const maturities: FeatureMaturity[] = ['ga'];
                if (state.showBeta) maturities.push('beta');
                if (state.showAlpha) maturities.push('alpha');
                state.allowedMaturities = maturities;
             }
        }
    }
  )
);

// Export actions separately for easier usage if needed, although direct usage is fine too
export const useFeatureVisibilityActions = () => useFeatureVisibilityStore((state) => state.actions);