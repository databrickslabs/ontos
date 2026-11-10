import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

/** Page sizes offered for "my assets" in Publish on the Essentials home. */
export const PUBLISH_PAGE_SIZES = [10, 25, 50] as const;
export type PublishPageSize = (typeof PUBLISH_PAGE_SIZES)[number];
export const DEFAULT_PUBLISH_PAGE_SIZE: PublishPageSize = 10;

interface EssentialsHomePreferencesState {
  publishPageSize: PublishPageSize;
  setPublishPageSize: (size: number) => void;
}

const toPageSize = (size: unknown): PublishPageSize =>
  PUBLISH_PAGE_SIZES.includes(size as PublishPageSize)
    ? (size as PublishPageSize)
    : DEFAULT_PUBLISH_PAGE_SIZE;

/** Essentials home preferences, kept in the browser like the other UI preferences. */
export const useEssentialsHomePreferencesStore = create<EssentialsHomePreferencesState>()(
  persist(
    (set) => ({
      publishPageSize: DEFAULT_PUBLISH_PAGE_SIZE,
      setPublishPageSize: (size) => set({ publishPageSize: toPageSize(size) }),
    }),
    {
      name: 'essentials-home-preferences',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ publishPageSize: state.publishPageSize }),
      merge: (persisted, current) => ({
        ...current,
        publishPageSize: toPageSize(
          (persisted as Partial<EssentialsHomePreferencesState> | undefined)?.publishPageSize,
        ),
      }),
    },
  ),
);
