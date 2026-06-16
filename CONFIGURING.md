# Configuring Ontos

This document covers all configuration options for running Ontos, including environment variables, database setup, and deployment configuration.

## Table of Contents

- [Environment Variables](#environment-variables)
- [Database Configuration](#database-configuration)
- [Local PostgreSQL Setup](#local-postgresql-setup)
- [Lakebase Setup (Production)](#lakebase-setup-production)
- [Default Application Roles](#default-application-roles)

---

## Environment Variables

Create a `.env` file in the project root (see `.env.example` for a complete template).

### Databricks Configuration

| Variable | Description | Example | Required |
|----------|-------------|---------|----------|
| `DATABRICKS_HOST` | Your Databricks workspace URL | `https://your-workspace.cloud.databricks.com` | Yes |
| `DATABRICKS_WAREHOUSE_ID` | SQL Warehouse ID (used by features, not DB) | `1234567890abcdef` | No |
| `DATABRICKS_CATALOG` | Default Unity Catalog catalog | `main` | No |
| `DATABRICKS_SCHEMA` | Default Unity Catalog schema | `default` | No |
| `DATABRICKS_VOLUME` | Volume for storing app-related files | `app_volume` | Yes |
| `DATABRICKS_TOKEN` | Personal access token (optional - SDK can use other auth methods) | `dapi1234567890abcdef` | No |
| `DATABRICKS_CONFIG_PROFILE` | Profile name in `~/.databrickscfg` for OAuth U2M auth (auto-refreshes). Used only when `DATABRICKS_TOKEN` is not set. | `DEFAULT` | No |

**Note:** `DATABRICKS_HTTP_PATH` is derived automatically from `DATABRICKS_WAREHOUSE_ID` and does not need to be set manually.

**Databricks auth resolution order (local dev):**

1. `DATABRICKS_TOKEN` — Personal Access Token (PAT). Highest priority; useful for workspaces that still issue PATs.
2. `DATABRICKS_CONFIG_PROFILE` — named profile in `~/.databrickscfg`. The Databricks SDK uses OAuth U2M and auto-refreshes the token, so this works even when admins disable PATs (run `databricks auth login --profile <name>` once to seed the profile).
3. SDK implicit auth — used in Databricks Apps where the platform injects credentials.

### Database Configuration

| Variable | Description | Example | Required |
|----------|-------------|---------|----------|
| `POSTGRES_HOST` | PostgreSQL server hostname | `localhost` | Conditional |
| `POSTGRES_PORT` | PostgreSQL server port | `5432` | Conditional |
| `POSTGRES_USER` | PostgreSQL username | `app_user` | Conditional |
| `POSTGRES_PASSWORD` | PostgreSQL password (required for `ENV=LOCAL` only) | `your_secure_password` | Conditional |
| `POSTGRES_DB` | PostgreSQL database name | `app_ontos_db` | Conditional |
| `POSTGRES_DB_SCHEMA` | Database schema for app tables (defaults to `public`) | `app_ontos` | No |

### Connection Pool Settings

| Variable | Default | Description | Recommended |
|----------|---------|-------------|-------------|
| `DB_POOL_SIZE` | 5 | Base number of connections in pool | 5-10 for most apps |
| `DB_MAX_OVERFLOW` | 10 | Additional connections under load | 2x `DB_POOL_SIZE` |
| `DB_POOL_TIMEOUT` | 10 | Max seconds to wait for connection | 10-30 seconds |
| `DB_POOL_RECYCLE` | 3600 | Recycle connections after N seconds | 3600 (1 hour) |
| `DB_COMMAND_TIMEOUT` | 30 | Query execution timeout in seconds | 30-60 seconds |

**Performance Tuning Examples:**

For high-traffic production:
```bash
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
```

For local development:
```bash
DB_POOL_SIZE=2
DB_MAX_OVERFLOW=5
DB_POOL_TIMEOUT=10
```

**Note:** The `DB_POOL_RECYCLE=3600` default is especially important for Lakebase deployments, as it ensures connections are refreshed before OAuth tokens expire.

### Application Settings

| Variable | Description | Example | Required |
|----------|-------------|---------|----------|
| `ENV` | Deployment environment (`LOCAL`, `DEV`, `PROD`) | `LOCAL` | No |
| `DEBUG` | Enable debug mode for FastAPI | `True` | No |
| `LOG_LEVEL` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` | No |
| `LOG_FILE` | Path to log file | `/path/to/app.log` | No |
| `APP_AUDIT_LOG_DIR` | Directory within `DATABRICKS_VOLUME` for audit logs | `audit_logs` | Yes |
| `APP_ADMIN_DEFAULT_GROUPS` | JSON array of Databricks groups for default Admin role | `["admins", "superusers"]` | No |
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

---

## Database Configuration

Ontos stores its metadata (settings, roles, reviews, etc.) in PostgreSQL.

### Authentication Modes

| Environment | Auth Method | Notes |
|-------------|-------------|-------|
| `ENV=LOCAL` | Password | Uses `POSTGRES_PASSWORD` |
| `ENV=DEV` or `ENV=PROD` | OAuth Token | Auto-generated for Lakebase |

---

## Local PostgreSQL Setup

For local development, you can run PostgreSQL on your machine.

### 1. Install PostgreSQL

**macOS (Homebrew):**
```bash
brew install postgresql@16
brew services start postgresql@16
```

After installation, add to your PATH:
```bash
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
```

### 2. Create Database and User

Connect as superuser:
```bash
psql -U $(whoami) -d postgres
```

Run these SQL commands:
```sql
-- Create application user
CREATE ROLE ontos_app_user WITH LOGIN PASSWORD '<your_password>';
GRANT ontos_app_user TO "<your_postgres_user>";

-- Create database
CREATE DATABASE app_ontos;
GRANT ALL PRIVILEGES ON DATABASE app_ontos TO ontos_app_user;
GRANT USAGE ON SCHEMA public TO ontos_app_user;
GRANT CREATE ON SCHEMA public TO ontos_app_user;
\q
```

Reconnect to the new database:
```bash
psql -U $(whoami) -d app_ontos
```

Create the application schema:
```sql
CREATE SCHEMA app_ontos;
ALTER SCHEMA app_ontos OWNER TO ontos_app_user;
GRANT USAGE ON SCHEMA app_ontos TO ontos_app_user;
GRANT ALL ON SCHEMA app_ontos TO ontos_app_user;
\q
```

### 3. Configure Environment

Add to your `.env`:
```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=ontos_app_user
POSTGRES_PASSWORD=<your_password>
POSTGRES_DB=app_ontos
POSTGRES_DB_SCHEMA=app_ontos
ENV=LOCAL
```

---

## Lakebase Setup (Production)

When deploying to production with Databricks Lakebase, the application uses **OAuth token authentication** instead of passwords.

### How It Works

- **Username detection:** Service principal username is auto-detected at runtime
- **Token generation:** OAuth tokens are automatically generated using the Databricks SDK
- **Token refresh:** Tokens refresh every 50 minutes (before 60-minute expiry)
- **Connection pooling:** Fresh tokens are automatically injected into database connections

### Setup Steps

#### 1. Create Lakebase Instance

Set up a new [Lakebase instance](https://docs.databricks.com/aws/en/oltp/instances/instance) and wait for it to start.

#### 2. Create Database (One-Time Setup)

Connect to your Lakebase instance:
```bash
psql "host=instance-xxx.database.cloud.databricks.com user=<your_email> dbname=postgres port=5432 sslmode=require"
Password: <paste OAuth token>
```

Create the database with open permissions:
```sql
-- Create the database
CREATE DATABASE "app_ontos";

-- Grant CREATE to PUBLIC so the app's service principal can create schemas
GRANT CREATE ON DATABASE "app_ontos" TO PUBLIC;
\q
```

**Why grant to PUBLIC?** The app's service principal is created automatically when the app first connects. By granting to `PUBLIC`, any authenticated role (including the future SP) can create schemas. This avoids needing to know the SP ID before deployment.

#### 3. Deploy Your App

```bash
databricks apps deploy <app-name>
```

On first startup, the app will:
1. Authenticate as its service principal using OAuth
2. Connect to the `app_ontos` database
3. Create the `app_ontos` schema (becomes schema owner automatically)
4. Set default privileges for future tables/sequences
5. Create all application tables

#### 4. Tighten Permissions (Optional)

After successful deployment, you can revoke the broad `PUBLIC` grant:
```sql
-- Get the SP ID from app logs, then run:
REVOKE CREATE ON DATABASE "app_ontos" FROM PUBLIC;
GRANT CREATE ON DATABASE "app_ontos" TO "<service_principal_uuid>";
```

### App Configuration (app.yaml)

Reference the Lakebase instance in your `app.yaml`:

```yaml
- name: "POSTGRES_HOST"
  valueFrom: "database"  # References your Lakebase instance resource
- name: "POSTGRES_PORT"
  value: "5432"
# POSTGRES_USER is auto-detected from service principal - do not set
- name: "POSTGRES_DB"
  value: "app_ontos"
- name: "POSTGRES_DB_SCHEMA"
  value: "app_ontos"
- name: "ENV"
  value: "PROD"  # Triggers OAuth mode (not LOCAL)
```

### Security Notes

- The `PUBLIC` grant only allows schema creation in the app database
- Only authenticated Databricks principals can connect
- Service principal names are never hardcoded in configuration
- You can optionally tighten permissions after first deploy

---

## Default Application Roles

On first startup, if no roles exist, the application creates default roles:

| Role | Description |
|------|-------------|
| **Admin** | Full administrative access to all features. Assigned to groups in `APP_ADMIN_DEFAULT_GROUPS`. |
| **Data Governance Officer** | Broad administrative access, typically excluding low-level system settings. |
| **Data Steward** | Read/Write access to data governance features (Products, Contracts, Glossary). |
| **Data Consumer** | Read-only access to data discovery features. |
| **Data Producer** | Read-only generally, with write access to create/manage Data Products and Contracts. |
| **Security Officer** | Administrative access to security and entitlements features. |

These roles can be viewed and modified in **Settings → RBAC** after initial startup.

---

## Example .env File

```env
# Databricks Configuration
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_WAREHOUSE_ID=1234567890abcdef
DATABRICKS_CATALOG=main
DATABRICKS_SCHEMA=default
DATABRICKS_VOLUME=app_volume

# Database (Local Development)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=ontos_app_user
POSTGRES_PASSWORD=your_password
POSTGRES_DB=app_ontos
POSTGRES_DB_SCHEMA=app_ontos

# Application Settings
ENV=LOCAL
DEBUG=True
LOG_LEVEL=INFO
APP_AUDIT_LOG_DIR=audit_logs
APP_DEMO_MODE=True

# Optional: Default Admin Groups
APP_ADMIN_DEFAULT_GROUPS=["admins"]
```

---

## Next Steps

- [README.md](README.md) - Project overview
- [CONTRIBUTING.md](CONTRIBUTING.md) - Development setup and guidelines
- [User Guide](src/docs/USER-GUIDE.md) - End-user documentation

