# Compliance DSL - Quick Guide

## Overview

The Compliance DSL enables you to write declarative rules for checking compliance across your Databricks Unity Catalog objects and application entities. Rules are evaluated automatically and can trigger actions like tagging, notifications, or custom error messages.

## Syntax

```
MATCH (entity:Type)
WHERE filter_condition
ASSERT compliance_condition
ON_PASS action
ON_FAIL action
```

### Key Components

- **MATCH**: Specifies which entity types to check (e.g., tables, data products)
- **WHERE**: Optional filter to narrow down entities before checking
- **ASSERT**: The actual compliance condition to verify
- **ON_PASS/ON_FAIL**: Actions to execute based on the result

## Supported Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `=` | Equality | `obj.status = 'active'` |
| `!=` | Not equal | `obj.owner != 'unknown'` |
| `>`, `<`, `>=`, `<=` | Comparison | `obj.score >= 95` |
| `MATCHES` | Regex match | `obj.name MATCHES '^[a-z_]+$'` |
| `IN` | List membership | `obj.type IN ['table', 'view']` |
| `CONTAINS` | Substring check | `obj.description CONTAINS 'PII'` |
| `AND`, `OR`, `NOT` | Boolean logic | `obj.active AND NOT obj.deprecated` |

## Built-in Functions

| Function | Description | Example |
|----------|-------------|---------|
| `HAS_TAG(key)` | Check if tag exists | `HAS_TAG('data-product')` |
| `TAG(key)` | Get tag value | `TAG('domain') = 'finance'` |
| `LENGTH(str)` | String length | `LENGTH(obj.name) <= 64` |
| `UPPER(str)` | Convert to uppercase | `UPPER(obj.name)` |
| `LOWER(str)` | Convert to lowercase | `LOWER(obj.name) = obj.name` |

On data products, data contracts and domains, a tag key is the tag's
`namespace/name` or its name; the name alone only works while no other namespace
has a tag of that name on the entity (see the
[DSL reference](compliance-dsl-reference.md#tag-functions)).

## Available Actions

| Action | Syntax | Description |
|--------|--------|-------------|
| `PASS` | `PASS` | Mark as successful (default) |
| `FAIL` | `FAIL 'message'` | Mark as failed with custom message |
| `ASSIGN_TAG` | `ASSIGN_TAG key: 'value'` | Add or update a tag on the entity |
| `REMOVE_TAG` | `REMOVE_TAG key` | Remove a tag from the entity |
| `NOTIFY` | `NOTIFY 'email@example.com'` | Send notification to recipients |

## Practical Examples

### Example 1: Naming Convention Enforcement

**Scenario**: Ensure all tables and views follow lowercase snake_case naming, while views must start with `v_`.

```
MATCH (obj:Object)
WHERE obj.type IN ['table', 'view']
ASSERT
  CASE obj.type
    WHEN 'view' THEN obj.name MATCHES '^v_[a-z][a-z0-9_]*$'
    WHEN 'table' THEN obj.name MATCHES '^[a-z][a-z0-9_]*$'
  END
ON_FAIL FAIL 'Names must be lowercase_snake_case. Views must start with "v_"'
ON_FAIL ASSIGN_TAG compliance_issue: 'naming_violation'
```

**Examples**:
- ✅ `customer_orders` (table)
- ✅ `v_active_customers` (view)
- ❌ `CustomerOrders` (table - uppercase)
- ❌ `orders_view` (view - missing `v_` prefix)

---

### Example 2: PII Data Protection

**Scenario**: All tables containing PII must be encrypted with AES256 and notify security team if violations are found.

```
MATCH (tbl:table)
WHERE HAS_TAG('contains_pii') AND TAG('contains_pii') = 'true'
ASSERT TAG('encryption') = 'AES256'
ON_FAIL FAIL 'PII data must be encrypted with AES256'
ON_FAIL ASSIGN_TAG security_risk: 'high'
ON_FAIL NOTIFY 'security-team@company.com'
ON_PASS ASSIGN_TAG last_compliance_check: '2025-01-15'
```

**What it checks**:
- If a table is tagged with `contains_pii: true`
- Then it must have `encryption: AES256` tag
- On failure: assigns risk tag and alerts security team
- On success: updates last check timestamp

---

### Example 3: Data Product Ownership

**Scenario**: All active data products must have a valid owner assigned.

```
MATCH (prod:data_product)
WHERE prod.status IN ['active', 'published']
ASSERT prod.owner != 'unknown' AND LENGTH(prod.owner) > 0
ON_FAIL FAIL 'Active data products must have a valid owner assigned'
ON_FAIL ASSIGN_TAG needs_attention: 'missing_owner'
ON_FAIL NOTIFY 'data-governance@company.com'
ON_PASS REMOVE_TAG needs_attention
```

**What it checks**:
- Only active or published data products
- Owner field must not be 'unknown' or empty
- Failures are tagged and governance team is notified
- Successful checks remove the attention tag

---

### Example 4: Data Contract Quality Standards

**Scenario**: All active data contracts must maintain a quality score above 95%.

```
MATCH (contract:data_contract)
WHERE contract.status = 'active'
ASSERT
  HAS_TAG('quality_score') AND
  TAG('quality_score') >= '95'
ON_FAIL FAIL 'Data quality score must be at least 95% for active contracts'
ON_FAIL ASSIGN_TAG quality_status: 'below_threshold'
ON_FAIL NOTIFY 'data-quality-team@company.com'
ON_PASS ASSIGN_TAG quality_status: 'meets_standard'
```

**What it checks**:
- Active contracts only
- Must have a quality_score tag
- Score must be 95 or higher
- Tags updated to reflect current quality status

---

### Example 5: Table and View Tagging Requirements

**Scenario**: All production tables and views must be tagged with a data product or explicitly marked as excluded.

```
MATCH (obj:Object)
WHERE obj.type IN ['table', 'view'] AND obj.catalog = 'production'
ASSERT HAS_TAG('data-product') OR HAS_TAG('excluded-from-products')
ON_FAIL FAIL 'All production tables/views must be tagged with a data product or marked as excluded'
ON_FAIL ASSIGN_TAG compliance_status: 'untagged'
ON_FAIL ASSIGN_TAG last_violation_date: '2025-01-15'
ON_PASS REMOVE_TAG compliance_status
```

**What it checks**:
- Only objects in the 'production' catalog
- Must have either `data-product` tag OR `excluded-from-products` tag
- Multiple tags applied on failure for tracking
- Clears compliance status tag when passing

---

### Example 6: Schema Documentation Requirements

**Scenario**: All schemas must have a meaningful comment/description of at least 20 characters.

```
MATCH (sch:schema)
WHERE sch.catalog != 'temp'
ASSERT
  sch.comment != '' AND
  LENGTH(sch.comment) >= 20
ON_FAIL FAIL 'Schemas must have a description of at least 20 characters'
ON_FAIL ASSIGN_TAG documentation_status: 'incomplete'
ON_FAIL NOTIFY 'data-documentation-team@company.com'
ON_PASS ASSIGN_TAG documentation_status: 'complete'
```

**What it checks**:
- All schemas except in 'temp' catalog
- Comment field must exist and be at least 20 characters
- Documentation team is notified of violations
- Tags reflect current documentation status

---

## Entity Types

You can write rules for these entity types:

### Unity Catalog Objects
- `catalog` - Unity Catalog catalogs
- `schema` - Database schemas
- `table` - Data tables
- `view` - Database views
- `function` - SQL/Python functions
- `volume` - Volumes for file storage

### Application Entities
- `data_product` - Data products
- `data_contract` - Data contracts
- `domain` - Business domains
- `glossary_term` - Business glossary terms
- `review` - Asset review requests

### Generic
- `Object` - Matches all entity types

## Common Properties

Different entities expose different properties. Here are the most common:

| Property | Description | Example |
|----------|-------------|---------|
| `type` | Entity type | `obj.type = 'table'` |
| `name` | Entity name | `obj.name MATCHES '^v_'` |
| `owner` | Owner email | `obj.owner != 'unknown'` |
| `status` | Status field | `obj.status = 'active'` |
| `catalog` | Parent catalog | `obj.catalog = 'prod'` |
| `schema` | Parent schema | `obj.schema = 'finance'` |
| `comment` | Description | `LENGTH(obj.comment) > 10` |
| `tags` | Tag dictionary | `HAS_TAG('domain')` |
| `created_at` | Creation time | Available for filtering |
| `updated_at` | Update time | Available for filtering |

## Tips and Best Practices

1. **Start Simple**: Test rules on a small subset using the `limit` parameter before running on all entities

2. **Use WHERE Efficiently**: Filter entities in the WHERE clause to improve performance:
   ```
   WHERE obj.catalog = 'production'  # Better than checking in ASSERT
   ```

3. **Provide Clear Messages**: Users need actionable feedback:
   ```
   ON_FAIL FAIL 'Tables must follow naming convention: lowercase_with_underscores'
   ```

4. **Tag for Tracking**: Use tags to track compliance over time:
   ```
   ON_FAIL ASSIGN_TAG last_failed: '2025-01-15'
   ON_PASS REMOVE_TAG last_failed
   ```

5. **Notify Appropriately**: Don't spam - notify only on critical violations:
   ```
   WHERE obj.catalog = 'production' AND HAS_TAG('critical')
   ON_FAIL NOTIFY 'urgent-alerts@company.com'
   ```

6. **Test Regex Patterns**: Verify your regex patterns work as expected:
   ```python
   import re
   pattern = r'^[a-z][a-z0-9_]*$'
   re.match(pattern, 'valid_name')  # Test first!
   ```

## Running Rules

Rules are executed via the ComplianceManager:

```python
from src.controller.compliance_manager import ComplianceManager

# Create or load a policy with your DSL rule
policy = compliance_manager.get_policy(db, policy_id)

# Run the policy (optionally with a limit for testing)
run = compliance_manager.run_policy_inline(db, policy=policy, limit=100)

# Check results
print(f"Success: {run.success_count}, Failures: {run.failure_count}")
print(f"Compliance Score: {run.score}%")
```

## Error Messages

The DSL provides helpful error messages when rules are malformed:

```
Lexer error at line 2, column 15: Unterminated string
Parser error at line 3, column 8: Expected ')', got 'AND'
Evaluation error: Unknown function: INVALID_FUNC
DSL evaluation error: IN operator requires list on right side
```

## Need Help?

- Check the [Compliance DSL Reference](/user-docs/compliance-dsl-reference) for complete syntax documentation
- Review existing policies in: `src/backend/src/data/compliance.yaml`
- Run tests: `pytest src/backend/tests/test_compliance_dsl.py -v`
- Access documentation via Settings → Documentation in the application
