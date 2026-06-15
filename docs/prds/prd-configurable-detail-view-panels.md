# PRD: Configurable Detail-View Panels (S/M/L + Custom Views)

## Problem Statement

Data Product and Data Contract detail views currently expose a three-way size toggle (S/M/L = `minimal` / `medium` / `large`) that decides which panels (sections) are visible. The mapping is **hardcoded** inside each detail view: a switch statement enumerates which section ids belong to each mode, and the active mode is persisted to `localStorage` under a single key per entity type.

This is rigid in three ways:

1. **No per-user choice over individual panels.** Users who want "medium plus quality" or "large minus subscribers" have no recourse — they get the curated set or nothing.
2. **No way to save a named arrangement.** A reviewer preparing for a QBR, a steward auditing compliance, and a producer building a draft all want different panel sets, but the only knob is the size enum.
3. **The default sets are invisible.** The mapping lives inside a TypeScript `switch`, so neither developers nor users can easily see "what's in medium?" without reading code.

The role-based initial default (`computeDefaultViewMode`: owner-team → large, write/admin → medium, else minimal) is a reasonable first-load behavior but stops being useful the moment a user wants anything else.

## Solution

Replace the hardcoded S/M/L mapping with a **canonical section registry** per entity type plus a **per-user view configuration** stored in `localStorage`. The three built-in views (`minimal` / `medium` / `large`) remain as defaults, but every user can:

- **Override** any built-in view in place (toggle individual panels), with a one-click Reset.
- **Create** named custom views ("QBR focus", "Compliance audit") with their own panel selection.
- **Switch** between views via the existing S/M/L icon buttons when no custom views exist, or a unified "Select view" dropdown once they create their first custom view.

The registry is a plain TypeScript module per entity type — anyone reading the codebase can see at a glance which panels exist and which are in each built-in view. The role-based first-load default is preserved (it picks a built-in slot, which may itself be overridden).

Views are stored as **diffs**, not snapshots:

- Built-in overrides diff against that built-in's section set, so new panels shipped in the code automatically appear inside overridden built-ins.
- User-created views diff against the **full** canonical section list, so new panels appear there too by default (user can opt out by hiding).

Storage is browser-local for v1; multi-device sync is explicitly deferred.

## User Stories

### Discovery and defaults

1. As a first-time user on a Data Product detail page, I want the view to start in the size that matches my role (owner-team → large, write/admin → medium, else minimal), so that I see a useful set of panels without configuring anything.
2. As a returning user, I want my last-selected view restored on reload, so that my preference is sticky across sessions.
3. As any user, I want to see the names of the built-in views (Small / Medium / Large, localised), so that I understand what the S/M/L buttons mean without hovering.

### Toggling panels on the current view

4. As a Data Producer on a "medium" view, I want to add the Quality panel to my current view via a checkbox in a popover, so that I can monitor quality without jumping to a different size.
5. As a Data Consumer on a "minimal" view, I want to remove the Description panel from my view, so that I can declutter further.
6. As any user, I want my panel toggles applied immediately (no Save button for the current view), so that I get instant feedback.
7. As any user, I want a "Reset to default" action on overridden built-in views, so that I can return to the shipped Medium/Small/Large composition with one click.

### Creating, naming, and managing custom views

8. As a Solution Architect preparing for a QBR, I want to save my current panel arrangement as a named view "QBR focus", so that I can switch to it instantly during the meeting.
9. As a user with a custom view, I want to rename it, so that I can clarify its purpose later.
10. As a user with multiple custom views, I want to delete one I no longer need, so that my dropdown stays clean.
11. As a user, I want to be told if I try to save an empty view (zero panels), so that I don't end up with a useless arrangement.
12. As a user, I want to be free to create two views with the same display name, so that I'm not blocked by spurious uniqueness validation (each view has its own id internally).
13. As a user, I want a soft cap of 20 custom views with a warning, so that I'm nudged to tidy up without being hard-blocked.
14. As a user, I want the built-in views (Small/Medium/Large) to remain in my dropdown even when I've created custom views, so that I always have a way back to the canonical defaults.
15. As a user, I should not be able to delete or rename the built-in views, so that the system always has a stable reset path.

### Switching between views

16. As a user with zero custom views, I want to keep the familiar S/M/L icon buttons, so that the UI does not become heavier than it is today.
17. As a user with one or more custom views, I want the S/M/L buttons to collapse into a single "Select view" dropdown listing all built-ins + custom views + a "Customize…" entry, so that all my options are in one place.
18. As a user on an overridden built-in view, I want to see a small dot indicator on the trigger and "(customized)" suffix in the dropdown for that entry, so that I know I'm not on the pristine default.

### Behavior across code changes

19. As a user who has overridden the Medium built-in, I want any new panel shipped in a future release to appear inside my overridden Medium by default, so that I do not silently fall behind the product's evolution.
20. As a user with a saved custom view, I want any new panel shipped in a future release to appear in my view by default (with the option to hide it), so that I am made aware of new capabilities.

### Permissions

21. As a read-only user, I should not see panels in the customize popover that I would not be allowed to render anyway (e.g. Subscribers, Access Grants), so that the UI does not advertise capabilities I cannot use.
22. As an admin who later loses elevated permissions on an entity, panels in my saved view that I can no longer render are silently hidden in render output (not removed from my stored configuration), so that my view comes back intact if my permissions are restored.

### Migration

23. As an existing user who previously selected "large" before this change shipped, my prior size selection should be migrated to the new storage shape on first load, so that I am not reset to the role-based default.

### Scope-related expectations

24. As a user, I expect the same mechanism to land on Asset detail and Domain detail views in the future, but I do not require it in this initial release.

## Implementation Decisions

### Architecture

- A new **section registry** per entity type is the single source of truth for: (a) the canonical ordered list of section ids with i18n keys, (b) optional permission predicates per section, and (c) the three built-in view definitions (`minimal`, `medium`, `large`) expressed as section-id sets. This **replaces** the existing inline `shouldShowSectionForViewMode` switch in each detail view.
- A new **view config store** module is a pure functional layer over `localStorage`. It owns the storage shape, the diff-apply logic, legacy-key migration, and the view-resolution function that produces the final visible section list for a given (config, viewId, permissions) tuple. No React inside.
- A **`useViewConfig(entityType)` React hook** wraps the store with state. It exposes read state (`activeView`, `customViews`, `builtinOverrides`) and a small set of mutators (`setActiveViewId`, `overrideBuiltin`, `createCustomView`, `updateCustomView`, `renameCustomView`, `deleteCustomView`, `resetBuiltin`). It is intentionally thin — all logic lives in the store module.
- A **`ViewSelector` component** consumes the hook and decides whether to render the S/M/L icon-button trio or the unified dropdown, based on whether any custom views exist. It also renders the customized-state indicator (dot + suffix) and the Reset-to-default action on overridden built-ins.
- A **`ViewCustomizePopover`** component shows a checkbox list of sections (filtered by permission predicate) and toggles call directly into `useViewConfig`.
- A **`ManageViewsDialog`** modal handles the heavier flows: Save-as-new, rename, delete, reset.

### Storage shape

Per entity type, one `localStorage` key (`viewconfig:dataProduct`, `viewconfig:dataContract`):

```
{
  activeViewId: 'minimal' | 'medium' | 'large' | <uuid>,
  overrides: {
    <builtinId>: { hidden: [<sectionId>...], added: [<sectionId>...] }
  },
  custom: [
    { id: <uuid>, name: <string>, hidden: [<sectionId>...], added: [<sectionId>...] }
  ]
}
```

`hidden`/`added` are always relative to the entry's base:

- For a built-in override, the base is that built-in's section set.
- For a custom view, the base is the **full canonical section list** from the registry. (So a freshly-created custom view starts as "all visible".)

This symmetry guarantees that new code-side sections automatically appear in both overridden built-ins and user-created views unless the user has explicitly hidden them.

### Legacy migration

On hook initialization, if `viewconfig:<entityType>` is absent but the legacy `<entityType>-view-mode` key exists with a value in `{minimal, medium, large}`, the legacy value is migrated into `activeViewId` and the legacy key is deleted. Mirror logic for Data Contract.

### First-load default

When `activeViewId` is absent after migration, the role-based selector (owner-team → `large`, write/admin → `medium`, else `minimal`) picks the initial slot. The slot is set explicitly into `activeViewId` and persisted, so subsequent loads bypass the selector.

### Permission gating

Each section in the registry may define `canShow(permissions)`. The customize popover filters out sections returning false; the detail-view renderer continues to gate independently (defense in depth). User configuration is **never** mutated based on permission changes — hidden-by-permission sections re-appear if permission is restored.

### Toolbar transition rule

- `customViews.length === 0` → render the existing S/M/L icon-button trio.
- `customViews.length >= 1` → render a single "Select view" dropdown that lists, in order: the three built-ins (with customized indicator where applicable), then the user's custom views, then a separator and a `Customize…` entry that opens the popover for the currently-active view, then a `Manage views…` entry that opens the dialog.

### Edge cases

- Empty view (0 sections) on save: rejected with inline validation in the dialog.
- Duplicate names: allowed (uuid is the identity).
- Built-in display names: i18n-managed, not user-renameable.
- Soft cap: 20 custom views per entity type, with a warning at save time; no hard limit.

### Entity-type scope

- Product and Contract detail views are wired in this change.
- Asset detail (`asset-detail.tsx`) and Domain detail are out of scope for v1 but the registry/store/hook are designed to accept additional entity types without changes to their interfaces — a new `*-sections.ts` module and a new `entityType` argument value are all that's needed later.

### What the detail views lose

Both `data-product-details.tsx` and `data-contract-details.tsx` shed their local `ViewMode` type, `parseStoredViewMode`, `computeDefaultViewMode`, `shouldShowSectionForViewMode`, the size-toggle JSX, and the size-related state. They replace these with `const { isSectionVisible } = useViewConfig('dataProduct' | 'dataContract')` and `<ViewSelector entityType={...} />` in the toolbar. The existing per-section JSX gating (`shouldShowSection('foo')`) becomes `isSectionVisible('foo')`.

## Testing Decisions

### What makes a good test for this work

Tests target **external behavior**, not implementation details. Specifically:

- **Inputs**: configuration object + section registry + permissions.
- **Outputs**: resolved section list, mutated configuration, migration result.

Tests must NOT assert on:

- The internal shape of intermediate objects beyond the documented storage schema.
- Specific React state transitions in the hook (test the store, not the hook plumbing).
- DOM structure of the UI components.

### Modules to be tested

Per the agreed scope, unit tests cover the two deep modules:

1. **Section registry modules** (`product-sections`, `contract-sections`):
   - Built-in view section sets are deterministic and contain only valid registry-known section ids.
   - `canShow(permissions)` predicates return the expected boolean for representative permission inputs (read-only, write, admin, owner-team-member).
   - The exported canonical order is stable across calls.

2. **View config store**:
   - **Load/save round-trips**: writing a config, reading it back, produces an identical object (modulo serialization).
   - **Legacy migration**: each of `minimal`/`medium`/`large`/missing/garbage legacy values produces the right post-migration state; legacy key is removed on success.
   - **Diff apply**: applying `{ hidden, added }` against a base set produces the expected resolved section list; ids in `hidden` that don't exist in base are ignored; ids in `added` that already exist in base are ignored; duplicates collapse.
   - **Resolution end-to-end**: given a config + registry + permissions, `resolveVisibleSections(viewId, …)` returns the expected ordered, permission-filtered section list for: a pristine built-in, an overridden built-in, a custom view, an active id that doesn't exist (fall back to the role-based default), a custom view referencing a section that no longer exists in the registry (silently dropped).
   - **Mutators**: `overrideBuiltin`, `resetBuiltin`, `createCustomView`, `updateCustomView`, `renameCustomView`, `deleteCustomView` produce the expected next-state config; empty-view creation is rejected at the store boundary, not only in the UI.
   - **New-section propagation**: when the registry gains a section after a config was saved, an overridden built-in and a custom view both surface the new section in their resolved output (unless the user explicitly hid it).

### Modules explicitly NOT unit-tested in this work

- `useViewConfig` hook: it is a thin React-state wrapper. The store's tests cover the logic; manual testing covers re-render behavior.
- `ViewSelector`, `ViewCustomizePopover`, `ManageViewsDialog`: covered by manual / Playwright testing in subsequent verification, not unit-tested in this PRD.

### Prior art in the codebase

Existing pure-function unit tests for `parseStoredViewMode`, `computeDefaultViewMode`, and `shouldShowSectionForViewMode` in `src/frontend/src/views/data-product-details.test.tsx` are the canonical pattern. Those tests will be **moved** to test the new registry / store modules; the originals are deleted along with the now-unused helpers in the detail view.

## Out of Scope

- **Server-side sync** of view configuration across browsers, devices, or users. Storage is browser-local for v1.
- **Per-entity-instance overrides** ("this view, but only for *this* particular product"). Configuration is per entity *type*, not per entity *instance*.
- **Sharing or exporting** custom views to other users.
- **Asset-detail and Domain-detail wiring**. The mechanism is generic; only Product and Contract are wired in v1.
- **Per-view section reordering**. Sections always render in the canonical order from the registry. Reordering is a substantially larger refactor of the detail-view JSX and can be reconsidered after usage data is collected.
- **Admin-configured organization defaults**. The role-based first-load default remains hardcoded.
- **Bulk view-config import/export** (JSON download/upload of views).

## Further Notes

- The exact section-id sets for the three built-in views will be copied verbatim from the current `shouldShowSectionForViewMode` implementations in `data-product-details.tsx` and `data-contract-details.tsx`. If any of those sets should change as part of this work (e.g., promote `quality` from large-only to medium), that should be called out and adjusted in the registry — but it is not a goal of this change.
- Section labels (i18n keys) need to be added to the existing translation files alongside the registry.
- The polymorphic panel matrix in `.cursor/rules/10-entity-panel-matrix.mdc` should be cross-referenced when defining the canonical section list for each entity type, and updated if new panel ids are introduced.
- Future extension: once Asset and Domain detail views adopt the same mechanism, the panel matrix could be consumed directly by the registry to keep eligibility rules in one place.
