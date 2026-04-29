# Approval Workflows v1 — Design Decisions & Scope

**Date**: 2026-04-29
**PRD**: #242
**Issues**: #277, #278, #279, #290, #291, #292

## Workflow Scope Overlap Behavior

When multiple workflows share the same trigger type and entity type:

**Process workflows** — all matching workflows fire independently. No priority, no exclusion. Two `on_create` workflows for `data_contract` both execute in parallel.

**Approval workflows** — the first matching workflow (by API query order) is used. If multiple approval workflows exist for `for_subscribe`, the frontend picks the first one returned; the rest are silently ignored unless the user manually selects from the workflow list.

**Mixed (approval + process)** — approval runs first (blocks the user action), then the process workflow fires after the approval completes.

### Rationale
Most deployments have one workflow per trigger. Overlap is rare and the additive behavior for process workflows is usually correct (e.g., "notify owner" + "run compliance check" both fire on create).

### Future enhancement
If customers need priority ordering or mutual exclusion:
- Add a `priority` field to workflows (lower = runs first)
- Add a "workflow selector" step in the approval wizard when multiple approval workflows match
- Add scope narrowing (e.g., workflow only applies to products in domain X)

## Parked Features (v1)

| Feature | Status | Notes |
|---------|--------|-------|
| Grant Permissions step | Type defined, no backend handler | Greyed out "(soon)" in palette. Needs #291 for variable propagation |
| Deliver: email channel | Config accepted, silently ignored | Only `in_app` implemented. Help text says "Coming soon" |
| Deliver: webhook channel | Config accepted, silently ignored | Same as email |
| Co-signers counter-signature | Record-only | No signing invitation sent to co-signers. By design per PRD |
| Checklist items visual editor | Raw JSON textarea | Works but not user-friendly for non-technical designers |
| Workflow versioning/diff | Out of scope | Snapshot captures point-in-time; no version history UI |
| Conditional branching in approval flows | Out of scope | Approval flows are linear in v1 (on_pass chain only) |

## Missing: Approvals Inbox (recommend filing as GitHub issue)

There is no dedicated "My Approvals" or "Pending Approvals" view. When a process workflow pauses at a "Request Approval" step, the approver's only way to find it is:

1. **Notification bell** — easy to miss, mixed with other notification types
2. **Workflows page → Recent Executions → filter "In Progress"** — finds paused executions, but no role-based filtering ("assigned to me")

For production use, users need:
- A dedicated **approvals inbox** showing all executions awaiting their approval, filtered by their role
- Clear distinction between "my pending approvals" (I need to act) and "my submitted requests" (I'm waiting on someone)
- Inline Approve/Reject without navigating to the Workflows page

The existing `/api/approvals/queue` endpoint returns entities in proposed status (contracts/products), which is a different concept from process workflow approval steps. These two approval surfaces are not connected.

Related issues: #62 (persona-based UI — would include a per-persona home with pending actions), #161 (filter approver roles by context). Neither covers this gap directly.

**Recommendation**: file a dedicated GitHub issue for an approvals inbox/queue view.

## What's Implemented

### Step Catalog (Approval)
- `legal_document` — scrollable markdown body, scroll-to-end detection, acknowledgement checkbox
- `acknowledgement_checklist` — itemized checkboxes with required/optional flags (max 10)
- `co_signers` — principal picker with min/max count (record-only)
- `user_action` — existing, unchanged for backward compatibility
- `persist_agreement` — explicit agreement materialization (non-visual, auto-advances)
- `generate_pdf` — real PDF via fpdf2 with download endpoint (non-visual)
- `deliver` — in_app notification to signer/entity_owner (non-visual)

### Step Catalog (Process)
- `grant_permissions` — type defined, config panel built, backend handler pending

### Infrastructure
- Workflow snapshot captured on session creation, copied to agreement
- Cross-workflow variable propagation (#291) — approval inputs available in process steps
- Unified workflow list with All/Process/Approval filter + type badges
- Designer type selection with filtered step palette
- 29 E2E tests covering all step types, validation, PDF download, delivery
