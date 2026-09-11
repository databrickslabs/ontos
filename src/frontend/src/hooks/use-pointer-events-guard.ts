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
 * It ALSO clears a stranded `aria-hidden`/`inert` left on the app root (or any
 * direct body child) by Radix's focus scope / react-remove-scroll: when a
 * Dialog opens it marks its siblings `aria-hidden`/`inert` to trap focus, and
 * if the trigger is unmounted/re-rendered during close (e.g. the underlying
 * list refetches on save), the cleanup can race and leave <#root> inert — the
 * whole app then swallows clicks ("can't click anything after creating a
 * concept") until the next render. Symptom in console: "Blocked aria-hidden on
 * an element because its descendant retained focus … Ancestor with aria-hidden:
 * <div#root>". We only clear it when no overlay is actually open.
 *
 * It also re-runs the check on every route change, because users typically
 * navigate as the next action after the freeze starts.
 */
export function usePointerEventsGuard(): void {
  const location = useLocation();

  useEffect(() => {
    if (typeof document === 'undefined') return;

    const body = document.body;

    // Selector for a genuinely-open MODAL overlay (dialog/menu/listbox/popper).
    // Deliberately specific: it must NOT match non-modal open widgets like
    // Collapsibles/Accordions/Tabs, which also carry data-state="open" but never
    // lock the body or mark siblings inert. Using a broad [data-state="open"]
    // here would make the guard think an overlay is always open (the app root is
    // full of open collapsibles) and never clear a stranded lock.
    const MODAL_OVERLAY_SELECTOR = [
      '[role="dialog"][data-state="open"]',
      '[role="alertdialog"][data-state="open"]',
      '[role="menu"][data-state="open"]',
      '[role="listbox"][data-state="open"]',
      '[data-radix-focus-guard]',
      '[data-radix-popper-content-wrapper] [data-state="open"]',
    ].join(',');

    const hasOpenRadixOverlay = (): boolean =>
      Boolean(document.querySelector(MODAL_OVERLAY_SELECTOR));

    // Clear a stranded aria-hidden/inert that Radix left on a direct child of
    // <body> (the app root, portals, etc.) when no overlay is actually open.
    // While a dialog is open Radix legitimately marks siblings hidden/inert, so
    // we stay out of the way then.
    const clearStuckHidden = (): void => {
      if (hasOpenRadixOverlay()) return;
      for (const el of Array.from(body.children) as HTMLElement[]) {
        const markedHidden = el.getAttribute('aria-hidden') === 'true';
        const markedInert = el.hasAttribute('inert');
        if (!markedHidden && !markedInert) continue;
        // Skip only if this subtree still hosts a genuine MODAL overlay — a
        // broad [data-state="open"] would match the many open Collapsibles the
        // app root always contains and wrongly keep the root inert forever.
        if (el.querySelector(MODAL_OVERLAY_SELECTOR)) continue;
        if (markedHidden) el.removeAttribute('aria-hidden');
        if (markedInert) el.removeAttribute('inert');
      }
    };

    const clearIfStuck = (): void => {
      if (body.style.pointerEvents === 'none' && !hasOpenRadixOverlay()) {
        body.style.pointerEvents = '';
      }
      clearStuckHidden();
    };

    // Observe changes to the body's `style` attribute AND to aria-hidden/inert
    // on the body subtree so we react the moment Radix writes the lock.
    const observer = new MutationObserver(() => {
      // Defer one frame so any concurrently-mounting overlay has a chance
      // to mark itself open before we make a decision.
      window.requestAnimationFrame(clearIfStuck);
    });
    observer.observe(body, { attributes: true, attributeFilter: ['style'] });
    // Separate observer for aria-hidden/inert on the body's direct children.
    const hiddenObserver = new MutationObserver(() => {
      window.requestAnimationFrame(clearStuckHidden);
    });
    for (const el of Array.from(body.children)) {
      hiddenObserver.observe(el, { attributes: true, attributeFilter: ['aria-hidden', 'inert'] });
    }

    // Run once on mount in case we landed on the page already stuck.
    window.requestAnimationFrame(clearIfStuck);

    // Interval watchdog — the guarantee. A MutationObserver only fires on the
    // attribute CHANGE; but Radix's aria-hidden module can set aria-hidden on
    // #root while a focus-guard is momentarily present (so our handler skips),
    // then remove the guard WITHOUT re-touching aria-hidden — so the observer
    // never re-fires and #root stays inert for many seconds (observed: 8s+ after
    // creating a concept = the "can't click anything" freeze). A cheap periodic
    // re-check recovers within one tick no matter how the leak happened. The
    // body-writes MutationObserver above still gives the instant path; this is
    // the floor.
    const watchdog = window.setInterval(clearIfStuck, 250);

    return () => { observer.disconnect(); hiddenObserver.disconnect(); window.clearInterval(watchdog); };
  }, []);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    // After a navigation, give React + Radix a frame to settle, then double-
    // check the body. This catches the common case of clicking a <Link>
    // from inside (or just after closing) an overlay.
    const body = document.body;
    const MODAL_OVERLAY_SELECTOR = [
      '[role="dialog"][data-state="open"]',
      '[role="alertdialog"][data-state="open"]',
      '[role="menu"][data-state="open"]',
      '[role="listbox"][data-state="open"]',
      '[data-radix-focus-guard]',
    ].join(',');
    const id = window.requestAnimationFrame(() => {
      if (document.querySelector(MODAL_OVERLAY_SELECTOR)) return;
      if (body.style.pointerEvents === 'none') body.style.pointerEvents = '';
      // Also clear a stranded aria-hidden/inert on body children after nav
      // (skip subtrees that still host a genuine modal overlay, not mere
      // open Collapsibles).
      for (const el of Array.from(body.children) as HTMLElement[]) {
        if (el.querySelector(MODAL_OVERLAY_SELECTOR)) continue;
        if (el.getAttribute('aria-hidden') === 'true') el.removeAttribute('aria-hidden');
        if (el.hasAttribute('inert')) el.removeAttribute('inert');
      }
    });
    return () => window.cancelAnimationFrame(id);
  }, [location.pathname, location.search]);
}

export default usePointerEventsGuard;
