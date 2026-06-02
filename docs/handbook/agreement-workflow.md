# Agreements and the Approval Workflow

Ontos has two flavours of workflow:

- **Process workflows** (`workflow_type = "process"`) — event-driven
  automations that react to triggers like `on_create`, `on_subscribe`,
  `on_status_change`.
- **Approval workflows** (`workflow_type = "approval"`) — wizard-driven
  flows that collect user input across multiple steps and produce a signed
  **agreement** record on completion.

This document covers the approval flavour and the agreement artifact it
produces. The `grant_permissions` step is shared with process workflows
and is explained in context.

## Three concepts that get conflated {#three-concepts}

Customers (and reviewers, and sub-agents writing code against the API)
often slur three different things together. They are distinct.

| Concept | What it is | When it exists |
|---|---|---|
| **Workflow** | The *definition* — an ordered list of step configurations with a trigger and a scope. Edited from Settings → Workflows. | Whenever you've authored a workflow definition. |
| **Wizard Session** | The *in-flight runtime state* of an approval workflow. Holds the snapshotted workflow definition (so later edits don't change what's being signed) and the per-step user inputs collected so far. | From the moment a user opens the wizard until the workflow completes or is cancelled. |
| **Agreement** | The *immutable post-completion record* — who signed what, against which entity, with which workflow definition snapshot. | Persisted at the end of a successful approval workflow. Never modified after. |

A related but separate entity is the **Workflow Execution**
(`WorkflowExecutionDb`) — the runtime row that tracks status (`pending` /
`running` / `paused` / `succeeded` / `failed` / `cancelled`) and current
step. Wizard sessions are the user-facing surface for in-flight approval
workflows; workflow executions are the lower-level state tracker that
both process and approval workflows write to.

## What an agreement is {#what-is-an-agreement}

An agreement is the durable record of a completed approval workflow. It
captures who agreed to what, against which entity, under which workflow
definition. Once written, an agreement is immutable: the workflow
definition in force at sign-time is snapshotted onto the record so
later edits to the workflow do not retroactively change the signed
terms.

Stored fields (`AgreementDb`):

- `entity_type`, `entity_id` — what the agreement is about (typically a
  data product, data contract, output port, or access grant).
- `workflow_id` — pointer to the live workflow (may be `NULL` if the
  workflow was deleted; the snapshot still describes what was signed).
- `wizard_session_id` — pointer to the wizard session that produced the
  agreement.
- `step_results` — JSON list of per-step results (user input, computed
  values, branching outcome).
- `workflow_snapshot` — immutable JSON of the workflow definition at
  sign time.
- `workflow_name`, `workflow_version` — denormalized for quick lookup.
- `pdf_storage_path` — optional generated PDF artifact.
- `created_by`, `created_at`.

The agreement complements (does not replace) the workflow execution
record: the `WorkflowExecutionDb` row captures runtime state while the
workflow is in flight; the agreement is the post-completion artifact.

## Approval Gates {#approval-gates}

An **Approval Gate** is a first-class concept across Ontos's lifecycle:
a moment where a configured approver must sign off before the entity
moves to the next state. The platform uses approval gates at well-known
junctures:

- **Contract Approval** — when a contract transitions
  `proposed → under_review → approved`.
- **Sandbox Ready** — when a product moves from `draft` to `sandbox`.
- **Product Certified** — when a product is submitted for certification
  (status transitions through `proposed → under_review → approved`).
- **Product Active** — when a product is published (typically
  `approved → active`).

Each gate is implemented as an approval workflow that's matched by
trigger type when the corresponding lifecycle action fires. The gate
configuration names the approvers (group, role, business owner, or
explicit email list), the policy checks to run, and any side effects
(notification, PDF generation, UC grant, etc.).

A gate may be configured to **auto-approve** under specific conditions
(e.g., `auto_approve=true` on an output port for low-sensitivity public
data) — in which case the gate is logged but not paused for human sign
off.

## Roles in an approval flow {#approval-roles}

Three logical roles participate, though a single person may play
several:

- **Initiator / requester / signer** — the user who launched the
  wizard. May be a Data Consumer requesting access to a Deliverable, a
  Data Producer requesting publication, or any user acknowledging a
  disclaimer.
- **Business owner / approver** — the party whose acceptance is
  required for the agreement to be valid. Resolved from the workflow's
  `approval` or `user_action` step configuration (e.g.,
  `approvers: "domain_owners"`, named groups, Ontos roles whose
  `approval_privileges` cover the workflow's entity type, or explicit
  emails). The role picker in the workflow designer filters to roles
  that can approve the entity types the workflow is configured for, so
  authors don't accidentally assign a role that has no approval
  authority for the target entity.
- **Co-signer** (optional) — additional principals captured via the
  `co_signers` step type. Each co-signer's acknowledgement is recorded
  in `step_results`.

The wizard launcher also captures an **on-behalf-of** principal when
the flow is initiated for a group or service principal rather than the
signer themselves. The captured `on_behalf_of` value flows through the
workflow context and is persisted on derived artifacts (e.g., the data
product subscription's `on_behalf_of_type` / `on_behalf_of_value`
columns).

## Triggering an approval workflow {#triggers}

Approval workflows are matched by **trigger type**, not by name. The
wizard dialog dispatches on `for_*` triggers, which are 1:1 mirrors of
the corresponding `on_*` process triggers:

| Wizard trigger | Matching process trigger | Use |
|---|---|---|
| `for_approval_response` | (responds to a paused process workflow) | Approver acts on a step paused inside a running process workflow |
| `for_subscribe` | `on_subscribe` | Consumer subscribes to / signs a contract |
| `for_request_review` | `on_request_review` | Wizard before a review request |
| `for_request_access` | `on_request_access` | Wizard before an access grant request |
| `for_request_publish` | `on_request_publish` | Wizard before publish/deploy |
| `for_request_certify` | `on_request_certify` | Wizard before certification |
| `for_request_status_change` | `on_request_status_change` | Wizard before a status change |
| `on_first_access` | (same) | One-time terms-of-use acceptance at app entry |

`on_first_access` is a session trigger: the frontend fires it on app
mount when the current user has not yet accepted the workflow at its
latest version.

## Wizard step types {#step-types}

A workflow is an ordered list of steps. The `StepType` enum is the
authoritative catalog; the most common types for approval workflows are
listed below. Step branching uses `on_pass` / `on_fail` references to
other `step_id` slugs.

| Step type | Purpose |
|---|---|
| `validation` | Evaluate a compliance DSL rule; pass/fail branches. |
| `approval` | Pause execution; resume when configured approvers respond. |
| `user_action` | Collect free-form user input — reason, acceptances, custom fields. |
| `on_behalf_of` | Capture self / group / SP principal at wizard start. |
| `legal_document` | Display a legal text the signer must scroll through. |
| `acknowledgement_checklist` | Force tick-box acknowledgement of named statements. |
| `co_signers` | Collect additional acknowledging principals. |
| `policy_check` | Evaluate an existing compliance policy by UUID. |
| `conditional` | Branch on a DSL expression. |
| `notification` | Send in-app / email / webhook notification. |
| `webhook` | Call an external HTTP endpoint (via UC Connections or raw URL). |
| `generate_pdf` | Render a PDF from `step_results` + per-step `pdf_contribution`. |
| `persist_agreement` | Write the agreement record. |
| `deliver` | Dispatch the signed agreement through configured channels. |
| `grant_permissions` | Grant Unity Catalog permissions via the service principal client. |
| `assign_tag` / `remove_tag` | Mutate tags on the trigger entity. |
| `entity_action` | Apply a status action (certify, publish, etc.) on the trigger entity. |
| `create_asset_review` | Open a formal Data Asset Review for tracking. |
| `script` | Execute Python code (gated by deployment policy). |
| `pass` / `fail` | Terminal nodes. |

## Execution state machine {#execution-state-machine}

A `WorkflowExecutionDb` row tracks the runtime status of a single
workflow invocation. The `ExecutionStatus` enum:

`pending`, `running`, `paused`, `succeeded`, `failed`, `cancelled`.

- `pending` — created, not yet started.
- `running` — actively executing a step.
- `paused` — waiting for an external event (typically an `approval` or
  `user_action` step's response).
- `succeeded` — reached a `pass` terminal or completed all steps.
- `failed` — reached a `fail` terminal or a step raised.
- `cancelled` — explicitly cancelled by an authorized caller.

Per-step results live in `WorkflowStepExecutionDb` with
`StepExecutionStatus`: `pending`, `running`, `succeeded`, `failed`,
`skipped`. The `passed` boolean captures the branching outcome (used by
`validation`, `policy_check`, `conditional`).

## The `grant_permissions` step {#grant-permissions-step}

`grant_permissions` is the bridge from a signed agreement to real Unity
Catalog access. The step:

1. Reads the workflow execution context, including the resolved
   consumer principals from the underlying data product
   (`${entity.consumer_principals}` is available in templates because
   the product enrichment runs before the step).
2. Uses the Ontos service principal's workspace client to issue UC
   `GRANT` statements on the configured securables.
3. Records the issued grants in the workflow step's `result_data` for
   audit, so revocation can find them later.

The step requires the service principal to hold **`MANAGE`** on each
securable it grants on. `ALL_PRIVILEGES` is **not** sufficient. UC
accepts only account-level groups; workspace-only groups will be
rejected even if they resolve in the Ontos identity layer.

## Webhook steps {#webhook-step}

A `webhook` step calls an external HTTP endpoint either through a Unity
Catalog Connection (preferred for secrets handling) or by direct URL.
The step config includes `method`, `body_template`, headers, and
optional extras for caller-supplied additional headers, query
parameters, and path segments that can be templated from workflow
context. Body templates can reference workflow context variables
(`${entity.consumer_principals}`, `${entity.<custom_field>}`, etc.), so
the workflow can drive ITSM tickets, e-mail providers, or Slack
notifications without baking secrets into the workflow definition.

## Delivery {#delivery-step}

A `deliver` step (distinct from `delivery`) dispatches the completed
agreement through one or more channels: `in_app` (Ontos notification),
`email` (via EmailService), and `webhook` (HTTP POST). Email is the
only channel that may be silently stripped if no email provider is
configured; authors are expected to integrate their own email provider
via a webhook step instead.

## Agreement immutability and re-execution {#immutability}

Once persisted, an agreement is not edited. If a workflow definition
changes after an agreement is signed, the signed agreement still
references the original definition via `workflow_snapshot`. To re-run
an approval for the same entity (e.g., a new contract version), a new
wizard session is launched, producing a new agreement row.

## Common questions {#common-questions}

**"My consumer subscribed but didn't get access — what's missing?"**

Three usual causes. (1) The approval gate is paused waiting for the
Data Product Owner to respond — the workflow execution shows
`paused`, not `failed`. (2) The `grant_permissions` step ran but the
app SP doesn't have `MANAGE` on the target UC securable. (3) The
`consumer_principals` list resolves to a workspace-only group, which
UC rejects.

**"What's the difference between a Wizard Session and an Agreement?"**

The Wizard Session is in-flight — the user is mid-flow, hasn't
finished, can still go back. The Agreement is what gets written at
the end, immutable. The wizard session points at the agreement once
it's persisted; the agreement points back at the wizard session for
audit.

**"If I edit the workflow definition while a wizard is in progress,
what happens to that wizard?"**

Nothing immediate. The wizard session snapshotted the workflow
definition at the moment it was launched. The in-flight wizard
continues with the snapshot, not the latest definition. The
resulting agreement records the snapshot too. New wizard sessions
launched after the edit pick up the new definition.

**"How do I know which workflow runs when a consumer subscribes?"**

It's matched by trigger type. For a subscribe action, the wizard
dispatches `for_subscribe`. Any approval workflow with trigger
`for_subscribe` and a matching scope (workspace / domain / project)
is eligible; the most specific scope wins. The Settings → Workflows
view shows all active workflows and their triggers.

**"Can I see a list of all paused workflows waiting for me?"**

Yes — the in-app notification center shows pending approvals, and
the Agreements / Approvals page lists workflow executions where
you're a configured approver and the status is `paused`.

**"What's the relationship between `grant_permissions` and the
product's `consumer_principals` list?"**

The `consumer_principals` list on the product is the authoritative
list of "who is allowed to consume this product". When a subscribe
workflow runs, that list is part of the execution context. The
`grant_permissions` step reads the resolved principals via
`${entity.consumer_principals}` and issues UC `GRANT` statements
accordingly. Updating the list on the product after access is
already granted does *not* automatically revoke — you'd need a
matching revoke workflow.

## Cross-references {#cross-references}

- [Permission model](roles-and-rbac.md#permission-model) for outer
  feature-gate behavior vs per-execution authorization
- [Consumer principals](data-product-lifecycle.md#consumer-principals)
  for what the `grant_permissions` step actually grants to
- [Data contract](data-contract-lifecycle.md#what-is-a-contract) for
  the contract being signed against
- [End-to-end flows](end-to-end-flows.md) — where approval gates fall
  in the producer and consumer journeys

_Last verified against codebase: 2026-05-28_
