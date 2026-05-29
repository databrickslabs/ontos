# PRD: Consistent Save / Cancel and Dirty-Tracking Across Settings Form Sub-Views

## Problem Statement

After the recent split of the Settings page into focused sub-views (one route per concern: `settings-general`, `settings-ui`, `settings-jobs`, `settings-git`, `settings-delivery`, `settings-search`, etc.), the editing UX inside each form-style sub-view drifted apart. Concretely, today:

- Save button placement is inconsistent. Most pages render an ad-hoc `pt-4` block at the **bottom-right** of the form (`general-settings.tsx`, `ui-customization-settings.tsx`, `git-settings.tsx`, `delivery-settings.tsx`). `jobs-settings.tsx` was recently changed to render a **sticky right-aligned** bar (a POC from a prior iteration). `search-config-editor.tsx` follows yet another convention. There is no single rule.
- **There is no Cancel button anywhere on the form-style settings sub-views.** A user who starts editing has no first-class way to discard local edits short of reloading the page or backing out of the route (which silently loses changes).
- **There is no dirty tracking.** Pages compare nothing against their last-loaded snapshot. The Save button is enabled unconditionally, so users routinely hit Save with no real changes; conversely, the page never indicates that there are pending edits.
- **There is no navigation guard.** Closing the tab, hitting reload, typing a new URL, or clicking a sidebar link while edits are pending all silently drop the changes. There is no `beforeunload` listener and no in-app prompt anywhere in the Settings area.

The result is a Settings experience that feels rough relative to the rest of the app, with measurable foot-guns (lost edits, accidental no-op saves) and visible inconsistency in alignment and labelling between very similar pages. It also blocks future polish work — every new settings sub-view today reinvents this same minor scaffolding, and reinvents it slightly differently.

## Solution

Introduce a single shared editing convention for **form-style** settings sub-views and apply it uniformly:

- Every form-style sub-view ends with a **static** Save / Cancel action block at the **bottom of the form, left-aligned**. The block is part of the normal page flow, not a sticky/floating bar.
- Each page tracks its own dirty state by comparing the current edit state against a snapshot taken at load time (and refreshed on successful save). Save and Cancel are disabled when the form is not dirty (Save is additionally disabled when the form is invalid or while a save request is in flight).
- Pages install a browser-level `beforeunload` warning while dirty, so tab close, reload, and typed-URL navigation prompt the user via the native browser dialog.
- The convention is delivered as **one component** (`SettingsFormActions`) and **one hook** (`useDirtyForm`), plus the already-existing `UnsavedChangesGuard` (built during the prior jobs-settings POC, currently only renders the `beforeunload` listener). All three live in shared component / hook directories and are reused across every migrated page.

The change is **UI only**: no backend changes, no API changes, no state model changes beyond local React state and snapshots. List/CRUD-style settings sub-views (where edits happen inside Dialogs that already have their own Save/Cancel) are explicitly out of scope.

In-app router blocking (intercepting clicks on `<Link>`s in the sidebar) is also out of scope: the app currently uses `BrowserRouter` (declarative router) and react-router v6's `useBlocker` requires `createBrowserRouter` + `RouterProvider`. Migrating the root router is a separate, larger refactor; the visible static action block plus the `beforeunload` listener are judged sufficient for this pass.

## User Stories

### Editing-flow stories

1. As a settings admin editing the General Settings form, I want to see Save and Cancel buttons in the same place on every settings sub-view, so that muscle memory carries between pages and I never have to hunt for the action.
2. As a settings admin who has made changes to a form, I want a Save button that is clearly enabled (and disabled when I have no pending changes), so that I can tell at a glance whether the form has unsaved edits.
3. As a settings admin who has made changes to a form, I want a Cancel button that reverts every field on the form back to the values that were loaded from the server, so that I can abandon a half-made edit without reloading the page.
4. As a settings admin who has just saved successfully, I want Save and Cancel to immediately return to their disabled state, so that I can see the change has been persisted and I do not accidentally re-save the same payload.
5. As a settings admin whose save request fails, I want my edits to stay in the form and Save / Cancel to remain enabled, so that I can correct and retry without re-typing.
6. As a settings admin filling out a form with required fields, I want Save to remain disabled while the form is invalid (even if it is dirty), so that I cannot submit a bad payload and trigger a backend validation error.

### Navigation-guard stories

7. As a settings admin with unsaved changes on a form, I want the browser to prompt me before I close the tab, hit reload, or type a different URL, so that I do not silently lose work.
8. As a settings admin with no pending changes, I want navigation to proceed silently with no prompt, so that the guard does not get in my way during normal browsing.
9. As a settings admin, I want the prompt to disappear immediately after I click Save successfully, so that the very next page navigation is unobstructed.
10. As a settings admin, I accept that clicking a sidebar link will still silently navigate me away in this phase (because the app is not yet on a Data Router and in-app blocking is out of scope), so that the change can ship as a UI-only update.

### Visual / layout stories

11. As a settings admin on a narrow viewport, I want Save / Cancel to be left-aligned at the bottom of the form, so that the primary action is closer to the natural reading start of the page and not clipped by the right edge.
12. As a settings admin, I want the action block to always be visible at the bottom of the form (not a floating sticky bar), so that the layout is predictable and matches the rest of the app shell.
13. As a settings admin, I want Save to be the primary (filled) button and Cancel to be the secondary (outline) button, so that the destructive action is visually de-emphasized.
14. As a settings admin saving a form, I want a spinner inside the Save button while the request is in flight, so that I can see the action is being processed.

### Per-page parity stories

15. As a settings admin on the **General Settings** sub-view, I want the same Save / Cancel / dirty-tracking behavior, so that this page no longer differs from the others.
16. As a settings admin on the **UI Customization** sub-view, I want the same Save / Cancel / dirty-tracking behavior, including correct snapshot tracking for the four current fields (i18n toggle, logo URL, About content, custom CSS).
17. As a settings admin on the **Git Settings** sub-view, I want the same Save / Cancel / dirty-tracking behavior across both the Git-connection form and any inline sub-forms on the page.
18. As a settings admin on the **Delivery Settings** sub-view, I want the same Save / Cancel / dirty-tracking behavior, including the multiple toggle/text fields that compose the delivery configuration.
19. As a settings admin on the **Jobs** sub-view, I want the existing right-aligned sticky bar replaced with the new static left-aligned action block, so that this page conforms to the same convention as the other forms even though it was migrated first.
20. As a settings admin on the **Search Configuration** sub-view, I want the same Save / Cancel / dirty-tracking behavior wrapping the nested editor controls, so that the page-level save matches every other settings form.

## Implementation Decisions

### Shared modules to add

- A new **`useDirtyForm` hook** that encapsulates dirty detection. Inputs: a function that builds a stable snapshot key from the current edit state, and the value of the last-loaded snapshot key. Outputs: `isDirty` (boolean) and helpers to update the stored snapshot key (after a successful save). The hook is the only place in the codebase that defines what "dirty" means; pages do not roll their own equality. The hook is a deep module in Ousterhout's sense — a single tiny interface (`isDirty` + reset) backed by stable, consistent equality semantics that every settings page can depend on.
- A new **`SettingsFormActions` component** that renders the bottom-left action block. Props include `isDirty`, `isValid` (defaults to `true`), `isSaving`, `onSave`, `onCancel`, and optional label overrides for the rare page that wants page-specific button text. Save is rendered as primary; Cancel as outline. Both are disabled when not dirty; Save is additionally disabled when invalid or saving; the saving state shows a spinner inside Save.
- An **`UnsavedChangesGuard` component** already exists from the prior jobs-settings POC and installs a `beforeunload` listener while `isDirty` is true. It is kept as-is and reused by every migrated page. The existing POC-era `SettingsActionBar` component (the sticky right-aligned bar) is removed once `jobs-settings` is re-migrated, since it no longer matches the convention.

### Convention every form-style page implements

- On data load, capture a snapshot of every editable field's loaded value. Store it in component state.
- Compare a `snapshotKey(current)` against a `snapshotKey(loaded)` via `useDirtyForm` to derive `isDirty`. The snapshot key is the page's responsibility to define; it should produce a deterministic string (e.g. sorted-key JSON) so that incidental ordering differences (Set iteration, object key order) do not produce false-positive dirty states.
- A successful save reseats the snapshot to the just-saved values so the form returns to the not-dirty state.
- A Cancel click restores every edit field from the stored snapshot.
- Render `<SettingsFormActions />` at the end of the form. Render `<UnsavedChangesGuard isDirty={isDirty} />` once per page.
- Remove the page's bespoke save button block.

### Layout and alignment

- The action block is a normal flow element at the bottom of the form, not sticky, not floating. It uses a consistent top margin and a consistent button spacing.
- Buttons are left-aligned (`justify-start`) so that the primary action sits near the natural reading start of the page; this contrasts with the current right-aligned convention and is the explicit ask.
- Save uses the default (primary) button variant; Cancel uses the outline variant. Save shows a `Save` icon when idle and a spinner when saving; Cancel shows a `RotateCcw` icon.

### Navigation-guard behaviour

- A single `beforeunload` listener is installed by `UnsavedChangesGuard` whenever the page is dirty. It triggers the native browser confirmation dialog on tab close, reload, and typed-URL navigation. Custom prompt text is not supported by modern browsers.
- No in-app router blocker is installed in this PRD. Clicking a sidebar `<Link>` while dirty will silently navigate. This is an accepted limitation tied to the app's current `BrowserRouter`. Lifting it is tracked separately as a future router migration.

### Pages migrated

- `general-settings.tsx`
- `ui-customization-settings.tsx`
- `git-settings.tsx`
- `delivery-settings.tsx`
- `jobs-settings.tsx` (replace the existing sticky `SettingsActionBar` with the new static `SettingsFormActions`; keep the snapshot logic that was added in the POC)
- `search-config-editor.tsx`

### Pages NOT migrated

- `certification-levels-settings.tsx`, `roles-settings.tsx`, `tags-settings.tsx`, `connectors-settings.tsx`, `semantic-models-settings.tsx`, `mcp-tokens-settings.tsx`. These are list/CRUD pages where editing happens inside a Dialog with its own Save/Cancel; a page-level action block does not apply.

### i18n

- No new translation keys are required. The component uses the existing `common:actions.save`, `common:actions.saving`, `common:actions.cancel`, and `common:confirmations.unsavedChanges` keys, which already exist in all seven shipped locales.
- Pages that today pass a page-specific Save label (e.g. "Save Configuration", "Save UI Settings") can continue to do so via the `saveLabel` prop on `SettingsFormActions`.

### Validation hook-up

- `SettingsFormActions` exposes an `isValid` prop. Pages that today rely on inline `disabled={!something.trim()}` predicates pass that boolean through. This keeps page-specific validation rules in the page; the shared component only knows how to disable.
- Jobs settings retains its existing "cannot enable workflows without a deployment path" guard, which today lives inside `handleSave` and surfaces a toast. That logic moves into the `isValid`-style derivation so the Save button is greyed out (with a tooltip later if desired) rather than firing a toast.

## Testing Decisions

- **No automated tests are added in this PRD.** The change is treated as a UI consistency cleanup and validated via manual smoke testing per page, consistent with how the prior `jobs-settings` POC was verified.
- For each migrated page, the manual smoke checklist is: load the page (Save / Cancel disabled), edit a field (Save / Cancel enable; "unsaved changes" pill visible), click Cancel (every field reverts, Save / Cancel disable again), edit again, hit Save (request fires; on success Save / Cancel disable; on failure they remain enabled), trigger a reload while dirty (browser native prompt fires), trigger a reload while clean (no prompt).
- Existing per-feature smoke flows (Jobs install, Git connection, Delivery toggles, etc.) continue to be exercised manually after the migration.
- If a follow-up PRD wants automated coverage, the natural seams are the `useDirtyForm` hook (pure function over snapshot strings; trivial vitest coverage) and the `SettingsFormActions` component (RTL test for the disabled-state matrix). Neither is required to ship this change.

## Out of Scope

- **Migrating the app from `BrowserRouter` to `createBrowserRouter` + `RouterProvider`.** Required to enable in-app router blocking via `useBlocker`. Tracked separately as a router-architecture concern.
- **In-app navigation prompts.** Sidebar `<Link>` clicks while dirty will silently navigate. This will be revisited after the router migration.
- **List/CRUD settings pages** (`certification-levels`, `roles`, `tags`, `connectors`, `semantic-models`, `mcp-tokens`). Their per-row editing happens in Dialogs that already have Save/Cancel; harmonizing those Dialogs is a separate cleanup.
- **Backend changes.** No API endpoints, schemas, or persistence semantics change. The set of fields that get sent in each page's PUT remains exactly as it is today.
- **Toast / notification rework.** The existing success/failure toasts on each page stay as-is.
- **Sticky / floating action bar exploration.** The user explicitly requested a static bottom-left block; the sticky pattern from the prior `jobs-settings` POC is being unwound, not generalized.
- **Tooltips, inline help on disabled buttons, or richer empty-state messaging.** Polish for a follow-up.

## Further Notes

- The prior `jobs-settings` POC introduced the components `src/frontend/src/components/settings/settings-action-bar.tsx` (sticky right-aligned) and `src/frontend/src/components/common/unsaved-changes-guard.tsx`. The guard is reused unchanged; the action bar is replaced by the new `SettingsFormActions` and then deleted. The snapshot pattern proven in `jobs-settings.tsx` (sorted JSON stringify with stable key ordering) is generalized into the new `useDirtyForm` hook.
- The "left-aligned" alignment ask is intentional. Most form pages in shadcn-ui examples use a right-aligned save bar; the user prefers the action group near the natural reading start so it remains visible on narrow viewports and is closer to the form labels.
- This PRD assumes the existing `i18n` keys (`common:actions.save`, `common:actions.cancel`, `common:actions.saving`, `common:confirmations.unsavedChanges`) are stable and shared across all seven shipped locales (verified during the jobs POC). If those keys change in the future, the shared component is the single update point.
