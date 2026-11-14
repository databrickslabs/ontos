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

### Semantic Link Functions
- `HAS_CONCEPT(iri_or_label)` - True when a concept linked to the entity has this IRI or this label (exact match)

```
ASSERT HAS_CONCEPT('https://example.com/ontology#Customer')
ASSERT HAS_CONCEPT('Customer')
ASSERT NOT HAS_CONCEPT('Deprecated term')
```

The concepts are the entity's semantic links, as stored on it (direct links only: sub-concepts
are not inferred). They are read for data products, data contracts and domains; for other entity
types, and for reviews, `HAS_CONCEPT` is false. The same links are available as fields, see
[Application Entities](#application-entities).

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
```

- **Recipients** resolve as in workflow notification steps:
  - user emails, and groups as `group:<name>`;
  - app role names or ids;
  - `entity_owner` (or `owner`), `domain_owners`, `business:<role id>`, resolved for each entity; on Unity Catalog objects `owner` is the object's UC owner;
    `domain_owners` (or `DomainOwner`) and `ContractApprover` and `AssetOwner` are the owners of the entity's domain / of the entity, the user who started the run included; unlike workflow approvals, nobody else is notified when there are none;
  - a comma-separated list of these.

  Keywords such as `owner`, `entity_owner` or `requester` match without case, spaces and underscores (`Owner`, `Entity Owner`). Any other name that is not an app role fails the action (*not a known recipient*); it doesn't become a recipient that no user matches.

  `requester` / `trigger_user` is the user who started the run, so scheduled runs of the compliance-checks job have none. A recipient list that resolves to nobody for an entity fails the action for that entity.
- **One notification per recipient per run.** A run can match many entities, so NOTIFY doesn't send one notification each. When the run ends, each recipient gets one notification:
  - it gives the run's totals of failed and passed entities;
  - it names up to 10 of the entities its NOTIFY actions ran for (each once), and counts the rest. It only names entities the recipient can read: a user is told the names of the data products and contracts they could open (the same checks as the product page and the contract list), a role or group only those every reader sees (published ones), and the names of Unity Catalog objects go only to their owner. The others are only counted;
  - it links to the run's results.

  The notification is created even if the run is a scheduled job, and also for the entities evaluated before a run that stops with an error.
- **Done** on a NOTIFY action means the recipient was queued for the run's notification. If the notifications can't be created when the run ends, the run reports the warning *notifications could not be sent*.
- **Permission.** NOTIFY can reach any user, group or role, so saving, renaming (the name is the notifications' title) or running a policy that uses it needs **admin** access to compliance (Data Governance Officers and Admins by default). Scheduled runs use the rules as saved.
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

Data products, data contracts, domains and reviews are read from the app database. A data
product or data contract has the same fields in a compliance run and in a workflow rule (the
`obj` of a validation step or of a policy check), so `ASSERT obj.has_owner = True` means the same
in both. A workflow rule also sees the trigger payload: on `before_create`, `before_update` and
`on_delete` the rule sees the proposed change or the payload, not the stored entity.

**Data products** (`data_product`) and **data contracts** (`data_contract`):

- `type` - `data_product` or `data_contract`
- `entity_type` - `DataProduct` or `DataContract` (as workflow rules name them)
- `id`, `name`, `version`, `created_at`, `updated_at` - As stored
- `status` - Lifecycle status (draft, active, deprecated, retired...)
- `description` - Purpose text; null when there is none
- `has_description`, `has_purpose`, `has_usage` (products) - Booleans over the description
- `owner` - Id of the owning team. It is an id, not an email: use `owner_emails` for addresses
- `owner_team_id` - The same id as `owner`
- `owner_team_name` - Name of the owning team, or null
- `owner_emails` - Email addresses of the owning team's user members, sorted (groups are left out); an empty list when there is no owner
- `has_owner` - True when an owning team is set
- `domain` - Name of the primary domain, or null. Same as `domain_name`
- `domain_name` - Name of the primary domain, or null
- `domain_id` - Id of the primary domain, or null
- `tags`, `tag_count`, `has_tags` - Tags, see [Tag Functions](#tag-functions)
- `concepts`, `concept_iris`, `concept_labels`, `concept_count`, `has_concepts` - Semantic links, see [Semantic Link Functions](#semantic-link-functions)
- `quality_check_count`, `has_quality_checks` - Quality items of the entity
- `relationship_count` and the counts by relationship type: `dataset_count`, `business_term_count`, `upstream_system_count`, `upstream_product_count`, `delivery_channel_count`, `logical_attribute_mapping_count`; and the booleans `has_business_terms`, `has_upstream_lineage`, `has_delivery_channels`, `has_logical_attribute_mappings`
- `publication_scope`, `is_published` - Publication state
- `certification_level`, `inherited_certification_level`, `effective_certification`, `is_certified` - Certification
- `maturity_level_order`, `maturity_evaluated_at` - Maturity level as of its last evaluation (null before the first); the level order, not its name
- Data products only: `output_port_count`, `contract_count` (input contracts of the output ports), `output_port_contract_count`, `has_contract`
- Data contracts only: `schema_object_count`

**Domains** (`domain`):

- `type`, `id`, `name`, `description`, `created_at`, `updated_at`
- `owner` - Id of the owning team
- `tags` - Tag dictionary
- `concepts`, `concept_iris`, `concept_labels`, `concept_count`, `has_concepts`

**Reviews** (`review`):

- `type`, `id`, `status`, `created_at`, `updated_at`
- `reviewer` - Reviewer's email
- `requester` - Requester's email
- No concept fields: a review covers many assets, so it has no semantic links

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
