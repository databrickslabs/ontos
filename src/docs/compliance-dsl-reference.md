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

Type names ignore case and underscores: `DataProduct`, `dataProduct` and
`data_product` all match data products. `data_asset_review`, the name workflows
give reviews, matches reviews. Compliance runs and workflow `policy_check` steps
resolve types the same way. A run whose rule matches no entity (unknown type, or
a `WHERE` that selects nothing) succeeds with the warning "no entities matched"
instead of results, and is left out of the overall compliance and the critical
issue count.

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

For Unity Catalog tables and views, `key` is the governed tag's key as Unity
Catalog stores it, with no namespace: `HAS_TAG('governance/pii')` doesn't match a
UC tag `pii`, so a rule that covers both app entities and tables names the tag
the way each one stores it. A tag without a value has the value `True`. See [Table and View Tags and
Lineage](#table-and-view-tags-and-lineage) for where the tags come from.

`TAG(key)` is `null` on an entity without that tag, and `null != ''` is true: `ASSERT
TAG('data_classification') != ''` passes every untagged entity, and an entity with the tag
but no value (`True`) as well. To require a tag, use `HAS_TAG('data_classification')`; to
require one of some values, use `TAG('data_classification') IN ['public', 'internal']`, which
is false without the tag.

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

### LLM Check
- `LLM_CHECK(text, 'criterion')` - Ask the configured serving endpoint (`LLM_ENDPOINT`)
  whether the text meets the criterion; true or false, with a short reason

```
MATCH (t:table)
ASSERT LLM_CHECK(t.comment, 'states the grain of the table')

MATCH (d:domain)
ASSERT LLM_CHECK(d.description, 'says who uses the data and for what')

MATCH (t:table)
ASSERT LENGTH(t.comment) >= 40 AND LLM_CHECK(t.comment, 'states the grain of the table')
```

Put a deterministic floor next to the check, as in the last example: the
model's verdict is a judgment, and a text written to steer it (prompt
injection) is only caught by the safety scan and the prompt, not by code. A
rule that also requires a minimum length fails short or empty texts without a
call, whatever the model answers, and saves calls.

**Deterministic floor.** `LLM_CHECK` itself checks, in code and before any call:

- non-empty: an empty or missing text fails without a call (`llm_check_empty_text`),
  also under `NOT`, so `NOT LLM_CHECK(...)` never passes an undocumented object;
- a minimum length of 20 characters (without the spaces around it): a shorter,
  placeholder text ("TBD", "table") fails without a call
  (`llm_check_text_too_short`), also under `NOT`, whatever a model would answer.

Both count as failures in the score (there is nothing to judge), not as not
evaluated, and, as for every check without a verdict, the entity's `ON_PASS` /
`ON_FAIL` actions don't run. A rule can raise the floor for its texts, as in the last example
(`LENGTH(t.comment) >= 40 AND LLM_CHECK(...)`).

The floor is what a rule still guarantees when the model is wrong or steered;
the model only judges what the floor lets through. There is no verdict schema
yet: the reply is one `PASS: <reason>` / `FAIL: <reason>` line.

The criterion must be a string literal: an expression such as `t.name` is
rejected when the rule is saved (`llm_check_criterion_not_literal`), because it
would put entity data into the model's instructions. The reason of a failed
check is the model's text: it is capped at 300 characters and shown as plain
text next to the result. Before saving, use **Test on a sample entity** in the
rule editor to try a criterion on one entity (at most 10 tests a minute per user,
counted per app process: with several replicas the limit is per replica; the
daily quota is shared).

- Access: saving, running or testing a rule with `LLM_CHECK` needs admin access
  to compliance (Data Governance Officers and Admins by default), as `NOTIFY`
  does (`llm_check_admin_required`). A run or test a user starts reads Unity
  Catalog with that user's own token, as every run a user starts does, so its
  results and reasons only cover the objects the user can read; the app entity
  types the rule matches (data products, contracts, domains, reviews) need read
  access to their feature (`llm_check_entity_read_required`). Scheduled runs use
  the app's identity.
- The serving endpoint is called with the app's identity, also for runs and
  tests a user starts: the user's token reads Unity Catalog, not the model. What
  bounds it is the admin gate above, the per-run budget and the user's daily quota.
- Actions: a rule with `LLM_CHECK` can't have `ASSIGN_TAG` or `REMOVE_TAG`; saving
  it is refused (`llm_check_tag_action`), the default policies YAML load skips such a
  policy (and leaves a stored one with that id as it is), and a run of such a rule
  stored some other way fails with the same code before it reads any entity, so no
  tag is written. The model's verdict picks
  `ON_PASS` / `ON_FAIL`, and an entity's owner can edit the text the model reads,
  so a steered verdict would change tags, which feed Unity Catalog tag sync and
  other gates. `NOTIFY` is allowed: a person reads it. Tag actions on model
  verdicts can be revisited once verdicts can go through Authority Resolution
  (#831) before anything is written.
- Data leaves the compliance store: the text under test (descriptions, column
  comments, owner text) goes to the serving endpoint, Foundation Model APIs or
  the model behind `LLM_ENDPOINT`, with no redaction of personal data or
  secrets. `LLM_CHECK` only calls the workspace's own serving endpoints
  (`<DATABRICKS_HOST>/serving-endpoints`): with an `LLM_BASE_URL` on another
  host it fails without a call (`llm_check_external_endpoint`).
- There is no switch for `LLM_CHECK` alone: turning on the LLM features
  (`LLM_ENABLED`, used by Ask Ontos) also turns it on, for the compliance admins
  who may save and run such rules.
- Two phases: the text is first scanned with the injection-check prompt
  (`LLM_INJECTION_CHECK_PROMPT`). A text the scan doesn't call `SAFE` fails with
  `llm_check_text_rejected`, and the criterion is never asked.

- Only evaluated in compliance runs, in `ASSERT`. In `WHERE`, in maturity gates,
  in workflow policy checks and validation steps, and in self-service creation (the
  compliance mapping's policies) the check fails (`llm_check_not_available`), so
  those are refused when saved: a rule with `LLM_CHECK` in `WHERE`
  (`llm_check_in_where`; it would skip every entity), a `policy_check` step on
  a policy with `LLM_CHECK` (`policy_check_policy_uses_llm_check`: an error that
  refuses the save of an active workflow; an inactive one saves with a warning
  and is refused when it is activated), a validation step whose rule uses
  `LLM_CHECK` (`validation_rule_uses_llm_check`, also when a stored workflow with
  one is activated), a maturity gate on such a policy
  (`maturity_gate_policy_uses_llm_check`), a compliance mapping that lists such a
  policy (422 `compliance_mapping_policy_uses_llm_check`), and an `LLM_CHECK` rule
  for a policy that steps of active workflows or maturity gates already use (409
  `llm_check_policy_in_use`; inactive workflows don't count, they can't be activated
  afterwards) or that the compliance mapping lists (409
  `llm_check_policy_in_self_service`). The default-policies YAML load skips such a
  policy when the mapping lists it.
- Fails closed: with an empty text (no call), LLM features off
  (`llm_check_disabled`), no endpoint (`llm_check_no_endpoint`), a refusal, an
  empty or unfinished reply, or a reply whose first line is not `PASS: <reason>`
  or `FAIL: <reason>`, the entity doesn't pass, also under `NOT`, and its
  `ON_PASS` / `ON_FAIL` actions don't run for it. Each call times out after 60 s.
  Such an entity is **not evaluated**: it counts neither as passed nor as
  failed, and the run's score covers only the judged entities (the run shows
  how many were not evaluated). An empty text is the exception: there is
  nothing to judge, so the entity fails.
- Cached: a verdict is stored per text, criterion, endpoint, the model the
  endpoint serves (read from its configuration once per run) and prompts, so a
  run over unchanged text makes no call, and repointing an endpoint at another
  model asks again. When the endpoint's configuration can't be read, verdicts
  are neither read from nor written to the cache (each check calls the model),
  so a verdict of another model is never reused. The model that answered is stored with the verdict. Calls
  are made at temperature 0 (endpoints that reject it are called without it). Verdicts older than
  `COMPLIANCE_LLM_CHECK_CACHE_MAX_AGE_DAYS` (default 30) are asked again, and
  deleted when a run starts. The cache is shared by every user and run: a
  verdict and its reason are keyed by the text, not by who asked, so a user can
  see a reason first written for another user's run over the same text (only
  for objects they can read, see the results filter).
- Budget: `COMPLIANCE_LLM_CHECK_MAX_CALLS_PER_RUN` model calls (default 100; a
  check makes two, the scan and the verdict; cached verdicts make none; a retry
  of a transient error, one at most per call, and a call made again without
  `temperature` count as calls too). It
  covers one policy run from the UI, and the whole run of the Compliance Checks
  job, shared by its policies. The checks past it fail with
  `llm_check_budget_exceeded`, and each policy run reports how many. Each run
  also shows its model calls and the verdicts it read from the cache
  (`llm_calls` and `llm_cache_hits` in the run's API answers).
- Daily quota: the runs and rule tests one user starts may make
  `COMPLIANCE_LLM_CHECK_MAX_CALLS_PER_USER_PER_DAY` model calls a day (UTC,
  default 400), retries included. The checks past it are not evaluated
  (`llm_check_daily_quota_exceeded`; the run warns how many), and a rule test
  that needed a call past it is answered 429 with `Retry-After` (seconds to
  midnight UTC). Cached verdicts don't count, so a run or test answered from the
  cache is never refused. A reservation not used is given back to the day it was
  made on. Scheduled runs have no user: only the per-run budget applies to them.
- Scheduled runs (the Compliance Checks job) read the LLM settings of the job's
  environment (`LLM_ENABLED`, `LLM_ENDPOINT`,
  `COMPLIANCE_LLM_CHECK_MAX_CALLS_PER_RUN`); without them, their `LLM_CHECK`s
  are not evaluated (`llm_check_disabled`).

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
  - user emails, and groups as `group:<name>`;
  - app role names or ids;
  - `entity_owner` (or `owner`), `domain_owners`, `business:<role id>`, resolved for each entity; on Unity Catalog objects `owner` is the object's UC owner;
    `domain_owners` (or `DomainOwner`) and `ContractApprover` and `AssetOwner` are the owners of the entity's domain / of the entity, the user who started the run included; unlike workflow approvals, nobody else is notified when there are none;
  - `self`: the policy's author (see below), not the user who runs it;
  - `recipient:'<name>'`: a Notification Recipient defined in Settings (see below);
  - a comma-separated list of these.

  Keywords such as `owner`, `entity_owner`, `self` or `requester` match without case, spaces and underscores (`Owner`, `Entity Owner`, `SELF`). Any other name that is not an email, a group or an app role fails the action (*not a known recipient*); it doesn't become a recipient that no user matches.

  `requester` / `trigger_user` is the user who started the run, so scheduled runs of the compliance-checks job have none. A recipient list that resolves to nobody for an entity fails the action for that entity.
- **Who may notify whom.** The policy's author decides. An admin (compliance ADMIN, the feature level the app resolves for the user; a role's `is_admin` flag doesn't count) may notify any target. Anyone else may notify:
  - `self`, which is the author, by their own email too;
  - `entity_owner` / `owner`;
  - a Notification Recipient whose allowed roles include one of the author's roles.

  Any other target is refused. A save with such a target fails with a message per target (code `notify_target_not_allowed`, or `notify_recipient_not_allowed` / `notify_recipient_not_found` for a recipient). The check runs again at each run, against the author and the author's groups as they were when they last changed the policy. A scheduled run has no user, so it uses the author too. A target that is refused at run time fails its NOTIFY action with a reason (the other actions still run). The rule is kept, so an admin can fix the target or the recipient's allowed roles. Only the entity's owners are allowed by default for non-admins; `domain_owners` and `business:` targets need an admin or a recipient.
- **Notification Recipients.** Admins define them in **Settings > Notification Recipients**: a name, the users, groups and app roles to notify (groups as `group:<name>`), the app roles allowed to use the recipient, and an active flag. Rules refer to a recipient by name, as `recipient:'Name'` (or `recipient:Name` when the name has no spaces). The name must be unique (case-insensitive), and must not contain commas or quotes.
- **Authors.** A policy records who last saved a change to it, and that user's groups. Saving any change to a policy with `NOTIFY` (its name included, since the name titles the notifications) checks its NOTIFY targets against the editor, who becomes the author; a refused target fails the save. A policy saved before authors were recorded has none, so only the entity's owners are allowed for it until an admin saves it again.
- **One notification per recipient per run.** A run can match many entities, so NOTIFY doesn't send one notification each. When the run ends, each recipient gets one notification:
  - it gives the run's totals of failed and passed entities;
  - it names up to 10 of the entities its NOTIFY actions ran for (each once), and counts the rest. It only names entities the recipient can read: a user is told the names of the data products and contracts they could open (the same checks as the product page and the contract list), a role or group only those every reader sees (published ones), and the names of Unity Catalog objects go only to their owner. The others are only counted;
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

Primary and foreign keys are not available yet.

#### Table and View Tags and Lineage
These fields come from system tables, read through the SQL warehouse the app is configured
with (`DATABRICKS_WAREHOUSE_ID`). They are loaded only for a rule that reads them, with one
statement per field group for each chunk of a catalog's tables (whole schemas, about 500
tables; never one per table), restricted to the catalogs and schemas selected by the
`AND`-ed parts of the rule's `WHERE` that don't read these fields. A chunk is read only when
the run gets to it, so a run that stops at its `limit` reads no more. The policies of one
compliance-checks job run share the statements: a later policy that needs the same tags or
lineage reuses them. A statement that failed with `timed_out`, `transient` or `query_failed`
is sent again by the next policy that needs it; one that failed with `no_access` or
`not_found` is not. Each policy run sends at most 100 statements (in a job run, each
policy has its own 100, and statements already read for an earlier policy don't count);
past that, the fields are not read (reason `budget_exceeded`). A policy run spends at most
15 minutes on these statements, from its start; past that, the statements still to send
and the one running are not waited for (reason `timed_out`):

- `tags` - The table's governed tags as `{key: value}`, read with `HAS_TAG` / `TAG`. Source:
  `system.information_schema.table_tags`. Column tags are not read
- `upstream_count` - Distinct tables this table was written from in the last 90 days, in
  `system.access.table_lineage`
- `downstream_count` - Distinct tables written from this table in the last 90 days

Lineage counts only events of the last 90 days and only table-to-table lineage (rows whose
source or target is a path, a notebook or a dashboard are not counted); a table with no event
in that window has `0`.

> **Stale tables read `0`.** A valid table that was last written more than 90 days ago (a
> yearly load, a frozen reference table) has `upstream_count = 0`, so `t.upstream_count > 0`
> fails it. Exclude such tables in the `WHERE` (by schema, or with a tag such as
> `NOT HAS_TAG('static')`), or check lineage only where pipelines run at least quarterly.

```
MATCH (t:table) ASSERT HAS_TAG('data_classification')
MATCH (t:table) ASSERT TAG('data_classification') IN ['public', 'internal', 'confidential']
MATCH (t:table) WHERE t.catalog = 'production' ASSERT t.upstream_count > 0
MATCH (v:view) ASSERT v.downstream_count > 0 OR HAS_TAG('deprecated')
```

A statement that is still running after 50 seconds keeps running and is polled; one still
running after 5 minutes, or at the run's 15 minutes, is cancelled (reason `timed_out`), as is
one whose polling fails, before it is retried.

Only tables and views have tags in rules. On catalogs, schemas, functions and volumes, `tags`
is not loaded: a rule that reads it (`MATCH (s:schema) ASSERT NOT HAS_TAG('x')`) reports
each of them as not evaluated (reason `not_loaded`) instead of passing it.

A transient error (the warehouse busy or starting, a rate limit, a network timeout) is
retried twice with backoff before the source is reported as unavailable (reason
`transient`); a missing system table or schema has the reason `not_found`.

If a source can't be read (no SQL warehouse configured, no access to the system table, the
statement fails or times out), its fields are left out and every entity whose rule reads them gets a
result marked *not evaluated* with the field, the source and the reason. It is neither passed
nor failed: it is not in the run's passed and failed counts, the score or the failed list,
and its `ON_PASS` / `ON_FAIL` actions don't run. When the `WHERE` reads a missing field, the
entity is kept only if the `AND`-ed parts of the `WHERE` that don't read it hold. The run ends
with the warning `rule_fields_unavailable` and the number of such entities. Fields from a
source that could be read are still evaluated.

A run that evaluated nothing (every entity not evaluated, or none matched), or that failed,
has no score: it stores null, the API returns `score: null` and the UI shows "No score". Each run also has
`coverage` (`evaluated`, `not_evaluated`), shown when some entities were not evaluated, so a
score measured on a few of many tables says so. The policy list, the stats and the trend use
the policy's latest run that has a score. A policy with no such run among its last 20 has no
score: it shows "No score", the overall compliance averages only the policies that have one
(no score at all when none has), and it doesn't count as a critical issue, which is a critical
policy scored below 70.

The results of a run list only the Unity Catalog objects the viewer can read: they are
checked with the viewer's own token when the results are opened (one listing per schema),
whoever started the run. The others are counted (`hidden_count`), not listed. A viewer
without a token sees none, except with `ENV=LOCAL` or `OBO_ALLOW_SP_FALLBACK=true`, where the
check uses the app's client and so hides nothing the app can read. The run's counts, score and
coverage, in the results and in the run list, are computed over the same visible results, so
they say nothing about the hidden objects; the results come in pages of up to 500 (`offset`,
`limit`), with `total` counting every visible result.

> **Policy scores and trends are org-wide; run results are per viewer.** The policy list
> (`compliance` of each policy), the stats (`overall_compliance`, critical issues) and the trend
> (`GET /api/compliance/trend`) use the score each run stored when it ended, over every object
> the run evaluated, including objects the viewer can't read. Every reader sees the same values
> there. They name no object, so they don't show what a viewer can't read, but they can differ
> from the score in a run's results, which counts only the viewer's visible results.

A failed run shows why as a code the UI translates (`error_code`, `error_params`): the app's own
codes, and `run_failed` for any other error (a Databricks SDK or database error, say). The
error text is not sent, as it can name objects or hosts the reader can't see; it stays in the
app log.

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
- `has_description`, `has_purpose` (both types), `has_usage` (products) - Booleans over the description
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
- `owner` - The list of the emails of the active Business Owners (`[]` when none), so test it
  with `LENGTH(d.owner) > 0` or `d.owner CONTAINS 'user@example.com'`. `d.owner != ''` is true
  for a domain with no owners (`[] != ''`), so it does not test emptiness. On `before_update`
  gates the `WHERE` sees the stored owners, but an `ASSERT` on `owner` sees only the change,
  which carries none
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
- **Tags and Lineage**: Read from system tables only when the rule uses them, once per
  chunk of a catalog's tables, only for the schemas a `WHERE` on catalog or schema selects,
  and at most 100 statements and 15 minutes per policy run
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
