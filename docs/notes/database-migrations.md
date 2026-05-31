# Database Migrations with Alembic

This document describes how database schema changes are managed using Alembic migrations.

## Overview

As of November 2025, this project uses **Alembic** for database schema management. All database changes must go through migrations to ensure consistency across development, staging, and production environments.

### Key Benefits

- **Version Control**: All schema changes are tracked in git
- **Repeatable**: Same migrations run in all environments
- **Rollback**: Can revert to previous schema versions if needed
- **Team Collaboration**: No conflicts between developers changing the schema
- **External Users**: Clear upgrade path for production databases

## Migration Setup

### Initial State

- **Baseline Migration**: `3135632d55e1_initial_schema_capture.py`
  - This is an empty migration that represents the existing schema
  - All tables were already created by SQLAlchemy's `create_all()` before migrations were enabled
  - This establishes the starting point for future changes

### For Existing Databases

If you have an existing database that was created before migrations were enabled:

```bash
cd src/backend
hatch -e dev run alembic stamp head
```

This tells Alembic that your database is already at the latest version without running any migrations.

### For Fresh Databases

The application will automatically:
1. Create all tables using `Base.metadata.create_all()`
2. Stamp the database with the baseline migration

No manual intervention is needed.

## Developer Workflow

### 1. Making Schema Changes

When you need to change the database schema:

1. **Modify your SQLAlchemy models** in `src/backend/src/db_models/`:
   ```python
   # Example: Add a new column to an existing model
   class DataProductDb(Base):
       __tablename__ = 'data_products'

       id = Column(String, primary_key=True)
       name = Column(String, nullable=False)
       description = Column(Text, nullable=True)
       # New column:
       status = Column(String, nullable=False, server_default='draft')
   ```

2. **Ensure the model is imported** in `src/backend/src/common/database.py`:
   ```python
   from src.db_models import data_products
   ```

### 2. Generate a Migration

```bash
cd src/backend
hatch -e dev run alembic revision --autogenerate -m "Add status column to data_products"
```

This will:
- Compare your models with the current database schema
- Generate a migration file in `alembic/versions/` with the detected changes
- Name the file with a revision ID and your message

### 3. Review the Migration

**CRITICAL**: Always review the generated migration! Auto-generation isn't perfect.

```bash
# Open the newly created migration file
cat alembic/versions/<revision_id>_add_status_column_to_data_products.py
```

Check for:
- **Correct operations**: Does it add/remove/modify the right columns/tables?
- **Data migration**: Do you need to populate new columns with data?
- **Indexes**: Are indexes created/dropped correctly?
- **Foreign keys**: Are constraints handled properly?
- **Destructive operations**: Will this delete data unintentionally?

Example migration:
```python
def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('data_products',
                  sa.Column('status', sa.String(), nullable=False, server_default='draft'))

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('data_products', 'status')
```

### 4. Test the Migration

Apply the migration to your development database:

```bash
hatch -e dev run alembic upgrade head
```

Verify:
- The migration applies successfully
- Your application still works
- Data integrity is maintained

Test rollback:
```bash
# Rollback one migration
hatch -e dev run alembic downgrade -1

# Check application still works
# Then reapply
hatch -e dev run alembic upgrade head
```

### 5. Commit the Migration

```bash
git add alembic/versions/<revision_id>_*.py
git commit -m "Add status column to data_products table

This migration adds a status column to track the lifecycle
state of data products (draft, published, archived, etc.)."
```

### 6. Automatic Deployment

When the application starts (`init_db()` in `database.py`):
1. Alembic checks the current database version
2. Automatically applies any pending migrations
3. Logs the results

No manual intervention needed in production!

## Common Commands

### Check Current Version
```bash
hatch -e dev run alembic current
```

### View Migration History
```bash
hatch -e dev run alembic history
```

### Upgrade to Specific Version
```bash
hatch -e dev run alembic upgrade <revision_id>
```

### Downgrade to Previous Version
```bash
hatch -e dev run alembic downgrade -1
```

### Downgrade to Specific Version
```bash
hatch -e dev run alembic downgrade <revision_id>
```

### Create Empty Migration (for data-only changes)
```bash
hatch -e dev run alembic revision -m "Populate default roles"
```

## Best Practices

### 1. One Logical Change Per Migration
Don't combine unrelated changes:
- ❌ Bad: "Add user table and refactor products table"
- ✅ Good: Two separate migrations

### 2. Test Migrations Thoroughly
- Test upgrade AND downgrade paths
- Test with production-like data volume
- Verify application functionality after migration

### 3. Handle Data Carefully
When adding non-nullable columns to existing tables:

```python
def upgrade() -> None:
    # Step 1: Add column as nullable
    op.add_column('data_products', sa.Column('status', sa.String(), nullable=True))

    # Step 2: Populate data
    op.execute("UPDATE data_products SET status = 'draft' WHERE status IS NULL")

    # Step 3: Make it non-nullable
    op.alter_column('data_products', 'status', nullable=False)
```

### 4. Be Careful with Destructive Operations
When dropping columns/tables:
1. Ensure no code references them
2. Consider a two-phase approach:
   - Migration 1: Stop using the column in code
   - Migration 2: Drop the column from database

### 5. Document Complex Migrations
Add comments explaining why:
```python
def upgrade() -> None:
    """Merge duplicate data product entries.

    Before schema change, we need to consolidate products that
    were accidentally created as duplicates. This ensures we don't
    violate the new unique constraint.
    """
    # Deduplication logic here
    ...
```

### 6. Never Edit Existing Migrations
Once a migration is committed and shared:
- ❌ Never modify it
- ✅ Create a new migration to fix issues

### 7. Keep Models and Migrations in Sync
The SQLAlchemy models are the source of truth:
- Models define the desired state
- Migrations are the path to get there
- Always update models first, then generate migrations

## Troubleshooting

### Migration Generation Detects No Changes

**Problem**: `alembic revision --autogenerate` says "No changes detected"

**Solutions**:
1. Verify your model is imported in `database.py`
2. Check that your model uses `Base` as the parent class
3. Restart Python (cached imports might be stale)

### Migration Fails to Apply

**Problem**: `alembic upgrade head` fails

**Solutions**:
1. Check the error message - often shows the specific issue
2. Verify database connectivity
3. Check if schema/table already exists manually
4. Review the migration code for errors

### Database Out of Sync with Models

**Problem**: Manual changes were made to the database

**Solution**: Generate a migration to capture the difference:
```bash
hatch -e dev run alembic revision --autogenerate -m "Sync database with models"
# Review carefully - this will show differences
```

### Need to Rollback Production

**Problem**: A migration caused issues in production

**Solution**:
```bash
# 1. Identify the problematic migration revision
hatch -e dev run alembic current

# 2. Downgrade to the previous version
hatch -e dev run alembic downgrade -1

# 3. Application will use the rolled-back schema on next restart
```

## For External Users

### Upgrading from Pre-Migration Versions

If you're running a version before migrations were enabled:

1. **Backup your database** (critical!)
   ```bash
   pg_dump -Fc your_database > backup_$(date +%Y%m%d).dump
   ```

2. **Pull the latest code** with migration support

3. **Stamp your existing database**:
   ```bash
   cd src/backend
   hatch -e dev run alembic stamp 3135632d55e1
   ```

4. **Restart the application** - future migrations will apply automatically

### Future Upgrades

Once migrations are enabled:
1. Pull the latest code (includes new migrations)
2. Restart the application
3. Migrations apply automatically on startup
4. Monitor logs for migration success:
   ```
   INFO: Alembic upgrade to head COMPLETED.
   INFO: Database schema is up to date according to Alembic.
   ```

## Architecture Details

### Migration Execution Flow

When `init_db()` runs (application startup):

```python
1. Load Alembic configuration
2. Connect to database
3. Check current DB revision (from alembic_version table)
4. Compare with head revision (latest migration file)
5. If different:
   - Run migrations to upgrade to head
   - Log success/failure
6. If same:
   - Log "schema up to date"
   - Continue startup
7. For fresh databases (no alembic_version table):
   - Use create_all() to create initial schema
   - Stamp with baseline migration
```

### Files and Directories

- `alembic.ini`: Alembic configuration
- `alembic/env.py`: Migration environment setup
- `alembic/versions/`: Migration files (committed to git)
- `src/backend/src/common/database.py`: Integration with application
- `src/backend/src/db_models/`: SQLAlchemy model definitions (source of truth)

### Migration Naming Convention

#### Alembic default

Alembic generates file names like:
```
<revision_id>_<message_slug>.py
```

Example: `3135632d55e1_initial_schema_capture.py`

The 12-char hex `<revision_id>` is the value stored in the `revision`
variable inside the file and recorded in the `alembic_version` table.
Older migrations in this repo (e.g. `3135632d55e1_*`, `h8355d269ff1_*`,
`o5022k936mm8_*`) use this default form.

#### Project shorthand: `<letter><number>_<slug>.py`

Starting with the ontology-driven data-model rewrite (`a1_dataset_to_asset_migration.py`),
this project switched to a human-friendly short-id convention:

```
<letter><number>_<slug>.py
```

Examples: `a1_dataset_to_asset_migration.py`, `b2_add_cert_pub_to_contracts.py`,
`g1_add_workflow_snapshot.py`, `j1_add_version_family_id.py`.

The two parts encode:

- **Letter** (`a`, `b`, `c`, …) — a roughly chronological **cohort / wave**
  of related migrations. A new letter is picked when a new feature wave
  starts. Historical waves so far: `a*` = asset/ontology rewrite,
  `b*` = certification + publication scope, `c*` = legacy-dataset cleanup,
  `d*` = ODCS v3.1.0 persistence, `e*` = semantic-models display names,
  `f*` = merge revision (`f1_merge_aa9_e2_heads`), `g*` = workflow
  snapshot, `h*` = consumer-principals / wizard OBO, `i*` = workflow_version
  backfill, `j*` = version_family_id.
- **Number** — order within that wave (`a1`, `a2`, `a3`, …, `a9`).

**Merge revisions** (created via `alembic merge -m '...' <head_a> <head_b>`)
get the next letter and a `merge_<head_a>_<head_b>` slug. Example:
`f1_merge_aa9_e2_heads.py` merges `aa9_is_approver` and `e2_semantic_display_name`.

#### What to use for new migrations

When adding a new migration, prefer the project shorthand:

1. Generate the file: `hatch -e dev run alembic revision -m '<message>'`
2. **Rename** the file from the default `<hex>_<slug>.py` to
   `<letter><number>_<slug>.py`. Pick the letter:
   - **Same wave** as the previous head → bump the number
     (after `j1_add_version_family_id`, the next would be `j2_…`).
   - **New themed wave** → next unused letter (after `j*`, start `k1_…`).
3. **Update the `revision` variable** inside the file to match the short
   id (e.g. `revision = 'j2_my_change'`). The filename prefix is cosmetic,
   but the `revision` string is what Alembic stores and what `down_revision`
   in subsequent migrations must reference.
4. Update the docstring header (`Revision ID: …` and `Revises: …`) to
   match.
5. Set `down_revision` to the **current head** (run `hatch -e dev run alembic heads`).

#### Caveats

- **Alembic only cares about `revision` uniqueness.** The `<letter><number>`
  prefix is purely a project convention; nothing in Alembic, CI, or the
  app enforces it. The hard rules enforced by CI are:
  - exactly **one head** at all times (`check-alembic-heads` job in
    `.github/workflows/test-coverage.yml`), and
  - every migration's `down_revision` resolves to a known revision.
- **Filename prefix vs `revision` string must agree.** If you rename the
  file but forget to update `revision = '...'`, descendants will still
  work (they reference the string, not the filename), but humans will be
  badly confused. Keep them in sync.
- A few historical migrations slipped through with mixed forms
  (`u1688q602tt5_*`, `r8355n269pp2_*`, etc.) — these are old and
  intentionally not renamed to avoid breaking the chain.

## Getting Help

- **Alembic Documentation**: https://alembic.sqlalchemy.org/
- **SQLAlchemy ORM**: https://docs.sqlalchemy.org/
- **Project Issues**: File an issue if migration tooling has bugs
