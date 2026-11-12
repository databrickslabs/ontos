# Compliance DSL Reference

## Overview

The Compliance DSL (Domain-Specific Language) provides a powerful, flexible way to define compliance rules that can be evaluated against various entities in your Databricks environment and application.

## Syntax

### Basic Structure

```
MATCH (entity:Type)
WHERE entity.property OP value [AND/OR ...]
ASSERT condition
ON_PASS action [action ...]
ON_FAIL action [action ...]
```

### Components

#### MATCH Clause
Specifies the entity type to evaluate:

```
MATCH (obj:Object)        # All entity types
MATCH (tbl:table)         # Only tables
MATCH (prod:data_product) # Only data products
```

**Supported Entity Types:**
- Unity Catalog: `catalog`, `schema`, `table`, `view`, `function`, `volume`
- Application: `data_product`, `data_contract`, `domain`, `glossary_term`, `review`
- Generic: `Object` (matches all types)

#### WHERE Clause (Optional)
Filters entities before evaluation:

```
WHERE obj.type IN ['table', 'view']
WHERE obj.owner != 'unknown' AND obj.status = 'active'
```

#### ASSERT Clause
Defines the compliance condition:

```
ASSERT obj.name MATCHES '^[a-z][a-z0-9_]*$'
ASSERT obj.encryption = 'AES256'
ASSERT HAS_TAG('data-product')
```

#### Action Clauses (Optional)
Define what happens on success or failure:

```
ON_PASS PASS
ON_FAIL FAIL 'Name must be lowercase with underscores'
ON_FAIL ASSIGN_TAG compliance_issue: 'naming_violation'
ON_FAIL NOTIFY 'compliance-team@example.com'
```

## Operators

### Comparison Operators
- `=` - Equality
- `!=` - Inequality
- `>` - Greater than
- `<` - Less than
- `>=` - Greater than or equal
- `<=` - Less than or equal
- `MATCHES` - Regular expression match
- `IN` - List membership
- `CONTAINS` - Substring/element containment

### Boolean Operators
- `AND` - Logical AND
- `OR` - Logical OR
- `NOT` - Logical NOT

### Examples

```
# Equality
obj.status = 'active'

# Regex match
obj.name MATCHES '^[a-z][a-z0-9_]*$'

# List membership
obj.type IN ['table', 'view']

# Boolean combination
obj.owner != 'unknown' AND obj.status = 'active'

# Negation
NOT obj.deprecated
```

## Literal Values

Values on the right-hand side of a comparison may be:

- **Strings** — single or double quoted, e.g. `'active'`, `"AES256"`
- **Numbers** — integers or floats, e.g. `42`, `95.5`
- **Booleans** — `True` / `False` (case-insensitive, so `true`/`false` also work)
- **Lists** — e.g. `['table', 'view']` (used with `IN`)

Booleans are real boolean values, so a rule can compare directly against a
boolean entity property:

```
# has_owner is a boolean property on the entity
ASSERT obj.has_owner = True
ASSERT obj.has_pii != True
```

> Note: bare `True`/`False` are boolean literals, whereas `'true'`/`'false'`
> are strings. Compare string properties and `TAG()` values against quoted
> values. Numeric fields such as `1` and `0` are not equal to booleans.

## Functions

### Tag Functions
- `HAS_TAG(key)` - Check if entity has a tag
- `TAG(key)` - Get tag value

```
ASSERT HAS_TAG('data-product')
ASSERT TAG('domain') = 'finance'
```

For data products, data contracts and domains, `key` is the assigned tag's
fully qualified name (`namespace/name`) or its name. The name alone works only
while the entity has no tag of the same name in another namespace; when names
repeat across namespaces, use the fully qualified name
(`TAG('privacy/classification')`). A tag assigned without a value has the value
`True`. If the tags can't be loaded, the run fails instead of treating the
entities as untagged.

### String Functions
- `UPPER(str)` - Convert to uppercase
- `LOWER(str)` - Convert to lowercase
- `LENGTH(str)` - Get string length

```
ASSERT LENGTH(obj.name) <= 64
ASSERT LOWER(obj.name) = obj.name  # Enforce lowercase
```

## CASE Expressions

Conditional logic for complex rules:

```
ASSERT
  CASE obj.type
    WHEN 'catalog' THEN obj.name MATCHES '^[a-z][a-z0-9_]*$'
    WHEN 'schema' THEN obj.name MATCHES '^[a-z][a-z0-9_]*$'
    WHEN 'table' THEN obj.name MATCHES '^[a-z][a-z0-9_]*$'
    WHEN 'view' THEN obj.name MATCHES '^v_[a-z][a-z0-9_]*$'
    ELSE true
  END
```

## Actions

### PASS
Mark check as successful (default):

```
ON_PASS PASS
```

### FAIL
Mark check as failed with custom message:

```
ON_FAIL FAIL 'Name must start with lowercase letter'
```

### ASSIGN_TAG
Add or update a tag on the entity:

```
ON_FAIL ASSIGN_TAG compliance_status: 'violation'
ON_FAIL ASSIGN_TAG 'governance/classification': 'confidential'
ON_FAIL ASSIGN_TAG 'pii'
ON_PASS ASSIGN_TAG 'governance/classification': ''
```

- **Key.** A bare name (`compliance_status`) is a tag in the default namespace. Quote the key to name a tag in another namespace by its fully qualified name, `'namespace/name'`. The tag must already exist.
- **Value.**
  - `key: 'value'` sets the value. If the tag defines possible values, the value must be one of them; otherwise the action fails with *value not allowed*.
  - `key` without a value assigns the tag only. When the entity already has the tag, its value (and who assigned it) is kept.
  - `key: ''` clears the value.
- **Entities.** Tag actions work on data products, data contracts and domains. On other entities (Unity Catalog objects) the action fails and the run carries on.

### REMOVE_TAG
Remove a tag from the entity:

```
ON_PASS REMOVE_TAG compliance_issue
ON_PASS REMOVE_TAG 'governance/classification'
```

The key is written as for `ASSIGN_TAG`. Removing a tag the entity doesn't have succeeds and changes nothing.

### NOTIFY
Send an in-app notification:

```
ON_FAIL NOTIFY 'security-team@example.com'
ON_FAIL NOTIFY 'compliance-alerts@example.com,data-governance@example.com'
ON_FAIL NOTIFY 'entity_owner'
ON_FAIL NOTIFY 'self'
ON_FAIL NOTIFY recipient:'Data Stewards'
```

- **Recipients** resolve as in workflow notification steps:
  - user emails and group names;
  - app role names or ids;
  - `entity_owner` (or `owner`), `domain_owners`, `business:<role id>`, resolved for each entity;
  - `self`: the policy's author (see below), not the user who runs it;
  - `recipient:'<name>'`: a Notification Recipient defined in Settings (see below);
  - a comma-separated list of these.

  `requester` / `trigger_user` is the user who started the run, so scheduled runs of the compliance-checks job have none. A recipient list that resolves to nobody for an entity fails the action for that entity.
- **Who may notify whom.** The policy's author decides. An admin (compliance Admin, or a role flagged as admin) may notify any target. Anyone else may notify:
  - `self`, which is the author, by their own email too;
  - `entity_owner` / `owner`;
  - a Notification Recipient whose allowed roles include one of the author's roles.

  Any other target is refused. A save with such a target fails with a message per target (code `notify_target_not_allowed`, or `notify_recipient_not_allowed` / `notify_recipient_not_found` for a recipient). The check runs again at each run, against the author and the author's groups as they were when they last changed the rule. A scheduled run has no user, so it uses the author too. A target that is refused at run time fails its NOTIFY action with a reason (the other actions still run). The rule is kept, so an admin can fix the target or the recipient's allowed roles. Only the entity's owners are allowed by default for non-admins; `domain_owners` and `business:` targets need an admin or a recipient.
- **Notification Recipients.** Admins define them in **Settings > Notification Recipients**: a name, the users, groups and app roles to notify, the app roles allowed to use the recipient, and an active flag. Rules refer to a recipient by name, as `recipient:'Name'` (or `recipient:Name` when the name has no spaces). The name must be unique (case-insensitive), and must not contain commas or quotes. A disabled recipient fails the NOTIFY actions that name it, with a reason; a recipient deleted after a rule named it does the same.
- **Authors.** A policy records who last changed its rule, and that user's groups. Only a change of the rule changes the author. A policy saved before authors were recorded has none, so only the entity's owners are allowed for it until an admin saves it again.
- **One notification per recipient per run.** A run can match many entities, so NOTIFY doesn't send one notification each. When the run ends, each recipient gets one notification:
  - it gives the run's totals of failed and passed entities;
  - it names up to 10 of the entities its NOTIFY actions ran for (each once), and counts the rest;
  - it links to the run's results.

  The notification is created even if the run is a scheduled job, and also for the entities evaluated before a run that stops with an error.
- **Done** on a NOTIFY action means the recipient was queued for the run's notification. If the notifications can't be created when the run ends, the run reports the warning *notifications could not be sent*.
- Notifications use the in-app channel.

### Action outcomes in run results

The run details page shows, for each entity, what its tag and notification actions did. A failed action shows its reason in the user's language (for example *tag not found*, *value not allowed*, *no recipient*). A failed action doesn't change whether the entity passed. `PASS` and `FAIL` aren't listed there, because they decide the result itself.

## Complete Examples

### 1. Naming Convention Rule

```
MATCH (obj:Object)
WHERE obj.type IN ['catalog', 'schema', 'table', 'view']
ASSERT
  CASE obj.type
    WHEN 'view' THEN obj.name MATCHES '^v_[a-z][a-z0-9_]*$'
    ELSE obj.name MATCHES '^[a-z][a-z0-9_]*$'
  END
ON_FAIL FAIL 'Objects must follow naming conventions'
ON_FAIL ASSIGN_TAG compliance_issue: 'naming_violation'
```

### 2. PII Encryption Rule

```
MATCH (tbl:table)
WHERE HAS_TAG('contains_pii') AND TAG('contains_pii') = 'true'
ASSERT HAS_TAG('encryption') AND TAG('encryption') = 'AES256'
ON_FAIL FAIL 'PII data must be encrypted with AES256'
ON_FAIL NOTIFY 'security-team@example.com'
ON_FAIL ASSIGN_TAG security_risk: 'high'
```

### 3. Data Product Ownership Rule

```
MATCH (prod:data_product)
WHERE prod.status IN ['active', 'published']
ASSERT prod.owner != 'unknown' AND LENGTH(prod.owner) > 0
ON_FAIL FAIL 'Active data products must have a valid owner'
ON_FAIL ASSIGN_TAG needs_attention: 'missing_owner'
ON_PASS REMOVE_TAG needs_attention
```

### 4. Tag Requirement Rule

```
MATCH (obj:Object)
WHERE obj.type IN ['table', 'view']
ASSERT HAS_TAG('data-product') OR HAS_TAG('excluded')
ON_FAIL FAIL 'All tables and views must be tagged with a data product'
ON_FAIL ASSIGN_TAG compliance_status: 'untagged'
```

### 5. Data Quality Threshold Rule

```
MATCH (contract:data_contract)
WHERE contract.status = 'active'
ASSERT
  HAS_TAG('quality_score') AND
  TAG('quality_score') >= '95'
ON_FAIL FAIL 'Data quality score must be at least 95%'
ON_FAIL NOTIFY 'data-quality-team@example.com'
```

### 6. Multi-Action Failure Handling

```
MATCH (obj:table)
ASSERT obj.owner != 'unknown'
ON_FAIL FAIL 'Table must have a valid owner'
ON_FAIL ASSIGN_TAG compliance_issue: 'missing_owner'
ON_FAIL ASSIGN_TAG last_failed: '2025-01-15'
ON_FAIL NOTIFY 'data-governance@example.com'
```

## Property Access

Entities have different properties based on their type:

### Unity Catalog Entities
- `type` - Entity type (catalog, schema, table, view, etc.)
- `name` - Entity name
- `id` - Entity ID
- `full_name` - Full qualified name
- `catalog` - Parent catalog (for schemas, tables)
- `schema` - Parent schema (for tables, views)
- `owner` - Owner email
- `comment` - Description
- `created_at` - Creation timestamp
- `updated_at` - Last update timestamp
- `storage_location` - Storage path (for tables, volumes)
- `table_type` - Unity Catalog table type as a string, such as `MANAGED`, `EXTERNAL`, `VIEW`,
  `MATERIALIZED_VIEW` or `METRIC_VIEW`. Views, materialized views and metric views are `view`
  entities; every other type is a `table` entity

#### Table and View Columns
Tables and views also carry fields computed from their columns, as returned by Unity Catalog
when Ontos lists the tables (no extra call per table):

- `columns` - List of `{name, type, comment, is_partition_key}`
- `column_count` - Number of columns
- `columns_without_comment_count` - Columns with no comment; a comment of only spaces counts
  as missing
- `column_comment_ratio` - Share of commented columns, from `0` to `1`; null when the table has
  no columns, so a threshold such as `>= 0.8` fails. Guard with `t.column_count = 0 OR ...` to
  let column-less objects pass
- `partition_column_count` - Number of partition columns
- `partition_columns_without_comment_count` - Partition columns with no comment

```
MATCH (t:table) ASSERT t.columns_without_comment_count = 0
MATCH (t:table) ASSERT t.column_comment_ratio >= 0.8
MATCH (t:table) ASSERT t.partition_columns_without_comment_count = 0
MATCH (v:view) ASSERT v.columns_without_comment_count = 0
```

Column tags, table tags, keys and lineage are not available yet.

### Application Entities
- `type` - Entity type
- `id` - Entity ID
- `name` - Entity name
- `description` - Description
- `status` - Status (draft, active, etc.)
- `version` - Version number
- `owner` - Owner email
- `domain` - Domain assignment
- `tags` - Tag dictionary
- `created_at` - Creation timestamp
- `updated_at` - Last update timestamp

## Best Practices

1. **Use WHERE to Filter**: Narrow down entities before ASSERT evaluation for performance
2. **Specific Error Messages**: Provide clear, actionable error messages in FAIL actions
3. **Combine Actions**: Use multiple actions for comprehensive failure handling
4. **Tag for Tracking**: Use tags to track compliance status over time
5. **Notify Appropriately**: Only notify on critical failures to avoid alert fatigue
6. **Test Incrementally**: Test rules on small subsets before running on all entities

## Error Handling

The DSL parser provides detailed error messages with line and column information:

```
Lexer error at line 2, column 15: Unterminated string
Parser error at line 3, column 8: Expected ')', got 'AND'
Evaluation error: Unknown function: INVALID_FUNC
```

## Extending the DSL

### Custom Actions

Register custom actions in Python:

```python
from src.common.compliance_actions import Action, ActionResult, register_action

class CustomAction(Action):
    def execute(self, context):
        # Your custom logic here
        return ActionResult(
            success=True,
            action_type='CUSTOM',
            message='Custom action executed'
        )

register_action('CUSTOM', CustomAction)
```

### Custom Functions

Extend the evaluator to support custom functions by modifying `evaluate_function` in `compliance_dsl.py`.

## Performance Considerations

- **Batch Processing**: Entity loading is batched for efficiency
- **Lazy Evaluation**: Entities are loaded on-demand as iterators
- **WHERE Filtering**: Applied before ASSERT to reduce evaluations
- **Limits**: Use the `limit` parameter when testing rules

## Integration

The DSL is integrated into the ComplianceManager:

```python
from src.controller.compliance_manager import ComplianceManager

manager = ComplianceManager()
run = manager.run_policy_inline(db, policy=policy, limit=100)
```

Results are stored in the database with:
- Success/failure counts
- Overall compliance score
- Per-entity results with messages
- Action execution audit trail
