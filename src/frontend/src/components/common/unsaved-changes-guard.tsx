import { useEffect } from 'react';

interface UnsavedChangesGuardProps {
  /** When true, tab close / reload / address-bar nav will prompt via native beforeunload. */
  isDirty: boolean;
}

/**
 * Drop-in guard that warns the user when leaving the tab with unsaved changes.
 *
 * Currently installs only a `beforeunload` listener (covers reload, tab close,
 * and address-bar navigation). In-app navigation via `<Link>` is NOT blocked
 * because the app uses the legacy declarative `BrowserRouter`; react-router's
 * `useBlocker` only works under a Data Router (`createBrowserRouter` +
 * `RouterProvider`). Upgrade the root router to enable in-app guard.
 *
 * Until then, the visible sticky action bar (Save + Cancel/Revert) gives users
 * a clear way to undo pending edits without leaving the page.
 */
export default function UnsavedChangesGuard({ isDirty }: UnsavedChangesGuardProps) {
  useEffect(() => {
    if (!isDirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Modern browsers ignore custom text; setting returnValue triggers the
      // native confirm prompt.
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  return null;
}
