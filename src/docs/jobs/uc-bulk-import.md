# UC Bulk Import Workflow

## Overview

The **UC Bulk Import** workflow automatically discovers and imports Data Contracts, Data Products, and Data Domains from Unity Catalog based on governed tags applied to catalog objects (tables, schemas, catalogs).

### Purpose

- **Automate Entity Creation**: Eliminate manual entry by discovering entities from existing UC tags
- **Bootstrap the App**: Quickly populate the app with existing metadata from your Unity Catalog environment
- **Maintain Sync**: Run periodically to keep app data synchronized with tagged UC objects
- **Support Multiple Entity Types**: Import contracts, products, and domains in a single workflow

### Supported Entity Types

- **Data Contracts**: Technical metadata definitions for datasets
- **Data Products**: Logical groupings of data assets with business context  
- **Data Domains**: Organizational units for grouping related data products

## When to Use This Workflow

Use the UC Bulk Import workflow when you:

1. **Have existing UC tag conventions** for marking contracts, products, or domains
2. **Want to bootstrap the app** with existing metadata from Unity Catalog
3. **Need periodic synchronization** between UC tags and app entities
4. **Prefer tag-driven workflows** over manual entity creation in the UI

## Configuration

### Accessing Configuration

1. Navigate to **Settings > Jobs** tab
2. Find "UC Bulk Import" in the workflow list
3. Click the **gear icon (⚙️)** next to the workflow name
4. The configuration dialog opens

### Configuration Parameters

#### Entity Patterns

Define how to discover each entity type from UC tags. Each entity type (Contract, Product, Domain) has independent configuration:

**Per-Entity Settings:**

- **Enabled**: Toggle to enable/disable discovery for this entity type
- **Filter Pattern** (Optional): Optionally limit which objects to consider
  - **Filter Source**: Choose whether to match against tag `key` or `value`
  - **Filter Pattern**: Regex pattern to match (e.g., `^include-.*$`)
- **Key Pattern** (Required): Regex to match tag keys identifying this entity type
  - Example: `^data-contract-(.+)$` matches keys like `data-contract-ABC`
- **Value Extraction** (Required): How to extract the entity name
  - **Source**: Extract from tag `key` or tag `value`
  - **Pattern**: Regex with capture group `()` to extract name
    - Example: `^data-contract-(.+)$` extracts "ABC" from "data-contract-ABC"

#### Default Catalog/Schema

- **Default Catalog**: Fallback catalog when physical_name doesn't include it
- **Default Schema**: Fallback schema when physical_name doesn't include it

#### Conflict Strategy

How to handle entities that already exist with the same name:

- **skip** (default): Ignore and log warning if entity name already exists
- **update**: Change an existing draft product or contract in place: add a port
  (product) or schema object (contract) for each tagged table the job never imported
  into it. The job records each table it imports, so a port or schema object you
  delete in the app is not added back. Products and contracts past draft are skipped;
  existing domains are left as they are. Drafts that get nothing new are counted as
  unchanged and keep their `updated_at`.
- **error**: Fail the job if a conflict is detected

> **Note**: Database connection parameters (host, database name, OAuth instance) are automatically provided by the system from application settings. You don't need to configure these.

## Pattern Syntax

### Regular Expression Basics

Regular expressions (regex) define search patterns. Key concepts:

- **Literal characters**: Match exactly (e.g., `data-contract` matches that text)
- **`.`**: Matches any single character
- **`+`**: Matches one or more of the preceding character/group
- **`*`**: Matches zero or more of the preceding character/group
- **`^`**: Anchors to start of string
- **`$`**: Anchors to end of string
- **`()`**: Capture group - extracts matched content
- **`[]`**: Character class (e.g., `[a-z]` matches any lowercase letter)
- **`\`**: Escape special characters (e.g., `\.` matches a literal period)

### Capture Groups

Use parentheses `()` to extract portions of the matched text:

- Pattern: `^data-contract-(.+)$`
- Input: `data-contract-customer_360`
- Extracted: `customer_360` (content inside parentheses)

### Common Patterns

**Key-Based Extraction:**
```regex
^data-contract-(.+)$
```
- Matches: `data-contract-customer_360`
- Extracts: `customer_360`

**Value-Based Extraction:**
```regex
^contract:(.+)$
```
- Tag key: `metadata`
- Tag value: `contract:customer_360`
- Extracts: `customer_360`

**Complex Pattern with Prefix/Suffix:**
```regex
^ontos-product-(.+)-v\d+$
```
- Matches: `ontos-product-sales_analytics-v2`
- Extracts: `sales_analytics`

**Domain from Schema:**
```regex
^domain_(.+)$
```
- Schema tag key: `domain_finance`
- Extracts: `finance`

## Discovery Process

### Step-by-Step Execution

1. **Load Configuration**: Read saved entity patterns from database
2. **Query UC Tags**: Scan `information_schema.{CATALOGS|SCHEMA|TABLE}_TAGS` views
3. **Apply Filters**: If filter patterns defined, check objects against filters
   - **Filter Inheritance**: Schema-level filter tags apply to child tables
4. **Match Key Patterns**: Apply key pattern regex to find matching tags
5. **Extract Names**: Use extraction pattern to capture entity names from matched tags
6. **Group Objects**: Collect all objects associated with each entity name
7. **Create Entities**:
   - **Contracts**: Create `DataContractDb` + `SchemaObjectDb` for each table
   - **Products**: Create `DataProductDb` + `OutputPortDb` linking to tables
   - **Domains**: Create `DataDomainDb` entries
8. **Link Products to Contracts**: Auto-link when same table has both contract and product tags
9. **Handle Conflicts**: Apply conflict strategy (skip/update/error)
10. **Report Results**: Log statistics (discovered, created, skipped, errors)

### Filter Inheritance

Filter patterns are inherited from parent to child:

- **Catalog-level filter tag** → Applies to all schemas and tables in that catalog
- **Schema-level filter tag** → Applies to all tables in that schema  
- **Table-level filter tag** → Applies only to that specific table

### Entity Creation Details

**Contracts:**
- Populate minimal required fields: `name`, `version`, `status`, `kind`, `api_version`
- Create `SchemaObjectDb` entry for each matched table with `physical_name` set

**Products:**
- Populate minimal required fields: `name`, `version`, `status`, `kind`, `api_version`
- Create `OutputPortDb` entries linking product to tables
- If contract exists for same table, set `contract_id` in output port (newest version
  of the contract; only on ports of draft products that have no contract yet)

**Domains:**
- Create basic domain record with `name`, `description` (if available)

## Running the Workflow

### Enable the Workflow

1. Go to **Settings > Jobs**
2. Find "UC Bulk Import"
3. **Configure** patterns (click gear icon)
4. **Toggle on** to enable the workflow
5. Click **Save**

The workflow will now be deployed to Databricks as a scheduled job.

### Manual Trigger

To run immediately:

1. Ensure workflow is enabled and deployed
2. Click the **Play icon (▶️)** next to "UC Bulk Import"
3. Monitor progress in real-time

### Scheduled Execution

- **Default Schedule**: Daily at 2:00 AM UTC
- **Modify Schedule**: Edit `uc_bulk_import.yaml` and redeploy
- **Pause Schedule**: Click the **Pause icon (⏸️)**

### Monitoring

**View Run History:**

1. Click the **History icon (🕒)** next to "UC Bulk Import"
2. See all past runs with status, duration, and timestamps
3. Click a run to view detailed logs

**Check Run Status:**

- **Green checkmark**: Completed successfully
- **Red X**: Failed (check logs for errors)
- **Yellow warning**: Completed with warnings (some entities skipped)
- **Blue spinner**: Currently running

**Overlapping runs:** one run imports at a time. A run that starts while another
one is importing (it can't take the job's database lock) imports nothing and
fails with exit code `3`, so it shows as failed rather than green; errors while
importing exit with `1`. The lock needs a direct database connection: a
transaction-mode connection pooler doesn't support it.

## Examples

### Example 1: Simple Key-Based Contract Discovery

**Scenario**: Tables tagged with `data-contract-{name}` keys

**Configuration:**
```yaml
Entity Type: contract
Enabled: true
Key Pattern: ^data-contract-(.+)$
Value Extraction Source: key
Value Extraction Pattern: ^data-contract-(.+)$
```

**UC Tags:**
```
catalog.schema.customers: data-contract-customer_360 = ""
catalog.schema.orders: data-contract-order_history = ""
```

**Result:**
- Contract "customer_360" created with `customers` table as schema object
- Contract "order_history" created with `orders` table as schema object

### Example 2: Value-Based Product Discovery with Filters

**Scenario**: Product names stored in tag values, only for "production" schemas

**Configuration:**
```yaml
Entity Type: product
Enabled: true
Filter Source: key
Filter Pattern: ^env-production$
Key Pattern: ^product-metadata$
Value Extraction Source: value
Value Extraction Pattern: ^product:(.+)$
```

**UC Tags:**
```
catalog.prod_schema: env-production = "true"
catalog.prod_schema.sales_data: product-metadata = "product:sales_analytics"
catalog.dev_schema.test_data: product-metadata = "product:test_product"  # Filtered out
```

**Result:**
- Product "sales_analytics" created (schema has env-production tag)
- "test_product" skipped (dev_schema lacks production filter tag)

### Example 3: Multi-Entity Import with Linking

**Scenario**: Tables tagged with both contract and product identifiers

**Configuration:**
```yaml
# Contract pattern
Entity Type: contract
Key Pattern: ^data-contract-(.+)$
Value Extraction: key / ^data-contract-(.+)$

# Product pattern  
Entity Type: product
Key Pattern: ^data-product-(.+)$
Value Extraction: key / ^data-product-(.+)$
```

**UC Tags:**
```
catalog.schema.user_profiles:
  - data-contract-user_data
  - data-product-user_360
```

**Result:**
- Contract "user_data" created
- Product "user_360" created
- Product output port automatically linked to "user_data" contract

### Example 4: Domain Discovery from Schema Tags

**Scenario**: Schemas tagged with domain identifiers

**Configuration:**
```yaml
Entity Type: domain
Enabled: true
Key Pattern: ^data-domain-(.+)$
Value Extraction Source: key
Value Extraction Pattern: ^data-domain-(.+)$
```

**UC Tags:**
```
catalog.finance_schema: data-domain-finance = ""
catalog.marketing_schema: data-domain-marketing = ""
```

**Result:**
- Domain "finance" created
- Domain "marketing" created

## Troubleshooting

### Common Regex Mistakes

**Issue**: Pattern doesn't match expected tags

**Solutions:**
- **Test patterns**: Use online regex testers (regex101.com) with sample tags
- **Escape special characters**: Use `\.` for literal periods, `\(` for literal parentheses
- **Anchor patterns**: Add `^` at start and `$` at end for exact matches
- **Check capture groups**: Ensure parentheses `()` are around the part you want to extract

**Example Fix:**
```
❌ Bad:  data-contract-.*  (matches too broadly)
✅ Good: ^data-contract-(.+)$  (anchored, captures name)
```

### Pattern Testing Strategies

1. **Start Simple**: Test with one tag key/value pair first
2. **Use Dry-Run Mode**: Set `dry_run: "true"` to see what would be imported without creating entities
3. **Check Logs**: Review job logs for pattern matching details
4. **Iterate**: Refine patterns based on log output

### Dry-Run Mode

Enable dry-run to preview results without creating entities:

1. Edit `uc_bulk_import.yaml`
2. Set `parameters.dry_run: "true"`
3. Redeploy workflow
4. Run and check logs for "would create" messages

### Log Analysis

**Key log messages:**

- `Processing {entity_type} patterns...`: Starting entity type
- `Discovered X objects for {entity_name}`: Found matching tags
- `Created {entity_type} {name}`: Successfully created
- `Skipped {entity_type} {name}: already exists`: Conflict with skip strategy
- `Failed to create {entity_type} {name}: {error}`: Creation error

### Handling Duplicate Names

**Problem**: Multiple objects with same extracted name

**Conflict Strategy Options:**

1. **skip**: First discovered creates entity, rest ignored (safe, recommended)
2. **update**: Adds newly tagged tables to existing drafts (see Conflict Strategy)
3. **error**: Job fails, requires manual resolution (strictest)

**Best Practice:**
- Use specific patterns to avoid name collisions
- Review skipped entities in logs
- Manually merge/deduplicate if needed

## Advanced Configuration

### Multiple Patterns Per Entity Type

To handle multiple tagging conventions, run the job multiple times with different configurations, or extend the pattern matching logic in the Python script.

### Custom Entity Mapping

The workflow creates entities with minimal fields. To populate additional fields:

1. Let workflow create basic entities
2. Use the UI or API to enrich entities with:
   - Descriptions
   - Owners and teams
   - SLA properties
   - Custom metadata

### Integration with Other Workflows

**Recommended Workflow Order:**

1. **UC Bulk Import**: Import entities from UC tags (this workflow)
2. **DQX Profile Datasets**: Profile contracts and suggest quality checks
3. **Data Quality Checks**: Validate contracts against actual data
4. **UC Bulk Export**: Sync enriched metadata back to UC tags

## Performance Considerations

### Large Catalogs

For catalogs with thousands of tables:

- **Limit Scope**: Use filter patterns to process subsets
- **Batch Runs**: Run for specific catalogs/schemas separately
- **Monitor Timeout**: Increase `timeout_seconds` if needed

### Scheduling Frequency

- **Initial Load**: Run once to bootstrap
- **Incremental Sync**: Daily or weekly for ongoing updates
- **On-Demand**: Manual trigger after bulk tagging operations

## Security and Permissions

### Required Permissions

The job's service principal needs:

- **Unity Catalog**: `USE CATALOG`, `USE SCHEMA`, `SELECT` on `information_schema` views
- **App Database**: Write access to `data_contracts`, `data_products`, `data_domains` tables

### Audit Trail

All imports are logged with:
- Timestamp
- Discovered entities
- Created/skipped/failed counts
- Configuration used

## Related Documentation

- [Job Configuration System](./job-configuration-system.md) - How workflow configuration works
- [UC Bulk Export](./uc-bulk-export.md) - Reverse sync (app to UC tags)
- [Data Contracts Guide](../USER-GUIDE.md#data-contracts) - Working with contracts in the app
- [Data Products Guide](../USER-GUIDE.md#data-products) - Working with products in the app

