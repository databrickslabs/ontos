# Process Workflows Guide

This guide provides comprehensive documentation for the **Process Workflows** system in Ontos. Process workflows enable automated, event-driven business processes for validation, approval, notifications, and data governance tasks.

> **Note:** These are internal application workflows for process automation, distinct from Databricks job workflows used for data processing.

---

## Table of Contents

1. [Overview](#overview)
2. [Process vs Approval Workflows](#process-vs-approval-workflows)
3. [Architecture](#architecture)
4. [Workflow Definitions](#workflow-definitions)
5. [Trigger System](#trigger-system)
6. [Step Types and Handlers](#step-types-and-handlers)
7. [Execution Tracking](#execution-tracking)
8. [Compliance DSL Integration](#compliance-dsl-integration)
9. [Visual Workflow Designer](#visual-workflow-designer)
10. [Default Workflows](#default-workflows)
11. [API Reference](#api-reference)
12. [Examples](#examples)
13. [Best Practices](#best-practices)

---

## Overview

### What are Process Workflows?

Process workflows are configurable, automated sequences of actions that execute in response to events within the Ontos application. They provide:

- **Event-driven automation**: Trigger workflows when entities are created, updated, or change status
- **Validation**: Check entities against compliance rules using the Compliance DSL
- **Approval gates**: Pause workflows pending human approval
- **Notifications**: Alert stakeholders about events or validation results
- **Tag management**: Automatically assign or remove tags based on conditions
- **Conditional branching**: Route workflow execution based on step outcomes

### Key Use Cases

| Use Case | Description |
|----------|-------------|
| **Pre-Creation Validation** | Block asset creation if naming conventions or required tags are missing (inline validation) |
| **Naming Convention Validation** | Validate that new catalogs, schemas, and tables follow naming standards |
| **Data Contract Validation** | Ensure contracts have required schema definitions and ownership |
| **Approval Workflows** | Require manager approval before publishing data products |
| **PII Detection** | Automatically tag tables containing sensitive data |
| **Subscription Notifications** | Notify consumers when subscribed datasets are updated |
| **Compliance Auditing** | Verify entities meet governance requirements |

---

## Process vs Approval Workflows

Workflows are stored in the same tables (`process_workflows`, `workflow_steps`) and distinguished by **workflow_type**:

| | Process workflows | Approval workflows |
|--|-------------------|---------------------|
| **What** | Event-driven automation (validation, notifications, blocking approval, tags). | Multi-step wizard in one session; agreement record; optional PDF. |
| **Runtime** | `WorkflowExecutor` (triggers, pause/resume). | Wizard runtime (session, submit step, complete/abort). |
| **Examples** | "Data Contract Review Request", "Naming Convention Validation". | "Sign data contract", "Promote Business Term". |
| **UI** | Settings → Workflows: list/edit **Process workflows** only (filter by `workflow_type=process`). | Approvals area or entity action "Sign contract" / "Start approval": list **Approval workflows** only; run wizard. |

- **Process workflows** (`workflow_type: process`): Triggered by events (on_create, on_status_change, etc.). Can pause for async approval; when an approver responds, the app uses the **default approval workflow** (e.g. "Enter a reason" + Approve/Reject) instead of a hardcoded dialog; completion calls the existing resume endpoint.
- **Approval workflows** (`workflow_type: approval`): User runs a multi-step wizard (Next/Back). On completion an **agreement** record is created and optionally a **PDF** (if the workflow includes a `generate_pdf` step). The flow is always recorded in the **entity change log** with a link to the agreement.

List APIs accept `?workflow_type=process` or `?workflow_type=approval`. The frontend Workflows page offers tabs "Process workflows" and "Approval workflows".

### Example approval workflow YAML

```yaml
workflows:
  - id: "sign-data-contract"
    name: "Sign data contract"
    description: "Multi-step wizard: acknowledge terms, enter reason, optional PDF."
    workflow_type: "approval"
    trigger:
      type: "manual"
      entity_types: []
    scope:
      type: "all"
    is_active: true
    is_default: false
    steps:
      - id: "terms"
        name: "Acknowledge terms"
        type: "user_action"
        config:
          title: "Terms and conditions"
          description: "Review and acknowledge the data contract terms."
          required_acceptances:
            - id: "accepted_terms"
              label: "I have read and accept the terms"
              type: "checkbox"
          required_fields:
            - id: "reason"
              label: "Reason for signing"
              type: "text"
              required: true
        on_pass: "done"
        on_fail: "done"
      - id: "done"
        name: "Done"
        type: "pass"
```

The **default approval response** workflow (used when an approver responds to a process-workflow approval request) is named "Approval response" and is loaded from `default_workflows.yaml`; it has one `user_action` step with a required "reason" field and Approve/Reject is handled by the resume endpoint.

---

## Architecture

### System Components

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              TRIGGER LAYER                                  │
│   TriggerRegistry: Fires events when entities are created/updated/deleted   │
│   Location: src/backend/src/common/workflow_triggers.py                     │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MANAGER LAYER                                  │
│   WorkflowsManager: CRUD operations, workflow matching, YAML loading        │
│   Location: src/backend/src/controller/workflows_manager.py                 │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              EXECUTOR LAYER                                 │
│   WorkflowExecutor: Step orchestration, branching, state management         │
│   Step Handlers: Type-specific execution logic                              │
│   Location: src/backend/src/common/workflow_executor.py                     │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            PERSISTENCE LAYER                                │
│   ProcessWorkflowDb: Workflow definitions                                   │
│   WorkflowStepDb: Step configurations                                       │
│   WorkflowExecutionDb: Execution history (per user/entity)                  │
│   WorkflowStepExecutionDb: Per-step results                                 │
│   Location: src/backend/src/db_models/process_workflows.py                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```text
1. EVENT OCCURS
   └── User creates a Data Contract via the UI

2. TRIGGER FIRED
   └── Application code calls TriggerRegistry.on_create()

3. WORKFLOW MATCHING
   └── WorkflowsManager finds workflows matching:
       - Trigger type: on_create
       - Entity type: contract
       - Scope: all (or specific project/domain)

4. EXECUTION
   └── WorkflowExecutor runs each matched workflow:
       ├── Creates WorkflowExecutionDb record
       ├── Executes steps sequentially with branching
       ├── Records step results in WorkflowStepExecutionDb
       └── Updates final status (succeeded/failed/paused)

5. RESULTS
   └── API returns execution results to caller
```

---

## Workflow Definitions

### Database Schema

Workflow definitions are stored in the `ProcessWorkflowDb` table:

| Column | Type | Description |
|--------|------|-------------|
| `id` | String (UUID) | Primary key |
| `name` | String | Unique workflow name |
| `description` | Text | Human-readable description |
| `trigger_config` | JSON | Trigger configuration |
| `scope_config` | JSON | Scope restrictions |
| `is_active` | Boolean | Whether workflow is enabled |
| `is_default` | Boolean | True for system-provided workflows |
| `version` | Integer | Optimistic locking version |
| `created_at` | Timestamp | Creation timestamp |
| `updated_at` | Timestamp | Last update timestamp |
| `created_by` | String | Creator's email |
| `updated_by` | String | Last updater's email |

### Trigger Configuration

The `trigger_config` JSON defines when the workflow executes:

```json
{
  "type": "on_create",
  "entity_types": ["contract", "product"],
  "from_status": null,
  "to_status": null,
  "schedule": null
}
```

### Scope Configuration

The `scope_config` JSON restricts workflow applicability:

```json
{
  "type": "project",
  "ids": ["project-123", "project-456"]
}
```

| Scope Type | Description |
|------------|-------------|
| `all` | Applies to all entities |
| `project` | Only entities in specified projects |
| `catalog` | Only entities in specified catalogs |
| `domain` | Only entities in specified domains |

### Pydantic Models

**Location:** `src/backend/src/models/process_workflows.py`

```python
class ProcessWorkflow(BaseModel):
    id: str
    name: str
    description: Optional[str]
    trigger: WorkflowTrigger
    scope: WorkflowScope
    steps: List[WorkflowStep]
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime

class WorkflowTrigger(BaseModel):
    type: TriggerType
    entity_types: List[EntityType]
    from_status: Optional[str]
    to_status: Optional[str]
    schedule: Optional[str]

class WorkflowScope(BaseModel):
    type: ScopeType  # all, project, catalog, domain
    ids: List[str]
```

---

## Trigger System

### TriggerRegistry

**Location:** `src/backend/src/common/workflow_triggers.py`

The `TriggerRegistry` provides a centralized interface for firing events and executing matching workflows.

### Trigger Types

| Type | Enum Value | Description |
|------|------------|-------------|
| Before Create | `before_create` | **Pre-creation validation** - blocks creation if workflow fails |
| Before Update | `before_update` | **Pre-update validation** - blocks update if workflow fails |
| On Create | `on_create` | Entity is created (post-creation) |
| On Update | `on_update` | Entity is modified (post-update) |
| On Delete | `on_delete` | Entity is deleted |
| On Status Change | `on_status_change` | Entity status changes (e.g., draft → published) |
| Scheduled | `scheduled` | Cron-based execution |
| Manual | `manual` | User-initiated execution |

> **Pre-Creation vs Post-Creation Triggers:** Use `before_create`/`before_update` for inline validation that must pass before an entity is saved. Use `on_create`/`on_update` for asynchronous actions like notifications or tagging that run after the entity is already persisted.

### Entity Types

| Entity | Enum Value | Description |
|--------|------------|-------------|
| Catalog | `catalog` | Unity Catalog catalog |
| Schema | `schema` | Unity Catalog schema |
| Table | `table` | Unity Catalog table |
| View | `view` | Unity Catalog view |
| Function | `function` | Unity Catalog function |
| Model | `model` | Unity Catalog model |
| Product | `product` | Data Product |
| Contract | `contract` | Data Contract |
| Dataset | `dataset` | Dataset implementation |
| Domain | `domain` | Data Domain |
| Glossary Term | `glossary_term` | Business glossary term |
| Review | `review` | Data Asset Review |

### Usage Examples

#### Firing an On-Create Trigger

```python
from src.common.workflow_triggers import get_trigger_registry
from src.models.process_workflows import EntityType

# Get registry with database session
registry = get_trigger_registry(db_session)

# Fire trigger when contract is created
executions = registry.on_create(
    entity_type=EntityType.CONTRACT,
    entity_id="contract-uuid-123",
    entity_name="Customer Data Contract",
    entity_data={
        "name": "Customer Data Contract",
        "schema": {"fields": [...]},
        "owner": "alice@company.com",
    },
    user_email="alice@company.com",
    scope_type="project",
    scope_id="project-456",
)

# Process results
for execution in executions:
    print(f"Workflow: {execution.workflow_id}, Status: {execution.status}")
```

#### Firing a Status Change Trigger

```python
executions = registry.on_status_change(
    entity_type=EntityType.PRODUCT,
    entity_id="product-uuid-789",
    from_status="draft",
    to_status="published",
    entity_name="Customer 360 Product",
    entity_data={...},
    user_email="bob@company.com",
)
```

#### Firing a Before-Create Trigger (Blocking Validation)

```python
# before_create returns a tuple: (all_passed, executions)
all_passed, executions = registry.before_create(
    entity_type=EntityType.TABLE,
    entity_id="catalog.schema.table_name",
    entity_name="table_name",
    entity_data={
        "name": "table_name",
        "catalog": "catalog",
        "schema": "schema",
        "tags": {"owner": "alice@company.com"},
    },
    user_email="alice@company.com",
)

# Block creation if validation failed
if not all_passed:
    raise HTTPException(status_code=400, detail="Pre-creation validation failed")

# Proceed with creation only if all workflows passed
```

> **Important:** The `before_create` and `before_update` triggers execute **synchronously** and return a boolean indicating whether all workflows passed. This enables blocking creation/update operations if validation fails.

### TriggerEvent Dataclass

```python
@dataclass
class TriggerEvent:
    trigger_type: TriggerType
    entity_type: EntityType
    entity_id: str
    entity_name: Optional[str] = None
    entity_data: Optional[Dict[str, Any]] = None
    user_email: Optional[str] = None
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    scope_type: Optional[str] = None
    scope_id: Optional[str] = None
```

---

## Step Types and Handlers

### Step Handler Architecture

Each step type has a dedicated handler class that inherits from `StepHandler`:

```python
class StepHandler(ABC):
    def __init__(self, db: Session, config: Dict[str, Any]):
        self._db = db
        self._config = config

    @abstractmethod
    def execute(self, context: StepContext) -> StepResult:
        pass
```

### Handler Registry

**Location:** `src/backend/src/common/workflow_executor.py`

```python
class WorkflowExecutor:
    HANDLERS: Dict[str, type] = {
        'validation': ValidationStepHandler,
        'approval': ApprovalStepHandler,
        'notification': NotificationStepHandler,
        'assign_tag': AssignTagStepHandler,
        'remove_tag': RemoveTagStepHandler,
        'conditional': ConditionalStepHandler,
        'script': ScriptStepHandler,
        'pass': PassStepHandler,
        'fail': FailStepHandler,
        'policy_check': PolicyCheckStepHandler,
        'webhook': WebhookStepHandler,
    }
```

### Step Types Reference

#### 1. Validation Step

Evaluates compliance rules using the Compliance DSL.

| Config Key | Type | Description |
|------------|------|-------------|
| `rule` | String | Compliance DSL rule expression |

**Example Configuration:**
```yaml
step_type: validation
config:
  rule: |
    MATCH (obj:Object)
    ASSERT obj.name MATCHES "^[a-z][a-z0-9_]*$"
    ON_FAIL: NOTIFY("Naming convention violation")
```

**Handler:** `ValidationStepHandler`

```python
def execute(self, context: StepContext) -> StepResult:
    from src.common.compliance_dsl import evaluate_rule_on_object
    
    rule = self._config.get('rule', '')
    passed, message = evaluate_rule_on_object(rule, context.entity)
    
    return StepResult(passed=passed, message=message, data={'rule': rule})
```

#### 2. Approval Step

Creates an approval request and pauses workflow execution.

| Config Key | Type | Description |
|------------|------|-------------|
| `approvers` | String | Approver specification (email, group, or role) |
| `timeout_days` | Integer | Days before approval expires |
| `require_all` | Boolean | Require all approvers (vs. any one) |

**Approver Specifications:**
- `domain_owners` - Owners of the entity's domain
- `project_owners` - Owners of the entity's project
- `requester` - User who triggered the workflow
- `user@example.com` - Specific email address
- `group-name` - Directory group name

**Example Configuration:**
```yaml
step_type: approval
config:
  approvers: domain_owners
  timeout_days: 7
  require_all: false
```

**Handler:** `ApprovalStepHandler`

> **Note:** When an approval step executes, the workflow enters `PAUSED` status. The workflow resumes when the approval is granted or rejected.

#### 3. Notification Step

Sends notifications to specified recipients.

| Config Key | Type | Description |
|------------|------|-------------|
| `recipients` | String | Recipient specification |
| `template` | String | Predefined message template |
| `custom_message` | String | Custom notification message |

**Recipient Specifications:**
- `requester` - User who triggered the workflow
- `owner` - Entity owner
- `user@example.com` - Specific email
- `group-name` - Directory group

**Available Templates:**
- `validation_failed` - Validation failure notification
- `validation_passed` - Validation success notification
- `product_approved` - Product approval notification
- `product_rejected` - Product rejection notification
- `approval_requested` - Approval request notification

**Example Configuration:**
```yaml
step_type: notification
config:
  recipients: requester
  template: validation_failed
```

**Handler:** `NotificationStepHandler`

#### 4. Assign Tag Step

Assigns a tag to the entity.

| Config Key | Type | Description |
|------------|------|-------------|
| `key` | String | Tag key name |
| `value` | String | Static tag value |
| `value_source` | String | Dynamic value source |

**Value Sources:**
- `current_user` - Email of user who triggered workflow
- `project_name` - Name of the entity's project
- `entity_name` - Name of the entity
- `timestamp` - Current ISO timestamp

**Example Configuration:**
```yaml
step_type: assign_tag
config:
  key: owner
  value_source: current_user
```

**Handler:** `AssignTagStepHandler`

#### 5. Remove Tag Step

Removes a tag from the entity.

| Config Key | Type | Description |
|------------|------|-------------|
| `key` | String | Tag key to remove |

**Example Configuration:**
```yaml
step_type: remove_tag
config:
  key: pending_review
```

**Handler:** `RemoveTagStepHandler`

#### 6. Conditional Step

Evaluates a condition using the Compliance DSL for branching.

| Config Key | Type | Description |
|------------|------|-------------|
| `condition` | String | DSL expression that evaluates to boolean |

**Example Configuration:**
```yaml
step_type: conditional
config:
  condition: obj.classification == "PII"
```

**Handler:** `ConditionalStepHandler`

#### 7. Script Step

Executes custom Python or SQL code.

| Config Key | Type | Description |
|------------|------|-------------|
| `language` | String | `python` or `sql` |
| `code` | String | Script code to execute |
| `timeout_seconds` | Integer | Maximum execution time |

**Example Configuration:**
```yaml
step_type: script
config:
  language: python
  code: |
    # Access entity data via 'entity' variable
    # Access step results via 'step_results' dict
    # Return a dict with 'passed' boolean and optional 'message'
    if entity.get('row_count', 0) > 1000000:
        return {'passed': True, 'message': 'Large table detected'}
    return {'passed': True}
  timeout_seconds: 30
```

**Handler:** `ScriptStepHandler`

> **Security Note:** Script execution runs in a restricted sandbox. Only approved functions and modules are available.

#### 8. Pass Step (Terminal)

Terminal step indicating successful workflow completion.

**Example Configuration:**
```yaml
step_type: pass
config:
  message: Validation completed successfully
```

**Handler:** `PassStepHandler`

#### 9. Fail Step (Terminal)

Terminal step indicating workflow failure.

| Config Key | Type | Description |
|------------|------|-------------|
| `message` | String | Failure message |

**Example Configuration:**
```yaml
step_type: fail
config:
  message: Data contract requires a schema definition
```

**Handler:** `FailStepHandler`

#### 10. Policy Check Step

Evaluates an existing compliance policy by its UUID. This allows workflows to reference centrally-managed compliance policies rather than duplicating DSL rules in workflow definitions.

| Config Key | Type | Description |
|------------|------|-------------|
| `policy_id` | String (UUID) | The UUID of the compliance policy to evaluate |

**Example Configuration:**
```yaml
step_type: policy_check
config:
  policy_id: "550e8400-e29b-41d4-a716-446655440000"
```

**Handler:** `PolicyCheckStepHandler`

```python
def execute(self, context: StepContext) -> StepResult:
    from src.db_models.compliance import CompliancePolicyDb
    from src.common.compliance_dsl import evaluate_rule_on_object
    
    policy_id = self._config.get('policy_id', '')
    if not policy_id:
        return StepResult(passed=False, error="No policy_id configured")
    
    # Look up policy by UUID
    policy = self._db.get(CompliancePolicyDb, policy_id)
    if not policy:
        return StepResult(passed=False, error=f"Policy not found: {policy_id}")
    
    if not policy.is_active:
        return StepResult(passed=True, message=f"Policy '{policy.name}' is inactive, skipped")
    
    # Evaluate the policy's rule
    passed, message = evaluate_rule_on_object(policy.rule, context.entity)
    
    return StepResult(
        passed=passed,
        message=message,
        data={'policy_id': policy_id, 'policy_name': policy.name, 'rule': policy.rule}
    )
```

> **Best Practice:** Use `policy_check` steps instead of `validation` steps when you want to centralize compliance rule management. This ensures that policy updates automatically apply to all workflows referencing that policy.

#### 11. Webhook Step

Calls external HTTP endpoints to integrate with external systems like ServiceNow, Slack, PagerDuty, or custom APIs. Supports two modes:

1. **UC Connection mode** (Recommended): Uses a pre-configured Unity Catalog HTTP Connection for secure credential management
2. **Inline mode**: Provides URL and credentials directly in configuration (for testing/simple cases)

| Config Key | Type | Description |
|------------|------|-------------|
| `connection_name` | String | UC HTTP Connection name (if using UC mode) |
| `url` | String | Target URL (if using inline mode) |
| `method` | String | HTTP method: GET, POST, PUT, PATCH, DELETE (default: POST) |
| `path` | String | Path appended to connection base URL (for UC mode) |
| `headers` | Object | Custom headers (merged with connection headers) |
| `body_template` | String | JSON body with `${variable}` substitution |
| `timeout_seconds` | Integer | Request timeout (default: 30) |
| `success_codes` | Array[Integer] | HTTP codes considered success (default: 200-299) |
| `retry_count` | Integer | Number of retries on failure (default: 0) |

**Template Variables:**
- `${entity_type}`, `${entity_id}`, `${entity_name}` - Entity information
- `${user_email}`, `${workflow_name}`, `${execution_id}` - Execution context
- `${step_results.step_id.data.field}` - Data from previous steps

**Example Configuration (UC Connection):**
```yaml
step_type: webhook
config:
  connection_name: servicenow-prod  # Pre-configured in Unity Catalog
  method: POST
  path: /api/now/table/incident
  body_template: |
    {
      "short_description": "Alert: ${entity_name}",
      "description": "Entity ${entity_type}/${entity_id} triggered workflow ${workflow_name}",
      "urgency": "2"
    }
  timeout_seconds: 30
on_pass: notify-success
on_fail: notify-failure
```

**Example Configuration (Inline URL):**
```yaml
step_type: webhook
config:
  url: https://hooks.slack.com/services/T00/B00/XXX
  method: POST
  headers:
    Content-Type: application/json
  body_template: |
    {
      "text": "Workflow completed for ${entity_name}"
    }
on_pass: done
```

**Handler:** `WebhookStepHandler`

> **Security Note:** UC Connections are recommended for production use as credentials are stored securely in Unity Catalog and managed by administrators. Inline mode stores credentials in workflow configuration.

---

## Execution Tracking

### Execution Context

When a workflow executes, a `StepContext` object is passed to each step handler:

```python
@dataclass
class StepContext:
    entity: Dict[str, Any]          # Entity data (mutable)
    entity_type: str                 # Entity type name
    entity_id: str                   # Entity identifier
    entity_name: Optional[str]       # Entity display name
    user_email: Optional[str]        # User who triggered workflow
    trigger_context: TriggerContext  # Full trigger information
    execution_id: str                # Workflow execution ID
    workflow_id: str                 # Workflow definition ID
    workflow_name: str               # Workflow name
    step_results: Dict[str, Any]     # Results from previous steps
```

### Execution Database Schema

#### WorkflowExecutionDb

Tracks each workflow execution:

| Column | Type | Description |
|--------|------|-------------|
| `id` | String (UUID) | Execution ID |
| `workflow_id` | String (FK) | Workflow definition ID |
| `trigger_context` | JSON | Trigger event details |
| `status` | String | Execution status |
| `current_step_id` | String | Current step (if paused) |
| `success_count` | Integer | Steps that passed |
| `failure_count` | Integer | Steps that failed |
| `error_message` | Text | Error details (if failed) |
| `started_at` | Timestamp | Start time |
| `finished_at` | Timestamp | Completion time |
| `triggered_by` | String | User email |

**Execution Statuses:**
- `pending` - Waiting to start
- `running` - Currently executing
- `paused` - Awaiting approval or external action
- `succeeded` - Completed successfully
- `failed` - Completed with failure
- `cancelled` - Manually cancelled

#### WorkflowStepExecutionDb

Tracks individual step executions:

| Column | Type | Description |
|--------|------|-------------|
| `id` | String (UUID) | Step execution ID |
| `execution_id` | String (FK) | Parent execution ID |
| `step_id` | String (FK) | Step definition ID |
| `status` | String | Step status |
| `passed` | Boolean | Pass/fail result |
| `result_data` | JSON | Step output data |
| `error_message` | Text | Error details |
| `duration_ms` | Float | Execution time in ms |
| `started_at` | Timestamp | Start time |
| `finished_at` | Timestamp | Completion time |

**Step Statuses:**
- `pending` - Waiting to execute
- `running` - Currently executing
- `succeeded` - Completed successfully
- `failed` - Completed with error
- `skipped` - Skipped due to branching

### Querying Executions

#### By User

```python
# Get all executions triggered by a specific user
executions = db.query(WorkflowExecutionDb).filter(
    WorkflowExecutionDb.triggered_by == "alice@company.com"
).order_by(WorkflowExecutionDb.started_at.desc()).all()
```

#### By Entity

```python
import json

# Get executions for a specific entity
executions = db.query(WorkflowExecutionDb).filter(
    WorkflowExecutionDb.trigger_context.contains(
        json.dumps({"entity_id": "contract-123"})
    )
).all()
```

#### With Step Details

```python
execution = db.query(WorkflowExecutionDb).filter_by(id=execution_id).first()

for step_exec in execution.step_executions:
    print(f"""
    Step: {step_exec.step.name}
    Type: {step_exec.step.step_type}
    Status: {step_exec.status}
    Passed: {step_exec.passed}
    Duration: {step_exec.duration_ms}ms
    Result: {step_exec.result_data}
    """)
```

---

## Compliance DSL Integration

Process workflows integrate with the Compliance DSL for validation and conditional logic.

### Using DSL in Validation Steps

```yaml
step_type: validation
config:
  rule: |
    MATCH (obj:Object)
    WHERE obj.type == "table"
    ASSERT obj.name MATCHES "^[a-z][a-z0-9_]*$"
    ON_FAIL: FAIL("Table name must be lowercase with underscores")
```

### Using DSL in Conditional Steps

```yaml
step_type: conditional
config:
  condition: obj.tags.classification == "PII"
```

### Available DSL Functions

See [Compliance DSL Reference](compliance-dsl-reference.md) for complete documentation.

Common patterns:
- `obj.property` - Access entity properties
- `obj.property IS NOT NULL` - Check for existence
- `obj.name MATCHES "regex"` - Regex matching
- `obj.tags.key == "value"` - Tag checking
- `LEN(obj.columns) > 0` - Collection checks

---

## Visual Workflow Designer

### Overview

The workflow designer provides a visual interface for creating and editing workflows using ReactFlow.

**Location:** 
- Frontend: `src/frontend/src/components/workflows/workflow-designer.tsx`
- View: `src/frontend/src/views/workflow-designer.tsx`

### Node Types

Each step type has a corresponding visual node:

| Step Type | Node Component | Icon |
|-----------|----------------|------|
| Trigger | `TriggerNode` | Play |
| Policy Check | `PolicyCheckNode` | ClipboardCheck |
| Validation | `ValidationNode` | Shield |
| Approval | `ApprovalNode` | UserCheck |
| Notification | `NotificationNode` | Bell |
| Assign Tag | `AssignTagNode` | Tag |
| Conditional | `ConditionalNode` | GitBranch |
| Script | `ScriptNode` | Code |
| Pass | `EndNode` | CheckCircle |
| Fail | `EndNode` | XCircle |

### Designer Features

1. **Drag-and-Drop**: Add steps from the toolbar
2. **Edge Connections**: Connect steps with pass/fail branches
3. **Configuration Panel**: Edit step settings in the side sheet
4. **Auto-Layout**: Automatic DAG layout using Dagre
5. **Validation**: Real-time workflow validation

### Accessing the Designer

1. Navigate to **Compliance** (in the main sidebar)
2. Scroll to the **Process Workflows** section
3. Click **Create Workflow** or **Edit** on an existing workflow
4. URL: `/compliance/workflows/:workflowId`

---

## Default Workflows

### Loading Defaults

Default workflows are loaded from `src/backend/src/data/default_workflows.yaml` on application startup (`startup_event` in `src/backend/src/app.py`):

```python
# During app initialization
workflows_manager = WorkflowsManager(db_session)
workflows_manager.load_from_yaml(requests_only_active=True)
```

- Only workflows that don't exist yet (by name) are created; existing ones, including local edits and their active state, are left untouched.
- Request workflows (`on_request_*`) are created with the `is_active` value from the YAML. All others (event-driven workflows such as naming validation or publish notifications, and the `for_*` UI wizards) are created **inactive**, so an upgrade doesn't turn on new automatic behavior. Enable them on the Workflows page.
- **Load Defaults** (`POST /api/workflows/load-defaults`) creates missing workflows with the YAML's `is_active`; with `update_existing=true` it also resets existing default workflows to the YAML.

### Pre-Defined Workflows

#### 1. Naming Convention Validation

Validates naming standards for Unity Catalog assets.

- **Trigger:** On Create
- **Entity Types:** Catalog, Schema, Table
- **Steps:**
  1. Validate lowercase naming
  2. Validate no reserved words
  3. Auto-tag or notify on failure

#### 2. Data Contract Schema Validation

Ensures contracts have required elements.

- **Trigger:** On Create
- **Entity Types:** Contract
- **Steps:**
  1. Check schema definition exists
  2. Check owner is assigned
  3. Auto-assign owner or notify

#### 3. Data Product Publish Approval

Requires approval before publishing.

- **Trigger:** On Status Change (draft → published)
- **Entity Types:** Product
- **Steps:**
  1. Validate completeness
  2. Request domain owner approval
  3. Notify on approval/rejection

#### 4. PII Detection and Classification

Automatically detects and tags PII data.

- **Trigger:** On Create
- **Entity Types:** Table
- **Status:** Inactive by default (opt-in)
- **Steps:**
  1. Check for PII indicators
  2. Assign classification tag
  3. Notify security team

#### 5. Dataset Update Notification

Notifies subscribers of dataset changes.

- **Trigger:** On Update
- **Entity Types:** Dataset
- **Steps:**
  1. Check for active subscriptions
  2. Notify subscribers
  3. Complete

---

## API Reference

### Endpoints

**Base Path:** `/api/workflows`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List all workflows |
| GET | `/:id` | Get workflow by ID |
| POST | `/` | Create new workflow |
| PUT | `/:id` | Update workflow |
| DELETE | `/:id` | Delete workflow |
| POST | `/:id/duplicate` | Duplicate workflow |
| POST | `/:id/toggle-active` | Enable/disable workflow |
| POST | `/:id/execute` | Manually execute workflow |
| POST | `/validate` | Validate workflow definition |
| GET | `/step-types` | List available step types |
| POST | `/load-defaults` | Reload default workflows |
| GET | `/compliance-policies` | List active compliance policies for policy_check step selector |
| GET | `/policy-usage/:policy_id` | Get workflows that reference a specific policy |
| GET | `/:id/referenced-policies` | Get policies referenced by a workflow |
| GET | `/executions` | List all workflow executions |
| GET | `/executions/:id` | Get execution details with step results |

### Request/Response Examples

#### List Workflows

```http
GET /api/workflows?active_only=true
```

```json
{
  "items": [
    {
      "id": "wf-uuid-123",
      "name": "Naming Convention Validation",
      "description": "Validates naming standards",
      "trigger": {
        "type": "on_create",
        "entity_types": ["catalog", "schema", "table"]
      },
      "scope": {
        "type": "all",
        "ids": []
      },
      "steps": [...],
      "is_active": true,
      "is_default": true
    }
  ],
  "total": 5
}
```

#### Create Workflow

```http
POST /api/workflows
Content-Type: application/json
```

```json
{
  "name": "Custom Validation",
  "description": "My custom validation workflow",
  "trigger": {
    "type": "on_create",
    "entity_types": ["table"]
  },
  "scope": {
    "type": "project",
    "ids": ["project-123"]
  },
  "steps": [
    {
      "step_id": "validate-name",
      "name": "Validate Table Name",
      "step_type": "validation",
      "config": {
        "rule": "MATCH (obj:Object) ASSERT obj.name MATCHES '^tbl_'"
      },
      "on_pass": "success",
      "on_fail": "failure",
      "order": 0
    },
    {
      "step_id": "success",
      "name": "Validation Passed",
      "step_type": "pass",
      "config": {},
      "order": 1
    },
    {
      "step_id": "failure",
      "name": "Validation Failed",
      "step_type": "fail",
      "config": {"message": "Table name must start with tbl_"},
      "order": 2
    }
  ],
  "is_active": true
}
```

#### Execute Workflow Manually

```http
POST /api/workflows/wf-uuid-123/execute
Content-Type: application/json
```

```json
{
  "entity_type": "table",
  "entity_id": "catalog.schema.table_name",
  "entity_name": "table_name",
  "entity_data": {
    "name": "table_name",
    "catalog": "catalog",
    "schema": "schema",
    "columns": [...]
  }
}
```

---

## Examples

### Example 1: Simple Validation Workflow

A workflow that validates table naming conventions:

```yaml
name: Table Naming Validation
description: Ensures tables follow naming standards
trigger:
  type: on_create
  entity_types:
    - table
scope:
  type: all
steps:
  - step_id: validate-name
    name: Check Naming Convention
    step_type: validation
    config:
      rule: |
        MATCH (obj:Object)
        ASSERT obj.name MATCHES "^[a-z][a-z0-9_]*$"
    on_pass: success
    on_fail: notify-failure

  - step_id: notify-failure
    name: Notify Failure
    step_type: notification
    config:
      recipients: requester
      template: validation_failed
    on_pass: failure

  - step_id: success
    name: Validation Passed
    step_type: pass

  - step_id: failure
    name: Validation Failed
    step_type: fail
    config:
      message: Table name must be lowercase with underscores only
```

### Example 2: Approval Workflow

A workflow that requires approval before publishing:

```yaml
name: Product Publish Approval
description: Requires approval before publishing data products
trigger:
  type: on_status_change
  entity_types:
    - product
  from_status: draft
  to_status: pending_approval
scope:
  type: all
steps:
  - step_id: validate-completeness
    name: Check Product Completeness
    step_type: validation
    config:
      rule: |
        MATCH (obj:Object)
        ASSERT obj.description IS NOT NULL
        ASSERT obj.owner IS NOT NULL
        ASSERT LEN(obj.output_ports) > 0
    on_pass: request-approval
    on_fail: reject-incomplete

  - step_id: request-approval
    name: Request Domain Owner Approval
    step_type: approval
    config:
      approvers: domain_owners
      timeout_days: 7
    on_pass: approved
    on_fail: rejected

  - step_id: approved
    name: Product Approved
    step_type: notification
    config:
      recipients: requester
      template: product_approved
    on_pass: success

  - step_id: rejected
    name: Product Rejected
    step_type: notification
    config:
      recipients: requester
      template: product_rejected
    on_pass: failure

  - step_id: reject-incomplete
    name: Incomplete Product
    step_type: fail
    config:
      message: Product must have description, owner, and at least one output port

  - step_id: success
    name: Approval Complete
    step_type: pass

  - step_id: failure
    name: Approval Denied
    step_type: fail
```

### Example 3: Conditional Tagging Workflow

A workflow that automatically tags tables based on content:

```yaml
name: PII Auto-Tagging
description: Automatically tags tables containing PII columns
trigger:
  type: on_create
  entity_types:
    - table
scope:
  type: all
steps:
  - step_id: check-pii
    name: Check for PII Columns
    step_type: conditional
    config:
      condition: |
        ANY(col IN obj.columns WHERE 
          LOWER(col.name) CONTAINS "ssn" OR
          LOWER(col.name) CONTAINS "email" OR
          LOWER(col.name) CONTAINS "phone"
        )
    on_pass: tag-pii
    on_fail: no-pii

  - step_id: tag-pii
    name: Apply PII Tag
    step_type: assign_tag
    config:
      key: classification
      value: PII
    on_pass: notify-security

  - step_id: notify-security
    name: Notify Security Team
    step_type: notification
    config:
      recipients: security-team@company.com
      custom_message: "New table with PII detected: ${entity_name}"
    on_pass: done

  - step_id: no-pii
    name: No PII Detected
    step_type: pass

  - step_id: done
    name: Tagging Complete
    step_type: pass
```

### Example 4: Pre-Creation Validation with Policy Checks

A workflow that validates assets **before** they are created, using existing compliance policies:

```yaml
name: Pre-Creation Compliance Validation
description: Validates naming conventions and required tags before asset creation
trigger:
  type: before_create
  entity_types:
    - catalog
    - schema
    - table
scope:
  type: all
steps:
  - step_id: check-naming
    name: Check Naming Conventions
    step_type: policy_check
    config:
      policy_id: "550e8400-e29b-41d4-a716-446655440001"  # UUID of Naming Conventions policy
    on_pass: check-tags
    on_fail: failure

  - step_id: check-tags
    name: Check Required Tags
    step_type: policy_check
    config:
      policy_id: "550e8400-e29b-41d4-a716-446655440002"  # UUID of Required Tags policy
    on_pass: success
    on_fail: failure

  - step_id: success
    name: Validation Passed
    step_type: pass
    config:
      message: All compliance checks passed

  - step_id: failure
    name: Validation Failed
    step_type: fail
    config:
      message: Pre-creation compliance validation failed
```

> **Key Difference:** This workflow uses `before_create` instead of `on_create`. When the workflow fails, the entity creation is **blocked** and the user receives immediate feedback in the UI. The `policy_check` steps reference existing compliance policies by UUID, ensuring centralized policy management.

### Example 5: Firing Pre-Creation Triggers from Code

How to integrate pre-creation workflows in your backend routes:

```python
from src.common.workflow_triggers import get_trigger_registry
from src.models.process_workflows import EntityType
from fastapi import HTTPException

# Get registry with database session
registry = get_trigger_registry(db_session)

# Fire before_create trigger (synchronous, blocking)
all_passed, executions = registry.before_create(
    entity_type=EntityType.TABLE,
    entity_id=f"{catalog}.{schema}.{table_name}",
    entity_name=table_name,
    entity_data={
        "name": table_name,
        "catalog": catalog,
        "schema": schema,
        "tags": request.tags,
    },
    user_email=current_user.email,
)

# Block creation if validation failed
if not all_passed:
    # Collect detailed error messages
    errors = []
    for exe in executions:
        for step_exe in exe.step_executions:
            if not step_exe.passed:
                policy_name = step_exe.result_data.get('policy_name', 'Unknown')
                message = step_exe.result_data.get('message', 'Validation failed')
                errors.append(f"{policy_name}: {message}")
    
    raise HTTPException(
        status_code=400,
        detail={
            'message': 'Pre-creation validation failed',
            'errors': errors,
        }
    )

# Proceed with creation only if all workflows passed
create_table(...)

# Fire post-creation trigger (asynchronous, non-blocking)
registry.on_create(
    entity_type=EntityType.TABLE,
    entity_id=f"{catalog}.{schema}.{table_name}",
    entity_name=table_name,
    entity_data={...},
    user_email=current_user.email,
)
```

---

## Best Practices

### Workflow Design

1. **Keep workflows focused**: One workflow per concern (validation, approval, notification)
2. **Use meaningful step IDs**: `validate-name` not `step1`
3. **Provide clear failure messages**: Help users understand what went wrong
4. **Test with inactive status**: Create workflows as inactive, test, then activate

### Performance

1. **Minimize blocking steps**: Use approvals sparingly
2. **Keep DSL rules efficient**: Simple rules execute faster
3. **Consider scope restrictions**: Limit workflows to relevant projects/domains
4. **Use async execution**: For non-critical workflows, consider async execution

### Error Handling

1. **Always include terminal steps**: Every path should end in `pass` or `fail`
2. **Add notification steps**: Notify relevant parties of failures
3. **Log meaningful data**: Include relevant context in step results
4. **Handle edge cases**: Consider null values and missing properties

### Security

1. **Limit script steps**: Use built-in step types when possible
2. **Validate approvers**: Ensure approver specifications resolve to valid users
3. **Scope appropriately**: Don't apply sensitive workflows globally
4. **Audit executions**: Regularly review workflow execution history

---

## Troubleshooting

### Common Issues

#### Workflow Not Triggering

1. Check workflow is `is_active: true`
2. Verify trigger type matches the event
3. Confirm entity type is in the trigger's `entity_types`
4. Check scope restrictions

#### Step Failing Unexpectedly

1. Check step configuration in execution result_data
2. Review error_message in WorkflowStepExecutionDb
3. Verify DSL rule syntax
4. Check entity data has expected properties

#### Approval Workflow Stuck

1. Check execution status is `paused`
2. Verify current_step_id points to approval step
3. Check approval system received the request
4. Review timeout configuration

### Debugging

Enable debug logging:

```python
# In src/common/logging.py
logging.getLogger('src.controller.workflow_executor').setLevel(logging.DEBUG)
logging.getLogger('src.common.workflow_triggers').setLevel(logging.DEBUG)
```

View execution details via API:

```http
GET /api/workflows/executions/:execution_id
```

---

## Future Roadmap (Deferred Items)

The following capabilities are explicitly deferred from the current implementation and tracked for future iterations:

### Timeout Expiry
Approval steps accept a `timeout_days` configuration but the system does not currently auto-expire approvals. A scheduled job should periodically scan for paused workflow executions where the approval step has exceeded `timeout_days` and automatically fail or escalate them.

### Crash Recovery
If the server restarts while a workflow is executing (status `running` or `paused`), those executions are currently orphaned. A startup recovery task should detect in-progress executions and either resume them from the last completed step or mark them as failed with a clear error message.

### Escalation
Overdue approval steps should support automatic escalation to a higher role (e.g., if a `DataSteward` hasn't responded in 3 days, escalate to `Admin`). This requires an `escalation_role` field on the approval step config and a scheduled checker.

### Parallel Approval Gates
The current `require_all` flag on approval steps is conceptual but not fully implemented for concurrent multi-approver scenarios. Supporting `n-of-m` approval quorums (e.g., 2 of 3 approvers must agree) would enable richer governance patterns.

### Audit Trail
Workflow executions are logged but not easily queryable. A dedicated `workflow_audit_log` table with structured fields (execution_id, step_id, action, actor, timestamp, outcome) would enable compliance reporting and execution history search.

### Test Coverage
The workflow executor currently lacks comprehensive unit tests for:
- Failure scenarios (step handler errors, partial execution)
- Timeout handling and thread safety
- Recovery from interrupted executions
- Concurrent workflow execution for the same entity
- Edge cases in template substitution and variable resolution

---

## Related Documentation

- [Compliance DSL Guide](compliance-dsl-guide.md)
- [Compliance DSL Reference](compliance-dsl-reference.md)
- [User Guide](USER-GUIDE.md)
- [README](README.md)

