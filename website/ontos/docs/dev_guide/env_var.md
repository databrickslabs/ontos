---
sidebar_position: 1
id: env_var
title: Environment Variables
---

# Environment Variables

The following table describes the main Ontos environment variables for Databricks and Database configurations set in the `app.yaml` file and their purpose. 

### Databricks Configuration

| Variable | Description | Example | Required |
|----------|-------------|---------|----------|
| `DATABRICKS_HOST` | Your Databricks workspace URL | `https://your-workspace.cloud.databricks.com` | Yes |
| `DATABRICKS_WAREHOUSE_ID` | SQL Warehouse ID (used by features, not DB) | `1234567890abcdef` | No |
| `DATABRICKS_CATALOG` | Default Unity Catalog catalog | `main` | No |
| `DATABRICKS_SCHEMA` | Default Unity Catalog schema | `default` | No |
| `DATABRICKS_VOLUME` | Volume for storing app-related files | `app_volume` | Yes |
| `DATABRICKS_TOKEN` | Personal access token (optional - SDK can use other auth methods) | `dapi1234567890abcdef` | No |


:::note Automatic configured variables
`DATABRICKS_HTTP_PATH` is derived automatically from `DATABRICKS_WAREHOUSE_ID` and does not need to be set manually.
:::

### Database Configuration

#### Database Properties 

| Variable | Description | Example | Required |
|----------|-------------|---------|----------|
| `POSTGRES_HOST` | PostgreSQL server hostname | `localhost` | Conditional |
| `POSTGRES_PORT` | PostgreSQL server port | `5432` | Conditional |
| `POSTGRES_USER` | PostgreSQL username | `app_user` | Conditional |
| `POSTGRES_PASSWORD` | PostgreSQL password (required for `ENV=LOCAL` only) | `your_secure_password` | Conditional |
| `POSTGRES_DB` | PostgreSQL database name | `app_ontos_db` | Conditional |
| `POSTGRES_DB_SCHEMA` | Database schema for app tables (defaults to `public`) | `app_ontos` | No |

#### Authentication Modes

Ontos stores its metadata (settings, roles, reviews, etc.) in PostgreSQL. The following variables show how Ontos manages authentication modes to access the Database instance.

| Environment | Auth Method | Notes |
|-------------|-------------|-------|
| `ENV=LOCAL` | Password | Uses `POSTGRES_PASSWORD` |
| `ENV=DEV` or `ENV=PROD` | OAuth Token | Auto-generated for Lakebase |

### Connection Pool Settings

| Variable | Default | Description | Recommended |
|----------|---------|-------------|-------------|
| `DB_POOL_SIZE` | 5 | Base number of connections in pool | 5-10 for most apps |
| `DB_MAX_OVERFLOW` | 10 | Additional connections under load | 2x `DB_POOL_SIZE` |
| `DB_POOL_TIMEOUT` | 10 | Max seconds to wait for connection | 10-30 seconds |
| `DB_POOL_RECYCLE` | 3600 | Recycle connections after N seconds | 3600 (1 hour) |
| `DB_COMMAND_TIMEOUT` | 30 | Query execution timeout in seconds | 30-60 seconds |

:::tip Variable configuration for local and Production
For **high-traffic** production we recommend the following:
```bash
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
```
For **local development** the following:
```bash
DB_POOL_SIZE=2
DB_MAX_OVERFLOW=5
DB_POOL_TIMEOUT=10
```
:::

:::warning Heads up on Pool Recycle variable
The `DB_POOL_RECYCLE=3600` default is especially important for Lakebase deployments, as it ensures connections are refreshed before OAuth tokens expire.
:::

### Application Settings

| Variable | Description | Example | Required |
|----------|-------------|---------|----------|
| `ENV` | Deployment environment (`LOCAL`, `DEV`, `PROD`) | `LOCAL` | No |
| `DEBUG` | Enable debug mode for FastAPI | `True` | No |
| `LOG_LEVEL` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` | No |
| `LOG_FILE` | Path to log file | `/path/to/app.log` | No |
| `APP_AUDIT_LOG_DIR` | Directory within `DATABRICKS_VOLUME` for audit logs | `audit_logs` | Yes |
| `APP_ADMIN_DEFAULT_GROUPS` | JSON array of Databricks groups for default Admin role | `["admins", "superusers"]` | No |
| `DEMO_SETUP_TOKEN` | Secret that lets a caller load or clear demo data via the `X-Demo-Setup-Token` header instead of the Admin permission. Leave unset to disable | `a-long-random-value` | No |
| `APP_DEMO_MODE` | Enable demo mode (loads sample data on startup) | `False` | No |
| `APP_DB_DROP_ON_START` | **DANGER:** Drop and recreate database on startup | `False` | No |
| `APP_DB_ECHO` | Log SQLAlchemy SQL statements (debugging) | `False` | No |

### Git Integration (Optional)

| Variable | Description | Example | Required |
|----------|-------------|---------|----------|
| `GIT_REPO_URL` | Git repository URL for config backup/sync | `https://github.com/user/repo.git` | No |
| `GIT_BRANCH` | Git branch for config backup/sync | `main` | No |
| `GIT_USERNAME` | Git authentication username | `git_user` | No |
| `GIT_PASSWORD` | Git password or Personal Access Token | `git_token_or_password` | No |

:arrow_right: The following sections explain how to configure a **Lakebase** instance for Production or a local **PostgreSQL** database for development.
