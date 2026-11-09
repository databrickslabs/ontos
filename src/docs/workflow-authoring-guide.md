# Workflow Authoring Guide

This guide explains how workflows behave when they run, so that what you build in **Compliance → Workflows** does what you expect. It covers the kinds of workflows, how an execution moves from step to step, how triggers are wired, the variables you can use in texts, how approvals pause and resume a workflow, what happens when something fails, and how to read **Recent Executions**.

For the field-by-field reference of every step type and the API, see the [Process Workflows Guide](/user-docs/process-workflows-guide). For the rule language used by validation, conditional and policy check steps, see the [Compliance DSL Guide](/user-docs/compliance-dsl-guide).

Everything below was checked against the code and on a running instance; the examples at the end were created through the API and run.

## Table of Contents

1. [Kinds of Workflows](#kinds-of-workflows)
2. [How an Execution Runs](#how-an-execution-runs)
3. [Triggers](#triggers)
4. [Step Types and What Makes Them Pass](#step-types-and-what-makes-them-pass)
5. [Variables and Templates](#variables-and-templates)
6. [Recipients and Approvers](#recipients-and-approvers)
7. [Approvals: Pausing and Resuming](#approvals-pausing-and-resuming)
8. [Gates: Blocking a Change](#gates-blocking-a-change)
9. [Failures, Retries and Cancellation](#failures-retries-and-cancellation)
10. [Debugging Recent Executions](#debugging-recent-executions)
11. [Worked Examples](#worked-examples)
12. [Known Limitations](#known-limitations)

---

## Kinds of Workflows

Ontos has two kinds of workflows, stored in the same tables and told apart by `workflow_type`:

| | Process workflow (`process`) | Approval workflow (`approval`) |
|--|--|--|
| **What it is** | Automation that runs on the server when an event happens | A wizard a user steps through in the browser (Next / Back) |
| **Started by** | A trigger (`on_*`, `before_*`, `manual`) | A UI action bound to a `for_*` trigger (or `on_first_access`) |
| **Runs in** | The workflow executor, inside the request that fired it | The wizard runtime (`/api/approvals/sessions/...`) |
| **Steps** | validation, conditional, policy check, approval, notification, tags, script, webhook, asset review, entity action, grant permissions, delivery, pass, fail | user action, legal document, acknowledgement checklist, co-signers, on behalf of, persist agreement, generate PDF, deliver, pass |
| **Examples** | "Status Change Request", "Data Contract Review Request" | "Request Status Change", "Subscription Agreement", "Approval response" |

"Trigger" is not a third kind: it is what starts a process workflow. The two kinds meet in request flows. For a status change request, for example, the "Request Status Change" wizard (`for_request_status_change`) collects the requester's reason, and the request then fires `on_request_status_change`, which runs the "Status Change Request" process workflow that asks for the approval.

The steps of one kind don't run in the other: a wizard step type put in a process workflow fails with `Unknown step type`.

## How an Execution Runs

These rules explain most surprises:

- **The first step is the entry step.** The executor starts at the first step of the workflow's step order. In the designer this is the step connected to the trigger. Through the API it is the first step of the `steps` list, unless you set `order` yourself.
- **Steps don't run in list order.** After a step, the executor goes to its `on_pass` step if it passed, or to its `on_fail` step if it failed. A step with no next step for its outcome ends the execution, even if more steps follow it in the list.
- **The outcome is the last step's result.** When the execution ends on a step that passed, the execution is `succeeded`; when it ends on a step that failed, it is `failed`. A failure that is routed to a notification step, which passes, therefore ends as `succeeded`. End every failure branch with a **Fail** step if the execution should show as failed (and, for gates, if the change should be blocked).
- **Execution is synchronous.** A workflow runs inside the request that fired it, until it ends or pauses. A slow webhook or script makes that request slow.
- **Every matching workflow runs.** When several active workflows match the same trigger and entity type, all of them run, one after the other, in no fixed order. A request that reports "the" workflow (for example `execution_id` in the response of a status change request) reports the first one that ran. Two active workflows with an approval step on the same trigger send two approval requests.

An execution has one of these statuses:

| Status | Meaning |
|--|--|
| `running` | Steps are being executed (you rarely see it, since execution is synchronous) |
| `paused` | Waiting at an approval step |
| `succeeded` | Ended on a step that passed |
| `failed` | Ended on a step that failed |
| `cancelled` | Cancelled by an admin while running or paused |

## Triggers

### Where each trigger fires

A workflow runs only if Ontos fires its trigger for an entity type the workflow lists (an empty `entity_types` list matches every type). This table lists where the current version fires each trigger:

| Trigger | Fired when | Entity types | Blocks the action? |
|--|--|--|--|
| `on_create`, `on_update`, `on_delete` | After a product, contract or domain is created, updated or deleted | `data_product`, `data_contract`, `domain` | No |
| `on_create` | After a catalog, schema or table is created through self-service | `catalog`, `schema`, `table` | No |
| `before_create` | Before a catalog, schema or table is created through self-service | `catalog`, `schema`, `table` | Yes |
| `before_update` | Before a contract is updated | `data_contract` | Yes |
| `before_status_change` | Before a product or contract changes status | `data_product`, `data_contract` | Yes |
| `on_status_change` | After a product, contract or asset review changes status | `data_product`, `data_contract`, `data_asset_review` | No |
| `on_request_review` | A review is requested | `data_product`, `data_contract`, `data_asset_review` | No |
| `on_request_status_change` | A status change is requested | `data_product` | No |
| `on_request_publish`, `on_request_certify` | Publication or certification is requested | `data_product`, `data_contract` | No |
| `on_request_deploy` | A contract deployment is requested | `data_contract` | No |
| `on_request_access` | Access is requested | `access_grant`, `project`, `role` | No |
| `on_publish`, `on_unpublish` | A product or contract is published or unpublished | `data_product`, `data_contract` | No |
| `on_certify`, `on_decertify` | A contract is certified or decertified from the contract page | `data_contract` | No |
| `on_subscribe` / `on_unsubscribe` | A user subscribes to / unsubscribes from a product | `data_product` / `subscription` | No |
| `on_expiring`, `on_revoke` | An access grant is about to expire, or is revoked | `access_grant` | No |
| `on_job_success`, `on_job_failure` | A background job ends | `job` | No |
| `on_maturity_change` | A maturity level changes | the evaluated entity | No |
| `manual` | `POST /api/workflows/{id}/execute?entity_type=...&entity_id=...&entity_name=...` (there is no button for it in the UI) | any | No |

`GET /api/workflows/trigger-types` returns the trigger catalog the designer uses, with each trigger's entity types.

Notes:

- **"After" triggers never undo the action.** The product is already created, updated or moved when an `on_*` workflow runs; if the workflow fails, the action stays done. Errors while firing them are logged and don't fail the action.
- **`scheduled` is not run.** It can be selected and saved, but nothing in the current version starts scheduled workflows.
- **`manual` runs see only what you pass.** A manual run passes `{id, name, type}` from the query as the trigger payload; without `entity_name`, `${entity_name}` is empty. Rule steps still see the stored entity (see below); notification texts and scripts only have those three fields.

### Filters

- **Entity types:** `entity_types` in the trigger. Empty means any.
- **Status:** for `on_status_change` and `before_status_change`, `from_status` and `to_status` restrict the transition. An empty value matches any status.
- **Scope:** the scope (project, catalog, domain) is saved with the workflow, but no trigger passes a scope today, so it isn't applied: a workflow scoped to one domain also runs for entities of other domains.

### Default workflows

- At startup, Ontos creates the default workflows that don't exist yet. Only the request workflows (`on_request_*`) are created active; the other defaults (automation, gates, UI wizards) are created inactive, so an upgrade doesn't turn on new automatic behavior. Workflows that already exist are left as they are.
- **Load New Only** (`POST /api/workflows/load-defaults`) does the same, keeping each workflow's `is_active` from the shipped definition.
- **Reload All Defaults** (`POST /api/workflows/load-defaults?update_existing=true`) rewrites every default workflow from the shipped definition, including `is_active`: defaults you had left inactive, such as "Naming Convention Validation", become active again. It also re-creates their steps, which removes the step history of their past executions (see [Debugging Recent Executions](#debugging-recent-executions)). Duplicates of defaults are not touched.
- A duplicate (`POST /api/workflows/{id}/duplicate?new_name=...`) starts inactive and is not a default.

## Step Types and What Makes Them Pass

Each step ends with a pass or a fail, which picks the next step. A step that raises an error fails, with the error text as its error.

| Step | Passes when | Fails when |
|--|--|--|
| `validation` | The rule's `ASSERT` holds | The assertion is false, or the rule or the entity can't be evaluated |
| `conditional` | The `condition` expression is true | It is false, or can't be evaluated |
| `policy_check` | The referenced compliance policy's rule holds, or the policy is inactive | The rule fails, or the policy doesn't exist |
| `approval` | The approver approves (the step pauses first) | The approver rejects, or no approver could be resolved |
| `notification` | At least one notification was created | None could be created |
| `assign_tag`, `remove_tag` | The tag was written or removed | The value couldn't be resolved or written |
| `script` | The script's `result` says so (see below) | `result` says not passed, the script raises, or times out |
| `webhook` | The response code is a success code (default 200-299) | Other codes, or the call fails after `retry_count` retries |
| `create_asset_review` | The review was created | It couldn't be created |
| `entity_action` | The action (certify, decertify, publish, unpublish, set publication scope) was applied | The action isn't allowed or fails |
| `grant_permissions` | The Unity Catalog grant was made | It couldn't be made |
| `pass` | Always | Never |
| `fail` | Never | Always; its `message` becomes the execution's error |

### What rules see

Validation, conditional and policy check steps evaluate their rule on `obj`:

- For data products and data contracts, `obj` is the **stored entity** (the fields maturity gates use, such as `status`, `has_owner`, `has_description`, `output_port_contract_count`, `certification_level`, `is_published`) merged with the trigger payload; payload fields win.
- For other entity types, and for `before_update` gates (whose payload is the proposed change), `obj` is the trigger payload only.
- If the stored entity can't be loaded, the step fails with the code `rule_entity_load_failed` instead of evaluating the rule on the payload alone.

A field that doesn't exist on `obj` makes comparisons like `obj.field != ''` true. Check fields that exist; the defaults use `obj.output_port_contract_count > 0`, `obj.schema_object_count > 0` and `obj.has_owner = true`.

In a validation step, only the `ASSERT` part is evaluated. When it fails, the step's message is `Assertion failed: ` followed by the text after `ASSERT`, including an `ON_FAIL FAIL '...'` clause if you wrote one; the `ON_FAIL` text is not used as a separate message. To show your own text, end the failure branch in a Fail step with a `message`, or use `${step_results.<step_id>.message}` in a notification.

### Scripts

A Python script runs with a small set of safe built-ins (`len`, `str`, `dict`, `sorted`, `min`, `max`, ...) and these variables: `entity` (the trigger payload), `entity_type`, `entity_id`, `entity_name`, `user_email`, `step_results`.

- Set a variable named `result`: `True` / `False`, or a dict `{"passed": bool, "message": str, "data": {...}}`. Without `result`, the step passes.
- Don't use `return`: the code isn't a function body, so `return` fails with `'return' outside function`.
- `import` is not available (`__import__ not found`).
- The step fails after `timeout_seconds` (default 60).

A SQL script runs on the SQL warehouse set in Settings, with variables substituted into the SQL text as they are: values are not quoted or escaped, so don't build SQL from user-entered fields.

## Variables and Templates

### Where variables are substituted

Variables are substituted in notification messages (`custom_message`), approval messages (`message`), webhook bodies, headers, query parameters and path suffixes, and SQL scripts. They are not substituted in rules or conditions.

Both `${name}` and `{{name}}` work. A variable that can't be resolved is left as written (for example `${entity.no_such_field}` stays in the text), which makes typos visible in the notification.

### Available variables

| Variable | Value |
|--|--|
| `${entity_name}`, `${entity_type}`, `${entity_id}` | The trigger entity |
| `${user_email}` | The user who fired the trigger; after an approval, the approver |
| `${workflow_name}`, `${workflow_id}`, `${execution_id}` | The running workflow and execution |
| `${entity.<field>}` | A field of the **trigger payload** (not of the stored entity). Nested paths work: `${entity.a.b}` |
| `${step_results.<step_id>.passed}` | Whether an earlier step passed (rendered as `True` / `False`) |
| `${step_results.<step_id>.message}` | An earlier step's message |
| `${step_results.<step_id>.data.<field>}` | A field of an earlier step's result data, for example a script's `data` |
| `${step_results.<approval_step_id>.decision}` | After an approval: `approved` or `rejected` |
| `${step_results.<approval_step_id>.reason}` | After an approval: the approver's message |
| `${context.<attribute>}` | An execution context attribute, for example `${context.on_behalf_of.value}` for subscriptions on behalf of a group |

Lists and objects are rendered as JSON, so a webhook body can carry them.

After an approval, the fields of the latest completed request wizard for the same entity (for example the requester's reason in "Request Status Change") are added under the approval step, and they replace fields with the same name: when that wizard has a `reason` field, `${step_results.<approval_step_id>.reason}` is the requester's reason, not the approver's. The approver's message is then still the step's error on a rejection.

### Trigger payloads

`${entity.*}` depends on what the trigger sends. Some examples from the current version:

| Trigger | Payload fields |
|--|--|
| `on_request_status_change` (product) | `product_id`, `product_name`, `from_status`, `target_status`, `justification`, `request_id` |
| `on_request_review` (product) | `product_id`, `product_name`, `from_status`, `to_status`, `message`, `reviewer_email`, `request_id` |
| `manual` | `id`, `name`, `type` |

For some trigger and entity type pairs, `GET /api/workflows/template-vars?trigger=<trigger>&entity_type=<type>` lists the variables with examples (the designer shows them next to webhook bodies). An empty list means that pair has no curated description, not that it has no variables.

## Recipients and Approvers

Notification `recipients` and approval `approvers` take one of these values, or several separated by commas:

| Value | Resolves to |
|--|--|
| `requester`, `trigger_user` | The user who fired the trigger (after an approval, see [Known Limitations](#known-limitations)) |
| `entity_owner` | The owners of the trigger entity (for an access grant, of the entity access is requested to) |
| `owner` | The payload's `owner` field, else as `entity_owner` |
| `DomainOwner` | An app role with that name if one exists; else the owners of the entity's domain, without the requester; else the Data Stewards and Admins |
| `ContractApprover` | An app role with that name if one exists; else the contract's owners, without the requester; else the Data Stewards and Admins |
| `data_stewards`, `admins`, `project_owners` | The Data Steward, Admin and Project Owner app roles |
| An app role name or id | Everyone in that role's groups (case, spaces and underscores are ignored in names) |
| `business:<role id>` | The users holding that business role for the entity |
| An email, or `user:<email>` | That user |

**A value that matches nothing is used as written**: `data_stewardz` creates a notification addressed to `data_stewardz`, which nobody sees, and the step passes. Check the `recipients` / `approvers` in the step's result data after a test run (see [Debugging](#debugging-recent-executions)).

## Approvals: Pausing and Resuming

### What an approval step does

1. It resolves its `approvers` and creates an **Approval Required** notification for each of them. Its `message` (with variables substituted) is shown in the notification and the approval dialog.
2. The execution pauses at that step (`paused`, **Waiting At** in Recent Executions).
3. When an approver decides, the execution resumes: an approval follows the step's `on_pass`, a rejection its `on_fail`. The approver's message becomes the step's error on a rejection, and is available as `${step_results.<step_id>.reason}`.

The approval step appears twice in the execution's step history: once when it asked for the approval, once with the decision.

`require_all` and `timeout_days` are stored with the step but not enforced in the current version: the first decision resumes the execution, and a paused execution waits until someone decides or an admin cancels it.

### Who can decide

The approval dialog (from the notification) calls `POST /api/workflows/handle-approval`:

```json
{ "execution_id": "<execution id>", "approved": true, "message": "Looks good" }
```

The caller must be a recipient of an approval notification for the step the execution is paused at (directly, or through the notification's role), or an admin. Others get `403 You are not an authorized approver for this execution`. For owner approvals (`DomainOwner`, `ContractApprover`), the requester can't decide their own request (`403`, code `own_owner_approval`). Once the step is decided, a second decision gets `404 Execution not found or not in paused state`. The approval notifications of the decided step are marked as handled.

### Resuming from another system

A webhook step doesn't wait for an answer: it calls the endpoint and passes or fails on the response. To have an external system decide, put an approval step after the webhook and let the system call:

```
POST /api/workflows/executions/{execution_id}/resume
{ "approved": true, "message": "...", "reason": "..." }
```

This endpoint requires read/write access to workflow settings and doesn't check approval notifications, so use it with an identity meant for automation. Send `${execution_id}` in the webhook body so the system knows which execution to resume.

### What Ontos does after a request is decided

When a request workflow resumes after an approval and ends, Ontos applies the decision:

| Workflow trigger | Entity | After approval | After rejection |
|--|--|--|--|
| `on_request_status_change` | data product | Applies the requested status, through the same checks and gates as a direct change | Nothing |
| `on_request_review` | data contract | Contract approved | Contract back to draft |
| `on_request_review` | data product | Product active | Product back to draft |
| `on_request_deploy` | data contract | Records `deploy_approve` in the change log (no status change) | Records `deploy_deny` |
| `on_request_certify`, `on_request_publish` | product, contract | Done by the workflow's `entity_action` step | Nothing |

This only happens after an approval step: a request workflow that never pauses doesn't change the entity.

## Gates: Blocking a Change

`before_create`, `before_update` and `before_status_change` workflows are gates: the action goes ahead only if every matching gate workflow ends `succeeded`. Otherwise it is refused. A refused status change returns an error (HTTP 400 from the status change endpoints, 409 from a contract's Approve / Reject actions) with this detail:

```json
{
  "detail": {
    "code": "status_change_blocked",
    "message": "Status transition from 'draft' to 'proposed' blocked by workflow: ...",
    "params": {
      "fromStatus": "draft",
      "toStatus": "proposed",
      "reasons": [{ "workflow": "<workflow name>", "text": "<fail step message>" }]
    }
  }
}
```

Each reason is the Fail step's `message` (or the failing step's message), so write it for the user who is refused.

**A gate that errors.** A gate whose evaluation raises an error (an exception, not a Fail step) is logged and the change goes ahead (#1103). A `PUT /api/data-products/{id}` or `PUT /api/data-contracts/{id}` that changes `status` doesn't run gates at all. STATUS_PR changes both: the trigger's `on_error` decides what a gate error does (`fail_open`, the default, lets the change through with a `GATE_ERROR` audit entry; `fail_closed` refuses it with `status_change_gate_error`), `disabled_for: {domains, data_products, data_contracts}` switches a gate off for those entities (audited as `GATE_SKIPPED`), and a `PUT` with a different `status` is refused with `status_change_requires_transition`.

**Don't put an approval in a gate.** A gate with an approval step pauses, which is not `succeeded`, so the change is refused with "waiting for approval", and approving later doesn't apply the change. To require an approval for a status change, use a status change request (`on_request_status_change`), which applies the change when it is approved.

## Failures, Retries and Cancellation

| What happens | Result |
|--|--|
| A step raises an error (SQL error, connection refused, ...) | The step fails with the error text; the executor follows its `on_fail` |
| `on_pass` / `on_fail` names a step that doesn't exist | Saving the workflow is refused (HTTP 400, `Step '<id>' references unknown step '<name>'`) |
| An `on_*` workflow fails | The action that fired it is already done and stays done |
| A gate fails or pauses | The action is refused |
| A gate's evaluation raises an error | The action goes ahead (STATUS_PR adds `on_error: fail_closed` to refuse it) |
| The server restarts while an execution is paused | It stays paused and can still be decided |

**Retry** (admins, failed executions only, `POST /api/workflows/executions/{id}/retry` or the Retry action in Recent Executions) runs the same execution again from the first step, with the trigger payload it was started with. Its previous step results are replaced, and every step runs again: notifications are sent again and webhooks called again.

**Cancel** (admins, running or paused executions) sets the execution to `cancelled`. The approval notifications of a cancelled execution stay in the approvers' list; deciding one gets `404`.

## Debugging Recent Executions

**Recent Executions** (Compliance → Workflows) lists executions with their status, current step and error. Open one to see each step:

| Step state | Meaning |
|--|--|
| Completed | The step ran and passed (for a step that ran more than once, its last run counts) |
| Failed | The step ran and failed; its error is shown under it |
| Waiting | The execution is paused at this step |
| Pending | The step has not run |

A step shows **Pending** when it was not on the path the execution took: in a finished execution, the steps of the branches not taken stay Pending. It is not an error.

If every step of an old execution shows Pending, its workflow was saved since: saving a workflow's steps (designer, `PUT /api/workflows/{id}` with `steps`, or Reload All Defaults) re-creates the steps, and the step results of its past executions are removed with the old steps. The execution itself, its status and error remain. (Fixed by WORKFLOWS_PR: steps are updated in place, and the results of a removed step are kept and shown under "Removed steps".)

What is stored for a step: its status, its error, and its result data (for example a notification's `recipients` and `message`, an approval's `approvers`, a webhook's URL). A validation step's failure message is not stored, only the rule; route the failure to a notification or a Fail step with a message to see it (fixed by WORKFLOWS_PR, which stores it as the step's error).

The **Error** column is the execution's error: the Fail step's message, or the message of the step it ended on. Step errors that carry a code are shown in the user's language.

The same data is in the API: `GET /api/workflows/executions?workflow_id=&status=` lists executions (without their steps), and `GET /api/workflows/executions/{id}` returns one with its steps.

### When a workflow didn't run

1. Is the workflow active?
2. Does Ontos fire its trigger for that entity type (see [Where each trigger fires](#where-each-trigger-fires))? `scheduled` never runs.
3. For status triggers, do `from_status` / `to_status` match the transition?
4. For a request, the response carries `execution_id` and `workflow_status` when a workflow ran.
5. The backend log has `Trigger fired: <trigger> for <entity type> '<id>'` for every trigger and `Found N matching workflow(s)` when some workflow matched.

## Worked Examples

Each example is the body of `POST /api/workflows`; the designer builds the same steps.

### A manual check with two branches

Checks that a product is active and tells the caller either way; the failure branch ends in a Fail step so the execution shows as failed.

```json
{
  "name": "Check product status",
  "trigger": { "type": "manual", "entity_types": ["data_product"] },
  "is_active": true,
  "steps": [
    { "step_id": "check-active", "name": "Check status", "step_type": "validation",
      "config": { "rule": "MATCH (obj:Object)\nASSERT obj.status = 'active'" },
      "on_pass": "notify-ok", "on_fail": "notify-not-active" },
    { "step_id": "notify-ok", "step_type": "notification",
      "config": { "recipients": "requester", "template": "validation_passed",
                  "custom_message": "${entity_name} is active" },
      "on_pass": "done" },
    { "step_id": "notify-not-active", "step_type": "notification",
      "config": { "recipients": "requester", "template": "validation_failed",
                  "custom_message": "${entity_name} is not active: ${step_results.check-active.message}" },
      "on_pass": "rejected" },
    { "step_id": "done", "step_type": "pass" },
    { "step_id": "rejected", "step_type": "fail", "config": { "message": "Product is not active" } }
  ]
}
```

Run it with `POST /api/workflows/{id}/execute?entity_type=data_product&entity_id=<product id>&entity_name=<product name>`. Although a manual run only passes the id and the name, the rule sees the stored status. On an active product the execution succeeds and the dialog shows "Tell the caller it failed" and "Rejected" as Pending; on a draft product it fails with "Product is not active".

### A gate before submitting a product for review

```json
{
  "name": "Description before review",
  "trigger": { "type": "before_status_change", "entity_types": ["data_product"], "to_status": "proposed" },
  "is_active": true,
  "steps": [
    { "step_id": "has-description", "step_type": "validation",
      "config": { "rule": "MATCH (obj:Object)\nASSERT obj.has_description = true" },
      "on_pass": "ok", "on_fail": "blocked" },
    { "step_id": "ok", "step_type": "pass" },
    { "step_id": "blocked", "step_type": "fail",
      "config": { "message": "Describe the product's purpose before submitting it for review" } }
  ]
}
```

Moving a product without a description to `proposed` is refused with `status_change_blocked` and that message; moving it to `sandbox` is not affected.

### Telling the Data Stewards about a status change request

```json
{
  "name": "Tell stewards about status change requests",
  "trigger": { "type": "on_request_status_change", "entity_types": ["data_product"] },
  "is_active": true,
  "steps": [
    { "step_id": "tell-stewards", "step_type": "notification",
      "config": { "recipients": "data_stewards", "template": "request_submitted",
                  "custom_message": "${user_email} asks to move ${entity.product_name} from ${entity.from_status} to ${entity.target_status}: ${entity.justification}" },
      "on_pass": "done" },
    { "step_id": "done", "step_type": "pass" }
  ]
}
```

It runs next to the default "Status Change Request" workflow, which still asks for the approval. The stewards get, for example, "producer@example.com asks to move Customer 360 Banking v1 from active to deprecated: Superseded by Customer 360 v2".

### An approval with the decision in the next message

```json
{
  "name": "Steward check",
  "trigger": { "type": "manual", "entity_types": ["data_product"] },
  "is_active": true,
  "steps": [
    { "step_id": "ask", "step_type": "approval",
      "config": { "approvers": "steward@example.com", "message": "Please check ${entity_name}" },
      "on_pass": "yes", "on_fail": "no" },
    { "step_id": "yes", "step_type": "notification",
      "config": { "recipients": "data_stewards", "template": "request_approved",
                  "custom_message": "${user_email} approved ${entity_name}: ${step_results.ask.reason}" },
      "on_pass": "done" },
    { "step_id": "done", "step_type": "pass" },
    { "step_id": "no", "step_type": "fail", "config": { "message": "Denied" } }
  ]
}
```

The steward sees "Please check <product>" in the approval notification. After they approve with "looks fine", `${user_email}` is the steward and `${step_results.ask.reason}` is "looks fine".

### A script that returns data to later steps

```json
{
  "name": "Score the name",
  "trigger": { "type": "manual", "entity_types": ["data_product"] },
  "is_active": true,
  "steps": [
    { "step_id": "score", "step_type": "script",
      "config": { "language": "python",
                  "code": "ok = entity_name.startswith('Trading')\nresult = {'passed': ok, 'message': 'name checked', 'data': {'len': len(entity_name)}}" },
      "on_pass": "tell", "on_fail": "bad" },
    { "step_id": "tell", "step_type": "notification",
      "config": { "recipients": "requester", "template": "validation_passed",
                  "custom_message": "Name length: ${step_results.score.data.len}" },
      "on_pass": "done" },
    { "step_id": "done", "step_type": "pass" },
    { "step_id": "bad", "step_type": "fail", "config": { "message": "Script said no" } }
  ]
}
```

Run on "Trading Analytics Dashboard v1" (with `entity_name` in the query), the notification says "Name length: 30". Without `entity_name`, the script fails on `None.startswith` and the execution fails with "Script said no".

## Known Limitations

As of this version:

- **After an approval, `requester` and `trigger_user` resolve to the approver**, as does `${user_email}`: a notification to the requester after an approval reaches the approver instead. Until this is fixed (PR #1017), address the requester after an approval by email, or notify them before the approval step.
- `scheduled` triggers are not run (see #941).
- Workflow scopes are saved but not applied.
- A gate whose evaluation errors lets the change through, and a `PUT` that changes `status` skips gates (STATUS_PR adds `on_error` and refuses that `PUT`).
- An approval step's `require_all` and `timeout_days` are not enforced.
- Saving a workflow's steps removes the step results of its past executions (fixed by WORKFLOWS_PR).
- A validation step's failure message is not stored with the step (fixed by WORKFLOWS_PR).
- Reload All Defaults also resets the defaults' active flag to the shipped value.
- After an approval, a field of the entity's latest completed request wizard replaces an approval field with the same name (`${step_results.<approval_step_id>.reason}` can be the requester's reason) (fixed by WORKFLOWS_PR).
- The `config` example of the script step in the API schema uses `return`, which fails; set `result` instead (fixed by WORKFLOWS_PR).

See also the [Future Roadmap section of the Process Workflows Guide](/user-docs/process-workflows-guide#future-roadmap-deferred-items) for timeout expiry, escalation and crash recovery.
