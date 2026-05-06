# PRD: Approval Workflows v2 — Step Catalog, Snapshot, PDF & Delivery

## Problem Statement

Approval Workflows are wizard-driven, multi-step flows that guide a user through giving consent for an action (subscribing to a data product, accepting a contract, requesting access). Today the wizard works, but it has three gaps that block real-world, legally-meaningful use:

1. **The step catalog is too generic.** The only interactive step type is a free-form `user_action` with optional required fields, `requires_input`, and `minimum_input_length`. There is no first-class way to model the things an approval flow actually needs: showing a legal document and requiring acknowledgement, presenting a checklist of explicit consents (e.g. "Accept PII usage"), naming co-signers, or running non-visual side effects like generating a PDF and delivering it. Workflow designers end up wedging everything into `user_action` payloads, which is fragile and gives users an inconsistent experience.

2. **Workflows are mutable while sessions are in flight.** The wizard reads `workflow.steps` live every time a user advances. If an admin reorders, renames, or tightens a workflow while a user is mid-session, the user's experience breaks (or worse, silently changes). After completion, the agreement record only stores `step_results` and a `workflow_id` — if the workflow is later edited or deleted, there is no faithful record of what the user actually agreed to. For an artifact that may be the basis of a legal contract, this is unacceptable.

3. **PDF generation and delivery are partial and implicit.** A `generate_pdf` step exists but its output handling is hardcoded; there is no first-class "deliver the agreement" step that uses the notification channels (`in_app`, `email`, `webhook`) the rest of the system already supports. Designers cannot configure where the signed contract goes.

## Solution

Introduce a dedicated **approval-mode step catalog** in the workflow designer, an **immutable workflow snapshot** persisted on every wizard session and agreement, and **first-class non-visual steps** for persisting the agreement, generating a PDF, and delivering it through the existing notification channels.

The workflow designer's toolbox becomes context-aware: when editing an approval-mode workflow, only approval-relevant steps are offered; when editing a process-mode workflow, today's catalog (validation, approval, notification, assign-tag, etc.) is shown. The Approval Wizard dialog renders each step using a step-type-specific UI component, with a uniform header (title + markdown description) so designers can give every step clear context for the signing user.

The snapshot is captured once when the wizard session is created and copied verbatim onto the agreement on completion. From that point on, the wizard runtime, PDF builder, and any audit view read from the snapshot, never from the live workflow definition. Existing in-flight sessions and historical agreements remain readable via a NULL-tolerant fallback to the live workflow.

## User Stories

1. As a workflow designer, I want the designer toolbox to show approval-specific step types when I am editing an approval workflow, so that I am not distracted by process automation steps that do not apply.
2. As a workflow designer, I want every visual step to have a `title` and a markdown `description`, so that the wizard shows the signing user clear context at every step without me building it into the field labels.
3. As a workflow designer, I want a `legal_document` step where I paste markdown for a legal text, optionally require the user to scroll to the end, and optionally require an acknowledgement checkbox, so that I can model "read this and confirm" interactions cleanly.
4. As a workflow designer, I want an `acknowledgement_checklist` step with one or more labeled checkboxes (e.g. "I accept usage of PII data", "I will not redistribute"), each markable as required, so that I can capture explicit, itemized consents.
5. As a workflow designer, I want a `co_signers` step that lets the signer name additional principals (users or groups) by email/name, with configurable min/max counts, so that I can capture co-ownership of an agreement when an enterprise requires more than one signer on record.
6. As a workflow designer, I want a `persist_agreement` non-visual step that materializes the agreement record at the position I place it, so that I can decide whether persistence happens before or after PDF generation and delivery.
7. As a workflow designer, I want a `generate_pdf` non-visual step with a configurable storage destination (Databricks volume path, or no storage), so that the signed contract can be archived where my organization requires.
8. As a workflow designer, I want a `deliver` non-visual step where I choose channels (`in_app`, `email`, `webhook`) and recipients (signer, co-signers, entity owner, literal email/group), so that the signed agreement reaches the right people through the right channel.
9. As a signing user, I want each wizard step to show me a clear title and an informational paragraph above the controls, so that I know what I am being asked to do.
10. As a signing user, I want non-visual steps to show a brief "Processing…" tile and auto-advance, so that the wizard does not present me with empty pages.
11. As a signing user, I want the wizard to refuse to advance if a required checkbox is unchecked, a required field is empty, or I have not scrolled to the end of a legal document that requires it, so that I cannot accidentally consent to something I did not see.
12. As a signing user, I want the wizard I started to remain stable even if an admin edits the underlying workflow definition while I am in the middle of it, so that my flow does not break or change unexpectedly.
13. As an auditor, I want every signed agreement to include a faithful, immutable copy of the workflow steps as they were at the moment of signing, so that I can reconstruct exactly what the signer was asked and what they answered.
14. As an auditor, I want the agreement PDF to be generated from the snapshot, not from the current workflow definition, so that the PDF is always consistent with what the user actually saw.
15. As a data product owner, I want to be notified through my chosen channels when a consumer signs a subscription agreement on my product, so that I can react in a timely fashion without polling the system.
16. As a data consumer, I want to receive an email with the PDF attachment after I sign an agreement, so that I have my own copy of what I agreed to.
17. As an admin, I want the default Subscription workflow shipped with the product to demonstrate the new step types end-to-end (legal document → acknowledgement checklist → optional co-signers → persist → PDF → deliver), so that I have a working template to clone and adapt.
18. As an admin, I want existing `user_action`-based workflows (the current Subscription and Approval Response defaults) to continue working unchanged, so that the upgrade does not require me to rebuild every workflow on day one.
19. As an admin, I want a single Alembic migration to add the snapshot columns, with NULL-tolerant fallback to live workflow definitions, so that deployments are zero-downtime and historical agreements remain readable.
20. As a workflow designer, I want a hard cap on the number of items in an `acknowledgement_checklist` step (e.g. ten), so that the wizard remains visually manageable on a single screen.
21. As a workflow designer, I want the `co_signers` step to be record-only — naming the principals on the agreement without launching a separate counter-signature flow — so that the model stays simple and the original signer's session completes synchronously.
22. As a signing user, I want the wizard heading to clearly label the current step's purpose (e.g. "Acceptable Use Acknowledgement"), so that I understand what I am consenting to at a glance.
23. As an auditor, I want the agreement record to also store the workflow's name and version at signing time, so that I can identify which template was used without re-deriving it from the snapshot.
24. As a workflow designer, I want each step type's configuration to be driven by a JSON schema served from the backend, so that the designer's properties panel renders the right form for each step type without bespoke per-type frontend code.
25. As a developer extending the system, I want adding a new approval step type to require only (a) registering a `StepTypeSchema`, (b) adding a server-side validator, and (c) adding a frontend renderer, so that the step catalog is genuinely extensible.

## Implementation Decisions

### Step Catalog (Visual)

All visual steps share a common header:

- `title` (string) — rendered as the wizard step heading. Falls back to `step.name` if absent.
- `description` (markdown string) — rendered as the informational paragraph below the heading.

The catalog adds the following visual step types alongside the existing `user_action`:

- **`legal_document`** — renders a markdown body. Configurable: `body_markdown`, `require_scroll_to_end` (boolean), `require_acknowledgement_checkbox` (boolean), `acknowledgement_label` (string). Validation: scroll-completion (frontend-tracked, sent in payload as a boolean) and/or checkbox checked, per config.
- **`acknowledgement_checklist`** — renders one or more labeled checkboxes. Configurable: `items: [{ id, label, required }]` with a hard cap of ten items per step. Validation: every required item checked.
- **`co_signers`** — renders a principal picker (badge-with-X, free-text email or group name in v1). Configurable: `min_count`, `max_count`, `principal_type` (`user` | `group` | `either`), `label`. Stored on the agreement as a named list. **Record-only**: no asynchronous counter-signature flow is launched; the original signer completes the wizard immediately.
- **`user_action`** (existing) — kept unchanged for backward compatibility with the current Subscription and Approval Response defaults.

### Step Catalog (Non-Visual)

Non-visual steps execute server-side at the moment the wizard reaches them. The wizard UI shows a brief "Processing…" tile and auto-advances on success, propagating server errors as toast notifications.

- **`persist_agreement`** — explicit step that materializes the agreement record. Today this is implicit at end-of-wizard; making it an explicit step lets the designer position it (for example, before or after PDF/delivery). When omitted from a workflow, the runtime persists the agreement implicitly at end-of-wizard, preserving today's behavior.
- **`generate_pdf`** — generates a PDF rendition of the agreement from the snapshot and accumulated step results. Configurable: `template_id` (optional, default = built-in template), `storage` (`volume` | `none`), `volume_path` (when `storage=volume`). Side effect: sets `pdf_storage_path` on the agreement.
- **`deliver`** — sends the agreement summary (and PDF link/attachment when present) through one or more channels. Configurable: `channels: ['in_app' | 'email' | 'webhook']`, `recipients` (an array drawn from `signer`, `co_signers`, `entity_owner`, or literal `<email>`/`<group_name>` strings), `subject_template`, `body_template`. Reuses the channel resolver and per-channel handlers already present in the workflow executor.

### Workflow Snapshot

Two new columns are added to both the agreement wizard sessions table and the agreements table:

- `workflow_snapshot` (Text, JSON-serialized) — array of step objects shaped `{ step_id, name, step_type, config, on_pass, on_fail, order }`.
- `workflow_name` (String, nullable) — captured for display/audit without rejoining `process_workflows`.

The snapshot is captured once when the session is created and copied verbatim into the agreement when the session completes. Once written it is never modified.

The wizard runtime resolves steps by reading the snapshot first and falling back to the live workflow definition only when the snapshot is NULL. This guarantees backward compatibility for in-flight sessions during the deploy window and for any agreements created before the migration.

The PDF builder reads exclusively from the snapshot.

### Designer Changes

- The toolbox in the workflow designer is filtered by the workflow's `workflow_type`. In approval mode the palette shows: `legal_document`, `acknowledgement_checklist`, `co_signers`, `user_action`, `persist_agreement`, `generate_pdf`, `deliver`, `pass`, `fail`. In process mode today's catalog is unchanged.
- Each new step type gets a React Flow node component with an icon and theme color registered in the designer's label/icon constants.
- The properties panel renders a generic `title` / `description` block for any visual step, and a per-step config form driven by the `config_schema` returned from the backend's step-type-schemas endpoint.
- The default node fallback already added in the previous iteration remains, so any future or unknown step type renders as a labeled placeholder rather than an empty box.

### Wizard UI Changes

The Approval Wizard dialog dispatches on `step_type` to render:

- `legal_document` — scrollable markdown container with an IntersectionObserver sentinel at the bottom that flips a `scrolled_to_end` boolean in local state; an optional acknowledgement checkbox below.
- `acknowledgement_checklist` — list of checkbox controls bound to `items[].id`.
- `co_signers` — badge-with-X principal picker; free-text input validated as email or group name.
- `user_action` — existing renderer.
- `persist_agreement`, `generate_pdf`, `deliver` — auto-submitting "Processing…" tile.

The step heading uses `config.title || step.name`. The help text uses `config.description` rendered as markdown. The "Next" button is disabled until the step's frontend validation passes; the backend revalidates on submit.

### Backend Surface

- New `StepType` enum values and `StepTypeSchema` entries in the workflows manager. Schemas are served by the existing step-type-schemas route.
- Per-step validators in the agreement wizard manager, dispatched from `submit_step` based on `step_type`.
- Snapshot read/write helpers on the wizard sessions and agreements repositories.
- A delivery handler that resolves recipients (signer / co-signers / entity owner / literal) and dispatches to the existing per-channel notification code paths, without going through the full process-workflow executor.

### API Contract

The existing approval session endpoints (`POST /api/approvals/sessions`, `GET /api/approvals/sessions/{id}`, `POST /api/approvals/sessions/{id}/steps`, `POST /api/approvals/sessions/{id}/abort`) are unchanged in shape. The `current_step` payload already carries `step_type` and `config`; the new step types simply use new `step_type` values and richer `config` objects.

### Migration

A single Alembic migration revising the current head adds `workflow_snapshot` and `workflow_name` to both `agreement_wizard_sessions` and `agreements`. No data backfill is performed; the NULL-tolerant fallback covers historical rows.

### Default Workflows

The shipped Subscription default in the YAML is rewritten to demonstrate the new catalog end-to-end:

`legal_document` (Acceptable Use) → `acknowledgement_checklist` (PII / Redistribution / Retention) → `co_signers` (optional, max 0 by default) → `persist_agreement` → `generate_pdf` (volume) → `deliver` (in_app + email).

The Approval Response default keeps `user_action` for backward compatibility but adds an explicit `title` and `description` to demonstrate the header convention.

### Backward Compatibility

- The `user_action` step type stays in both backend and frontend.
- Existing workflows without `workflow_snapshot` continue to run via the live-workflow fallback.
- Workflows without an explicit `persist_agreement` step still get an implicit agreement at end-of-wizard.
- The session and agreement API contracts do not change.

## Testing Decisions

Tests verify external behavior through the public interfaces (manager methods, route handlers, wizard dialog interactions). They do not assert on internal implementation details.

### Backend (pytest)

- **Snapshot capture and immutability**: creating a session captures the snapshot; editing the workflow afterwards does not change the session's view; completing the session copies the snapshot to the agreement.
- **Snapshot fallback**: a session with `workflow_snapshot = NULL` resolves steps from the live workflow definition.
- **Per-step validators**: one happy-path and one rejection-path test for each new visual step type (`legal_document` scroll-and-checkbox, `acknowledgement_checklist` required items, `co_signers` count bounds and principal-type validation).
- **`persist_agreement` placement**: explicit-step and implicit-end-of-wizard paths both yield exactly one agreement record per session.
- **PDF from snapshot**: the PDF builder produces output even when the underlying workflow is deleted between session creation and PDF generation.
- **Delivery dispatch**: `deliver` resolves `signer`, `co_signers`, `entity_owner`, and literal recipients to the right channel handlers; channel selection respects the `channels` config.

Prior art: existing wizard manager tests in the backend test suite, plus the workflow notification channels test for channel dispatch patterns.

### Frontend

- **Wizard dispatch**: the dialog renders the correct component for each `step_type` and disables "Next" until validation passes.
- **Legal document scroll detection**: the sentinel observer flips the validation flag when scrolled to the bottom.
- **Checklist**: required items block "Next"; optional items do not.
- **Co-signers picker**: enforces min/max and validates principal entries.

Prior art: existing wizard dialog tests for `user_action`.

### End-to-End

The existing Subscribe-via-marketplace happy path is updated to walk the rewritten Subscription workflow end-to-end and assert that an agreement is created, a PDF is stored, and the signer receives an in-app notification.

## Out of Scope

- **Asynchronous counter-signature** by co-signers. The `co_signers` step is record-only by decision; a future PRD can layer a counter-signature flow on top.
- **SCIM / directory autocomplete** for the co-signers principal picker. v1 uses free-text input with validation. The Slack / Teams notification channels (only the channels already present in the workflow executor are wired up).
- **WYSIWYG markdown editor** for the legal document body. v1 uses a plain markdown textarea with a preview toggle if cheap, or no preview otherwise.
- **Versioned workflow definitions** beyond the snapshot. The snapshot is the audit unit; full workflow versioning with diff/history is a separate feature.
- **Per-user / per-tenant overrides** of default workflows.
- **Importing legal documents from external sources** (URL, file upload). The step takes inline markdown.
- **Conditional branching** within an approval workflow beyond the existing `on_pass` / `on_fail` mechanics. Approval flows in v1 are linear.

## Further Notes

- The snapshot also doubles as the contractual basis for the PDF; the PDF render is therefore deterministic with respect to a given session/agreement, which is exactly the property an auditor or legal team needs.
- Adopting `title` / `description` uniformly on visual steps is what unlocks a consistent wizard UX without per-step bespoke layout work, and makes future step types cheap to add.
- Reusing the existing notification channel resolver from the workflow executor for the `deliver` step keeps a single source of truth for channel handling and respects whatever future channels (Slack, Teams) get added there.
- The hard cap of ten items per `acknowledgement_checklist` step is ergonomic, not technical; designers needing more should split into multiple steps to keep each screen scannable.
