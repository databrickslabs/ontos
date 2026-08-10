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

> Note: `True` unquoted is a boolean literal, whereas `'true'` (quoted) is the
> string `"true"`. Compare boolean properties against unquoted `True`/`False`.

## Functions

### Tag Functions
- `HAS_TAG(key)` - Check if entity has a tag
- `TAG(key)` - Get tag value

```
ASSERT HAS_TAG('data-product')
ASSERT TAG('domain') = 'finance'
```

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
ON_PASS ASSIGN_TAG last_checked: '2025-01-15'
```

### REMOVE_TAG
Remove a tag from the entity:

```
ON_PASS REMOVE_TAG compliance_issue
```

### NOTIFY
Trigger notification to recipients:

```
ON_FAIL NOTIFY 'security-team@example.com'
ON_FAIL NOTIFY 'compliance-alerts@example.com,data-governance@example.com'
```

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
- `table_type` - TABLE or VIEW

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
