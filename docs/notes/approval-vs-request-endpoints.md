# Approval (sync wizard) vs Request (async) — Endpoints and Process Workflow Usage

## Two workflow types

The **process workflow** feature has two runtime modes:

| | **Process workflows** | **Approval workflows** |
|--|------------------------|------------------------|
| **Type** | `workflow_type: process` | `workflow_type: approval` |
| **Runtime** | **Async**: triggered by events, run by `WorkflowExecutor`, can pause at approval steps | **Sync in UI**: user runs a multi-step wizard; server tracks a **session** (current step, step results) |
| **Storage** | Domain “request” records (e.g. `access_grant_requests`) + `workflow_executions` (paused/running) | `agreement_wizard_sessions` (in progress) → on success → `agreements` |
| **User flow** | User submits a “request” → workflow runs (notify, maybe pause for approval) → approver responds later | User opens wizard → steps through in the UI → on “Finish” server creates agreement and runs completion_action (e.g. subscribe) |
| **Naming** | “Request” (async: something the user asked for, handled later) | “Approval” / “session” (sync: wizard run in the UI; session = server-side wizard state) |

So:

- **Request** = async flow: user creates a request record, a **process** workflow is triggered, and the outcome (approve/deny) happens later (e.g. approver gets a notification and uses “approval response”).
- **Approval (wizard)** = sync flow: user drives an **approval** workflow in the UI step-by-step; server keeps a **session** for resilience (resume/back); when the user completes, we persist an **agreement** only.

---

## What we have: endpoints by purpose

### 1. Process workflows (definitions and execution)

**Prefix:** `/api/workflows` — [workflows_routes.py](src/backend/src/routes/workflows_routes.py)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/workflows` | List workflow definitions (optional `?workflow_type=process` or `approval`, `?is_active=true/false`). Returns `{ workflows, total }`. |
| `GET /api/workflows/{id}` | Get one workflow by ID |
| `GET /api/workflows/for-trigger/{trigger_type}` | Get the **first active workflow** that declares the given trigger type. Optional `?entity_type=` narrows the match. Used for app-known UI actions; the app **never** relies on workflow name. Allowed values: `for_approval_response`, `for_subscribe`, `for_request_review`, `for_request_access`, `for_request_publish`, `for_request_status_change`. Returns same shape as GET by id; 404 if none. |
| `POST /api/workflows` | Create workflow |
| `PUT /api/workflows/{id}` | Update workflow |
| `DELETE /api/workflows/{id}` | Delete workflow |
| `GET /api/workflows/executions` | List workflow **executions** (process runs: pending, running, paused, completed, failed) |
| `POST /api/workflows/executions/{execution_id}/resume` | **Resume** a **paused** process workflow (approver approved/rejected) |
| `GET /api/workflows/executions/paused/by-entity` | Find paused executions for an entity (for approval UI) |
| `POST /api/workflows/handle-approval` | Handle approval from a notification (finds execution, resumes it, marks notification read) |

**Known-action trigger types:** The app looks up workflows by **trigger type**, not by human-readable name. In [process_workflows.py](src/backend/src/models/process_workflows.py), `TriggerType` includes `FOR_APPROVAL_RESPONSE`, `FOR_SUBSCRIBE`, `FOR_REQUEST_REVIEW`, `FOR_REQUEST_ACCESS`, `FOR_REQUEST_PUBLISH`, and `FOR_REQUEST_STATUS_CHANGE`. Each `FOR_*` matches a corresponding `ON_*` process trigger (e.g. `FOR_REQUEST_ACCESS` ↔ `ON_REQUEST_ACCESS`, `FOR_SUBSCRIBE` ↔ `ON_SUBSCRIBE`). Default workflows in `default_workflows.yaml` set `trigger.type` to these values so the app can find them via `GET /api/workflows/for-trigger/{trigger_type}`. All power the same ApprovalWizardDialog. Names can change or be localized.

These are used for **process** workflows: event-triggered runs that may pause at an approval step; the approver responds via resume/handle-approval.

---

### 2. “Approvals” — queue and **wizard (session)** API only

**Prefix:** `/api/approvals` — [approvals_routes.py](src/backend/src/routes/approvals_routes.py)

Workflow **definitions** are under `/api/workflows` only (list, get by id, get by trigger type). Approvals does **not** expose workflow listing or “default workflow” endpoints.

| Endpoint | Purpose |
|----------|---------|
| `GET /api/approvals/queue` | **ApprovalsManager**: list items “awaiting approval” (e.g. contracts in proposed/under_review, products in draft). Used for an “approvals queue” UI. Not driven by workflow executions directly. |
| **Wizard (sync) — session lifecycle** | |
| `POST /api/approvals/sessions` | **Create** a wizard session (workflow_id, entity_type, entity_id, completion_action). Returns session_id + first step. |
| `GET /api/approvals/sessions/{session_id}` | **Get** current step + step_results (for Back/refresh). |
| `POST /api/approvals/sessions/{session_id}/steps` | **Submit** one step; server advances and returns next step or `{ complete: true, agreement_id, ... }`. |
| `POST /api/approvals/sessions/{session_id}/abort` | **Abort** wizard (mark session abandoned). |

So under `/api/approvals` you have: **queue** + **session** API only. To get workflows for the approval response dialog use `GET /api/workflows/for-trigger/for_approval_response`; for the subscription wizard use `GET /api/workflows/for-trigger/for_subscribe`; for request wizards use `GET /api/workflows/for-trigger/for_request_access` (etc.); to list approval workflows for a picker use `GET /api/workflows?workflow_type=approval`.

---

### 3. Access grants — “request” (async) side

**Prefix:** `/api/access-grants` — [access_grants_routes.py](src/backend/src/routes/access_grants_routes.py)

| Endpoint | Purpose |
|----------|---------|
| `POST /api/access-grants/request` | **Create** an access grant **request**. This persists a row in `access_grant_requests` and fires **ON_REQUEST_ACCESS** (process workflow). |
| `GET /api/access-grants/my-requests` | List **requests** created by the current user (all statuses). Used by the **Requests** UI. |
| `GET /api/access-grants/requests/my` | Same idea (alternate path). |
| `GET /api/access-grants/requests/pending` | Pending requests (e.g. for admins). |
| `POST /api/access-grants/handle` | Approve/deny a request (admin). |
| `DELETE /api/access-grants/requests/{request_id}` | Cancel a pending request (requester). |
| … (entity, grants, config, etc.) | Other access-grant operations. |

So “request” here = the **async** flow: user creates a **request**; a **process** workflow runs (notify, approval step, etc.); approver handles it later. The “Requests” UI should show these.

---

## How process workflows are used (triggers and callers)

Process workflows are **triggered by events**. The trigger registry ([workflow_triggers.py](src/backend/src/common/workflow_triggers.py)) exposes methods like:

- `on_request_access` → **ON_REQUEST_ACCESS**
- `on_request_review` → **ON_REQUEST_REVIEW**
- `on_request_publish` → **ON_REQUEST_PUBLISH**
- `on_request_deploy` → **ON_REQUEST_DEPLOY**
- `on_request_status_change` → **ON_REQUEST_STATUS_CHANGE**
- `on_status_change` → **ON_STATUS_CHANGE**
- `on_create`, `on_update`, `on_delete`, `before_*`, job lifecycle, subscribe/unsubscribe, expiring, revoke, etc.

**Who fires these (examples):**

| Trigger | Fired from |
|---------|------------|
| **ON_REQUEST_ACCESS** | AccessGrantsManager (create access request), UserRoutes (role access), ProjectsManager, … |
| **ON_REQUEST_REVIEW** | DataAssetReviewsManager, … |
| **ON_REQUEST_PUBLISH** | DataContractsManager, data product routes (publish request) |
| **ON_REQUEST_DEPLOY** | DataContractsManager (deploy request) |
| **ON_REQUEST_STATUS_CHANGE** | DatasetsManager, DataProductsManager, DataContractsManager (status change requests) |
| **ON_STATUS_CHANGE** | DatasetsManager, DataProductsManager, DataContractsManager (after status actually changes) |
| **ON_CREATE / ON_UPDATE / ON_DELETE** | Various (contracts, products, …) |
| **ON_JOB_SUCCESS / ON_JOB_FAILURE** | JobsManager |
| **ON_SUBSCRIBE / ON_UNSUBSCRIBE** | Data products / datasets subscription |
| **ON_EXPIRING / ON_REVOKE** | AccessGrantsManager |

Flow:

1. Something happens (e.g. user creates access request).
2. Code calls `get_trigger_registry(db).on_request_access(...)` (or the right trigger).
3. Registry finds matching **process** workflows and runs them via **WorkflowExecutor**.
4. If a step is an **approval** step, the executor creates notifications and **pauses** the execution.
5. Approver later uses **approval response** (default workflow) and **POST /api/workflows/handle-approval** or **POST /api/workflows/executions/{id}/resume** to resume the run.

So:

- **Process workflows** = event-driven, async, can pause for approval; “request” endpoints (e.g. access-grants) create the domain request and fire the trigger.
- **Approval workflows** = only the **wizard** under `/api/approvals/sessions`; they do **not** use the trigger registry or WorkflowExecutor; they use AgreementWizardManager and sessions.

---

## Summary table

| Concept | Async (“request”) | Sync (“approval” wizard) |
|--------|--------------------|---------------------------|
| **Workflow type** | Process | Approval |
| **Stored** | Domain request (e.g. access_grant_requests) + workflow_executions | agreement_wizard_sessions → agreements |
| **Starts when** | Event (e.g. user creates request) → trigger → WorkflowExecutor | User clicks “Subscribe” / “Sign” → POST /api/approvals/sessions |
| **Approval** | Workflow pauses; approver uses GET /api/workflows/for-trigger/for_approval_response + resume/handle-approval | User completes wizard steps; server creates agreement |
| **List “my”** | e.g. GET /api/access-grants/my-requests | Sessions are not listed in Requests; completed agreements only (when “my agreements” is added) |
| **Requests UI** | Show these (access requests, and later other process requests) | Do **not** show sessions; show only **completed agreements** (when we add “my agreements”) |

So: **“Request”** = async, process-workflow-backed, something the user asked for and that is handled (or pending) later. **“Approval”** in the sense of the wizard = sync, approval-workflow, server-side session for the UI; sessions are not “requests” and should not appear in the Requests section.
