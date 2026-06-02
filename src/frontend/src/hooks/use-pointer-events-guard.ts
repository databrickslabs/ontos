import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/**
 * Defensive safety net for a well-known Radix UI race where
 * `document.body.style.pointer-events` is left stuck at `none` after a modal
 * overlay (Dialog, DropdownMenu, Popover, Select, AlertDialog, …) closes —
 * most reliably reproduced by opening a Dialog from inside a DropdownMenu and
 * then closing the Dialog (radix-ui/primitives#1241 and similar reports).
 * When that happens, every click on the page is dropped at the body element
 * before reaching React Router's <Link> or any handler, so the UI looks
 * frozen even though React is fine.
 *
 * This hook installs a MutationObserver on <body> that clears a stranded
 * `pointer-events: none` only when no Radix overlay is actually open. It
 * therefore cannot interfere with legitimately open dialogs/menus — those
 * still get to lock the body while they're up.
 *
 * It also re-runs the check on every route change, because users typically
 * navigate as the next action after the freeze starts.
 */
export function usePointerEventsGuard(): void {
  const location = useLocation();

  useEffect(() => {
    if (typeof document === 'undefined') return;

    const body = document.body;

    const hasOpenRadixOverlay = (): boolean => {
      // Any Radix primitive in modal mode renders content with
      // data-state="open" inside a portal. We treat the presence of any
      // such open node as "an overlay is legitimately controlling the body
      // pointer-events lock" and stay out of the way.
      return Boolean(
        document.querySelector(
          [
            '[role="dialog"][data-state="open"]',
            '[role="alertdialog"][data-state="open"]',
            '[role="menu"][data-state="open"]',
            '[role="listbox"][data-state="open"]',
            '[data-radix-focus-guard]',
            '[data-radix-popper-content-wrapper] [data-state="open"]',
          ].join(','),
        ),
      );
    };

    const clearIfStuck = (): void => {
      if (body.style.pointerEvents === 'none' && !hasOpenRadixOverlay()) {
        body.style.pointerEvents = '';
      }
    };

    // Observe changes to the body's `style` attribute so we react the moment
    // Radix (or anything else) writes `pointer-events: none` onto it.
    const observer = new MutationObserver(() => {
      // Defer one frame so any concurrently-mounting overlay has a chance
      // to mark itself open before we make a decision.
      window.requestAnimationFrame(clearIfStuck);
    });
    observer.observe(body, { attributes: true, attributeFilter: ['style'] });

    // Run once on mount in case we landed on the page already stuck.
    window.requestAnimationFrame(clearIfStuck);

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    // After a navigation, give React + Radix a frame to settle, then double-
    // check the body. This catches the common case of clicking a <Link>
    // from inside (or just after closing) an overlay.
    const body = document.body;
    const id = window.requestAnimationFrame(() => {
      if (body.style.pointerEvents === 'none') {
        const open = document.querySelector(
          [
            '[role="dialog"][data-state="open"]',
            '[role="alertdialog"][data-state="open"]',
            '[role="menu"][data-state="open"]',
            '[role="listbox"][data-state="open"]',
            '[data-radix-focus-guard]',
          ].join(','),
        );
        if (!open) body.style.pointerEvents = '';
      }
    });
    return () => window.cancelAnimationFrame(id);
  }, [location.pathname, location.search]);
}

export default usePointerEventsGuard;
