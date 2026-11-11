# Contributing to Ontos

Thank you for your interest in contributing to Ontos! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Commit Guidelines](#commit-guidelines)
- [Versioning](#versioning)
- [Release Process](#release-process)
- [Pull Request Process](#pull-request-process)
- [Code Style](#code-style)
- [Testing](#testing)
- [License](#license)

---

## Code of Conduct

Please be respectful and professional in all interactions. We're building a collaborative community around data governance.

---

## Getting Started

### Prerequisites

- **Python 3.10 - 3.12** (as defined in `pyproject.toml`)
- **Node.js 18+** (includes npm, the frontend package manager)
- **Hatch** (Python build tool):
  ```bash
  pip install hatch
  ```

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/ontos.git
   cd ontos
   ```
3. Add the upstream remote:
   ```bash
   git remote add upstream https://github.com/databrickslabs/ontos.git
   ```

---

## Development Setup

### 1. Install Dependencies

```bash
# Frontend dependencies
cd src/frontend
npm install

# Backend dependencies are managed by Hatch and installed automatically
```

#### Working Behind a Private npm Mirror (optional)

Some corporate environments block the public npm registry and require all
package traffic to flow through an internal mirror (e.g., Nexus, Artifactory,
Verdaccio, or an HTTPS pass-through proxy). npm handles this cleanly: point the
registry at your mirror and npm rewrites the host of each `resolved` URL at
install time. Because npm's `replace-registry-host` defaults to `"npmjs"`, the
committed `package-lock.json` keeps its canonical `https://registry.npmjs.org/`
URLs, and `npm ci` does **not** persist the rewrite back to the lockfile — so
there is no diff to worry about and no git filter needed.

Set the registry per-clone without committing anything:

```bash
# In the frontend project (or globally via ~/.npmrc)
npm config set registry https://<your-mirror-host>/
```

`npm install`, `npm ci`, and `npm install <pkg>` all work normally, and any
commits you make contain only real dependency changes against the public
registry URLs. Integrity hashes (`integrity sha512-...`) are independent of the
URL, so package verification is unaffected.

### 2. Configure Environment

Create a `.env` file in the project root:

```bash
cp .env.example .env
# Edit .env with your configuration
```

See **[CONFIGURING.md](CONFIGURING.md)** for complete documentation on:
- All environment variables
- Database setup (local PostgreSQL and Lakebase)
- Connection pool tuning
- Default roles configuration

### 3. Start Development Servers

**Frontend** (Terminal 1):
```bash
cd src/frontend
npm run dev:frontend
```

**Backend** (Terminal 2):
```bash
cd src
npm run dev:backend
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs (Swagger): http://localhost:8000/docs

### Running Multiple Worktrees Side-by-Side

If you develop in more than one git worktree at once (e.g. one per feature
branch), **each worktree must run its own frontend and backend on distinct
ports** — otherwise a second worktree's servers bind to the same 3000/8000 and
either fail to start or, worse, serve one branch's frontend against the other
branch's backend. The default `3000`/`8000` are fine for a single worktree;
give every additional worktree its own pair.

The frontend port and proxy target are env-var driven; the backend port is
passed directly to `uvicorn`:

| Variable | Default | Controls |
|----------|---------|----------|
| `VITE_PORT` | `3000` | Vite dev-server port |
| `VITE_PROXY_TARGET` | `http://localhost:8000` | backend the Vite dev server proxies `/api`, `/docs`, `/redoc` to |

Point the frontend at its own backend with `VITE_PROXY_TARGET` so the proxy
targets the matching port. Example — a second worktree on backend `8100` /
frontend `3100`:

**Backend** (from `src/`): invoke `uvicorn` directly with the port you want.
The `yarn dev:backend` / `hatch -e dev run dev-backend` shortcut is hard-coded to
`8000`, so a secondary worktree runs the underlying command instead:
```bash
hatch -e dev run uvicorn --app-dir backend src.app:app --reload --host=0.0.0.0 --port=8100
```

**Frontend** (from `src/frontend/`):
```bash
VITE_PORT=3100 VITE_PROXY_TARGET=http://localhost:8100 yarn dev:frontend
```

Both worktrees can share the same local `app_ontos` PostgreSQL database; only
the HTTP ports need to differ.

---

## Commit Guidelines

We use [Conventional Commits](https://www.conventionalcommits.org/) for all commit messages. This enables automatic changelog generation and semantic versioning.

### Commit Message Format

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Types

| Type | Description |
|------|-------------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation only changes |
| `style` | Code style changes (formatting, missing semicolons, etc.) |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf` | Performance improvements |
| `test` | Adding or updating tests |
| `build` | Changes to build system or dependencies |
| `ci` | Changes to CI configuration |
| `chore` | Other changes that don't modify src or test files |
| `revert` | Reverts a previous commit |

### Scope (optional)

The scope provides additional context. Common scopes include:

- `frontend` - React/TypeScript frontend changes
- `backend` - Python/FastAPI backend changes
- `api` - API endpoint changes
- `db` - Database/model changes
- `auth` - Authentication/authorization changes
- `contracts` - Data contracts feature
- `products` - Data products feature
- `compliance` - Compliance policies feature
- `semantic` - Semantic models feature
- `mcp` - MCP integration

### Examples

```bash
# Feature
feat(contracts): add schema validation for ODCS v3.1.0

# Bug fix
fix(backend): correct date parsing in contract import

# Documentation
docs: update API documentation for MCP endpoints

# Refactoring
refactor(frontend): extract form components into shared module

# Breaking change (use ! or BREAKING CHANGE footer)
feat(api)!: change data product response format

# With body and footer
feat(products): add data lineage visualization

Implements interactive DAG view for data product dependencies.
Uses react-flow for rendering and supports zoom/pan navigation.

Closes #123
```

### Pre-commit Checks

Before committing, ensure:

1. **Tests pass**:
   ```bash
   # Backend tests
   cd src && hatch -e dev run test
   
   # Frontend tests
   cd src/frontend && npm run test:run
   ```

2. **Linting passes**:
   ```bash
   # Backend
   cd src && hatch -e dev run lint:all
   
   # Frontend
   cd src/frontend && npm run type-check
   ```

3. **Commit message follows convention**

---

## Versioning

We use [Semantic Versioning](https://semver.org/) (SemVer):

- **MAJOR** (X.0.0): Breaking changes
- **MINOR** (0.X.0): New features (backward compatible)
- **PATCH** (0.0.X): Bug fixes (backward compatible)

### Version Files

The project tracks version in multiple files:

| File | Purpose |
|------|---------|
| `src/pyproject.toml` | Python/Hatch build config (source of truth) |
| `src/backend/src/__init__.py` | Python runtime `__version__` |
| `src/frontend/package.json` | Node/npm frontend |
| `src/package.json` | Root build helper |

### Bump Version Script

Use the provided script to keep all version files in sync:

```bash
# View current versions
python src/scripts/bump_version.py

# Update all files to a new version
python src/scripts/bump_version.py 0.5.0

# Dry run (preview changes without applying)
python src/scripts/bump_version.py --dry-run 0.5.0
```

The script will:
1. Update all version files
2. Print next steps for committing and tagging

---

## Release Process

### 1. Prepare Release

```bash
# Ensure you're on main and up to date
git checkout main
git pull upstream main

# Create release branch (optional for larger releases)
git checkout -b release/0.5.0
```

### 2. Update Version

```bash
python src/scripts/bump_version.py 0.5.0
```

### 3. Update Changelog (if maintaining one)

Add release notes to `CHANGELOG.md` summarizing changes since last release.

### 4. Commit and Tag

```bash
git add -A
git commit -m "chore: bump version to 0.5.0"
git tag v0.5.0
```

### 5. Push

```bash
git push origin main
git push origin v0.5.0
# Or if on release branch:
# git push origin release/0.5.0
# Then create PR and merge
```

### 6. Create GitHub Release

1. Go to GitHub Releases
2. Click "Draft a new release"
3. Select the tag `v0.5.0`
4. Add release notes (can be auto-generated from commits)
5. Publish

### 7. Deploy

```bash
databricks bundle deploy --var="catalog=app_data" --var="schema=app_ontos"
databricks apps deploy <app-name>
```

---

## Pull Request Process

### Before Submitting

1. **Sync with upstream**:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Run tests**:
   ```bash
   cd src && hatch -e dev run test
   cd src/frontend && npm run test:run
   ```

3. **Check types and lint**:
   ```bash
   cd src/frontend && npm run type-check
   ```

### PR Guidelines

1. **Title**: Use conventional commit format
   - `feat(products): add export to YAML feature`
   
2. **Description**: Include:
   - What changes were made
   - Why the changes were needed
   - How to test the changes
   - Screenshots for UI changes

3. **Size**: Keep PRs focused and reasonably sized
   - Large features should be broken into smaller PRs

4. **Reviews**: 
   - At least one approval required
   - Address all review comments

### After Merge

- Delete your feature branch
- Pull latest main to your local

---

## Code Style

### Python (Backend)

- Follow [PEP 8](https://pep8.org/)
- Use type hints extensively
- Use `async def` for async operations
- Max line length: 100 characters

```python
async def get_data_product(
    product_id: str,
    db: Session = Depends(get_db),
) -> DataProductResponse:
    """Retrieve a data product by ID."""
    ...
```

### TypeScript (Frontend)

- Use TypeScript strictly (no `any` where avoidable)
- Prefer `interface` over `type` for object shapes
- Use functional components with hooks
- Follow React best practices

```typescript
interface DataProductCardProps {
  product: DataProduct;
  onSelect: (id: string) => void;
}

export const DataProductCard: React.FC<DataProductCardProps> = ({
  product,
  onSelect,
}) => {
  // ...
};
```

### File Naming

- **Python**: `snake_case.py` (e.g., `data_products_manager.py`)
- **TypeScript**: `kebab-case.tsx` (e.g., `data-product-card.tsx`)
- **Tests**: `test_*.py` or `*.test.tsx`

---

## Testing

### Backend Tests

```bash
cd src

# Run all tests
hatch -e dev run test

# Run with coverage
hatch -e dev run test-cov

# Run specific test file
hatch -e dev run pytest backend/src/tests/unit/test_data_products.py
```

### Frontend Tests

```bash
cd src/frontend

# Run tests
npm run test:run

# Run with coverage
npm run test:coverage

# Run in watch mode
npm run test:watch

# Run E2E tests
npm run test:e2e
```

### Writing Tests

- Place unit tests next to the code or in `tests/unit/`
- Name tests descriptively: `test_create_data_product_validates_schema`
- Use fixtures for common setup
- Aim for >80% coverage on new code

### Local Directory Provider (PrincipalPicker testing)

Many surfaces in the app use the `PrincipalPicker` to resolve users and
groups against the configured Directory provider (Roles, Entitlements,
Reviews, Comments audience, Workflow Designer custom principals, Data
Contract wizard owner/stakeholders, etc.). To exercise the configured
code path locally without standing up an Entra ID tenant or a Lakebase
table, use the bundled `file` provider against the sample CSV at
`src/backend/src/data/principals.csv`.

The CSV ships with three users (Alice / Bob / Carol) and three groups
(Producers / Consumers / Admins) and matches the format the
`FileProvider` expects:

```csv
type,id,display_name,sub_label
user,alice@example.com,Alice Liddell,alice@example.com
user,bob@example.com,Bob Builder,bob@example.com
user,carol@example.com,Carol Carlsson,carol@example.com
group,Producers,Data Producers,producers-guid
group,Consumers,Data Consumers,consumers-guid
group,Admins,Platform Admins,admins-guid
```

**Configure via the UI (recommended):**

1. Start the dev servers (see [Development Setup](#development-setup)).
2. Sign in as a user with `settings:READ_WRITE` permission.
3. Navigate to **Settings → Integrations → Directory**.
4. Pick **CSV file (test / demo)** as the Provider.
5. Set **CSV file path** to the absolute path of the bundled file, e.g.
   `/Users/you/code/ontos/src/backend/src/data/principals.csv`.
6. Click **Save**, then **Test connection** — you should see a success
   toast.

**Configure via the backend directly** (e.g. in a test fixture or
seed script):

```python
from src.repositories.app_settings_repository import app_settings_repo

app_settings_repo.set_by_key(db, "DIRECTORY_PROVIDER_TYPE", "file")
app_settings_repo.set_by_key(
    db,
    "DIRECTORY_FILE_PATH",
    "/absolute/path/to/src/backend/src/data/principals.csv",
)
```

**Verify it works:**

- `GET /api/directory/status` → `{ "configured": true, "provider_type": "file", "file_path": "/…/principals.csv" }`
- `GET /api/directory/search?q=ali&types=users` → returns Alice
- In any picker (e.g. Assign Owner on a Data Product), type `al` —
  the dropdown should show a two-line row with `Alice Liddell` and
  `alice@example.com` underneath.

The file is re-read whenever its `mtime` advances, so editing the CSV
takes effect on the next picker query without a server restart. The
sample file is checked in as a fixture — feel free to extend it
locally, but please don't commit org-specific edits.

### Testing with Different User Personas (Runtime Impersonation)

The app supports per-request user impersonation via HTTP headers, so you can
test how features behave for different personas (Admin, Data Producer,
Consumer, etc.) against the **same running backend**. No restarts are needed.

> ⚠️ **Security:** anyone holding `TEST_USER_TOKEN` can act as any user and
> any groups, including admin. Only enable it on local or dev/test
> deployments, never in production. It is **off by default**: when the
> variable is unset, the `X-Test-*` headers are ignored, normal OBO resolution
> applies, and `GET /api/test/personas` returns 404.

**How it works:**

- The backend enables impersonation only when `TEST_USER_TOKEN` is set.
- A client (the UI persona picker, curl, Playwright, ...) sends
  `X-Test-Token: <token>` plus the identity to use (`X-Test-User-Email`,
  optional `X-Test-User-Groups`). When the token matches, the backend uses
  that identity instead of the real user.
- The persona list shown in the UI (`GET /api/test/personas`) is resolved in
  this order:
  1. **Volume override:** `{DATABRICKS_VOLUME}/config/test_personas.yaml`.
     When this file exists, it is used *exclusively*.
  2. **Repo-bundled fallback:** `src/backend/src/data/test_personas.yaml`.

  Both files use the same schema. The list is cached for ~30s, so edits show
  up without a restart. The persona list only controls *which* personas the
  picker offers. It does not grant anything by itself.

Pick the setup that matches how you run Ontos:

| | Option A: local development | Option B: deployed app |
|---|---|---|
| You run Ontos from | a clone of this repo (`npm run dev` + `hatch`) | a Databricks App deployed with a bundle that references the Ontos repo |
| Token configured in | `src/backend/.env` | a secret scope, wired in **your** bundle |
| UI picker token | `VITE_TEST_USER_TOKEN` in `src/frontend/.env` | `localStorage["ucapp.testToken"]` in the browser |
| Edit personas by | editing the repo-bundled YAML (or the volume file) | uploading the YAML to the app's volume |

#### Option A: local development (cloned repo)

1. Generate a token, e.g. `openssl rand -hex 32`.
2. Set it on the backend: `TEST_USER_TOKEN=<your-token>` in
   `src/backend/.env`.
3. (For the UI picker) set the same value as
   `VITE_TEST_USER_TOKEN=<your-token>` in `src/frontend/.env`. It is read by
   the Vite dev server, so this only works in local dev.
4. To change the personas, edit `src/backend/src/data/test_personas.yaml`
   locally (please don't commit org-specific personas). If
   `DATABRICKS_VOLUME` resolves to a Unity Catalog volume (e.g. the dotted
   `main.default.app_files` from `.env.example`) and your workspace
   credentials can read it, an override file on that volume takes precedence.
5. In the user-info dropdown, a "Test persona" section lists the personas.
   Pick one and the page reloads with every API request impersonating that
   user. A yellow ring around the avatar shows that a persona is active.

From curl, Playwright, or any other HTTP client:

```bash
curl -H "X-Test-Token: <your-token>" \
     -H "X-Test-User-Email: producer@test.local" \
     -H "X-Test-User-Groups: [\"data-producers\"]" \
     http://localhost:8000/api/user/details
```

#### Option B: deployed app (bundle referencing the Ontos repo)

Configure everything in **your own** bundle and workspace. No change to the
Ontos repo is needed.

1. Generate a token, e.g. `openssl rand -hex 32`.
2. Store the token in a secret scope:

   ```bash
   databricks secrets create-scope <scope>          # if it doesn't exist yet
   databricks secrets put-secret <scope> <key>      # paste the token
   ```

3. Update the bundle file `src/databricks.yaml`. Use the code snippet below as an example:

   - `variables.app_config` is the app's runtime configuration (it replaces `src/app.yaml`).
   - `resources.apps.ontos.resources` declares the workspace objects the app
     may use (database, warehouse, endpoint, volume, secret). An `env` entry
     with `value_from: <name>` takes its value from the resource with that
     `name`.

   The two blocks marked `TEST PERSONAS` are the only additions to test with
   the impersonation.

   ```yaml
   bundle:
     name: ontos

   variables:
     sql_warehouse_id:
       description: "ID of the SQL warehouse to use"
       lookup:
         warehouse: "<warehouse name>"        # e.g. "Serverless Starter Warehouse"
     catalog_name:
       description: "Unity Catalog catalog for app data"
       default: "app_data"
     schema_name:
       description: "Schema for app data; also used as the Postgres schema"
       default: "app_ontos"
     volume_name:
       description: "Volume for app files (audit logs, outputs, persona override)"
       default: "app_files"
     lakebase_branch:
       description: "Lakebase branch the app connects to"
       default: "projects/<lakebase-project>/branches/<branch>"
     lakebase_database:
       description: "Lakebase database on that branch"
       default: "projects/<lakebase-project>/branches/<branch>/databases/<database>"
     llm_endpoint_name:
       description: "Model serving endpoint for LLM features"
       default: "<serving endpoint name>"
     # TEST PERSONAS: where the TEST_USER_TOKEN secret lives (step 2).
     test_user_token_secret_scope:
       description: "Secret scope holding TEST_USER_TOKEN"
       default: "<scope>"
     test_user_token_secret_key:
       description: "Secret key holding TEST_USER_TOKEN"
       default: "<key>"

     app_config:
       type: complex
       description: "Ontos runtime configuration (replaces src/app.yaml)"
       default:
         command:
           - python
           - backend/src/app.py
         env:
           - name: ENV
             value: DEV
           - name: APP_DEMO_MODE
             value: "false"
           # Keep "false". "true" drops the Postgres schema on every start.
           - name: APP_DB_DROP_ON_START
             value: "false"
           - name: PYTHONPATH
             value: ./backend
           - name: PYTHONUNBUFFERED
             value: "1"
           - name: FRONTEND_STATIC_DIR
             value: ./static
           - name: PGSCHEMA
             value: ${var.schema_name}
           - name: POSTGRES_HOST
             value_from: database
           - name: DATABRICKS_CATALOG
             value: ${var.catalog_name}
           - name: DATABRICKS_SCHEMA
             value: ${var.schema_name}
           - name: DATABRICKS_WAREHOUSE_ID
             value_from: sql-warehouse
           # Resolves to /Volumes/<catalog>/<schema>/<volume>. The persona
           # override is read from config/test_personas.yaml under it.
           - name: DATABRICKS_VOLUME
             value_from: volume
           - name: APP_ADMIN_DEFAULT_GROUPS
             value: '["admins"]'
           - name: APP_AUDIT_LOG_DIR
             value: audit_logs
           - name: LLM_ENABLED
             value: "True"
           - name: LLM_ENDPOINT
             value_from: serving-endpoint
           # TEST PERSONAS: enables impersonation. Remove for production.
           - name: TEST_USER_TOKEN
             value_from: test-user-token

   resources:
     apps:
       ontos:
         name: "ontos-dev"
         description: "Ontos (dev/test)"
         # Path to the Ontos `src/` directory, relative to this file
         # (e.g. "." if this file sits in src/, "./ontos/src" for a submodule).
         source_code_path: "."
         config: ${var.app_config}
         resources:
           - name: database
             postgres:
               branch: ${var.lakebase_branch}
               database: ${var.lakebase_database}
               permission: CAN_CONNECT_AND_CREATE
           - name: sql-warehouse
             sql_warehouse:
               id: ${var.sql_warehouse_id}
               permission: CAN_USE
           - name: serving-endpoint
             serving_endpoint:
               name: ${var.llm_endpoint_name}
               permission: CAN_QUERY
           # WRITE_VOLUME (as in src/manifest.yaml): the app writes audit logs
           # and other files here, and reads the persona override from it.
           - name: volume
             uc_securable:
               securable_type: VOLUME
               securable_full_name: ${var.catalog_name}.${var.schema_name}.${var.volume_name}
               permission: WRITE_VOLUME
           # TEST PERSONAS: supplies TEST_USER_TOKEN. Remove for production.
           - name: test-user-token
             secret:
               scope: ${var.test_user_token_secret_scope}
               key: ${var.test_user_token_secret_key}
               permission: READ
         permissions:
           - user_name: "*"
             level: CAN_USE

   targets:
     dev:
       default: true
       variables:
         catalog_name: "app_data_dev"
         schema_name: "app_ontos_dev"
         volume_name: "app_files_dev"
   ```
4. Validate/Deploy and Run your bundle
   ```bash
   databricks bundle validate -t dev          # validate your deployment for the dev target
   databricks bundle deploy -t dev            # deploy the bundle
   databricks bundle run ontos -t dev         # run the Ontos app with the configuration passed in the app_config variable in databricks.yaml, which will take precedent over the app.yaml file.
   ```

   > ⚠️ **Security:** Make sure to not keep this feature enabled in 
   > the production environment!
   
5. Enable the UI picker in your browser. The deployed frontend is a static
   build, so `VITE_TEST_USER_TOKEN` is not available there. Open the app, 
   then run this in the browser devtools console and reload:

   ```js
   localStorage.setItem("ucapp.testToken", "<your-token>")
   ```

   Run `localStorage.removeItem("ucapp.testToken")` to turn it off again.

6. To customize the personas without a repo change, upload a YAML file (same
   schema as `src/backend/src/data/test_personas.yaml`) to the app's volume:

   ```bash
   databricks fs cp test_personas.yaml \
     dbfs:/Volumes/<catalog>/<schema>/<volume>/config/test_personas.yaml --overwrite
   ```

   It is picked up within ~30s. Delete the file to fall back to the bundled
   list. If the app can't read the file (e.g. a missing volume permission),
   the backend logs a warning and uses the bundled list.

From curl or other clients, call the app URL and authenticate to Databricks
as usual, in addition to the `X-Test-*` headers:

```bash
curl -H "Authorization: Bearer $(databricks auth token | jq -r .access_token)" \
     -H "X-Test-Token: <your-token>" \
     -H "X-Test-User-Email: producer@test.local" \
     https://<your-app-url>/api/user/details
```

#### Header reference

- `X-Test-User-Email` is required when `X-Test-Token` matches.
- `X-Test-User-Groups` is optional (JSON array or comma-separated). When it
  is omitted, the backend falls back to a real SCIM lookup, so the persona
  reflects actual workspace state.
- Optional refinement headers: `X-Test-User-Username`, `X-Test-User-Name`,
  `X-Test-User-Ip`.

#### Notes

- The server never returns the token itself. `GET /api/test/personas`
  returns header names, not the token.
- This mechanism is complementary to the env-based `MOCK_USER_*` variables
  (which require restarts) and to the in-process FastAPI
  `app.dependency_overrides[get_user_details_from_sdk]` pattern used by most
  integration tests.

See `src/backend/src/tests/integration/test_user_header_override.py` for
worked examples.

---

## License

By contributing to Ontos, you agree that your contributions will be licensed under the project's license (see LICENSE.txt).

---

## Supply Chain Security

This project follows GitHub Actions supply chain security best practices as required for `databrickslabs` repos.

### Action Pinning

All GitHub Actions in `.github/workflows/` must be pinned to full SHA commits with a version comment:

```yaml
# Correct
uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4

# Incorrect
uses: actions/checkout@v4
```

Dependabot (`.github/dependabot.yml`) will automatically open PRs when new action versions are available.

### Python Dependency Pinning

Python dependencies use a two-file pattern:

- `requirements.in` - Source constraint files with version ranges (what you edit)
- `requirements.txt` - Locked files with exact versions and hashes (what CI installs)

To regenerate locked files after updating `.in` files:

```bash
./scripts/lock-requirements.sh
```

This requires [uv](https://github.com/astral-sh/uv) and PyPI access. The script runs `uv pip compile --generate-hashes` for all three requirement sets (`src/`, `src/backend/`, `src/e2e/`).

### Alembic Migration Heads

The database migration history under `src/backend/alembic/versions/` must always
have **exactly one head**. Two PRs that branch off the same Alembic tip and each
add a sibling revision will leave `main` with multiple heads, and app startup
will crash in `init_db` with `script directory has multiple heads`.

CI enforces this via the **Alembic Single-Head Check** job in
`.github/workflows/test-coverage.yml`. On every PR it runs
`scripts/check-alembic-heads.py`, which:

1. Loads the PR's `versions/` tree and fails if `alembic heads` returns more
   than one head.
2. Fails if any newly added revision's `down_revision` is not reachable from
   the PR base branch's tip — i.e. you forgot to rebase before authoring the
   migration.

**Remediation when the check fails:**

- Rebase your branch onto the current base, drop your revision file, and
  re-run `alembic revision -m '<message>'` so the new revision descends from
  the live head.
- Or, if a merge revision is the right call (your branch and another both
  shipped migrations independently), run
  `alembic merge -m 'merge heads' <head_a> <head_b>` and commit the resulting
  file.

**Escape hatch:** Apply the `alembic-branch` label to the PR to bypass the
check. Use this only when the multi-head state is intentional and a merge
revision is planned in the same PR.

### Workflow Permissions

All workflows must declare a minimal `permissions` block at the workflow level:

```yaml
permissions:
  contents: read
```

Only add additional permissions (e.g., `issues: write`) if the workflow genuinely requires them.

When jobs need more (e.g. `id-token: write` for JFrog, `contents: write` to push), grant it on
those jobs only, not at the workflow level, so the other jobs stay read-only.

### CI for Pull Requests from Forks

CI installs all dependencies through JFrog, authenticated with a GitHub OIDC token. GitHub issues
no OIDC token to `pull_request` runs from forks, so on a fork PR every job fails in the JFrog
auth step before running any code. This is expected and is not a test failure.

To run CI for a fork PR, a maintainer with push access:

1. Reviews the whole PR. The mirrored code runs on the protected runners with this repository's
   CI credentials: every job can request the JFrog OIDC token (`id-token: write`), and the lockfile
   job also has `LOCKFILE_BOT_TOKEN` and write access to the repository contents and pull requests.
   Test code, `conftest.py` files and build scripts run with those credentials too.
2. Runs `scripts/fork-sync-pr.sh <PR_NUMBER> <REVIEWED_SHA>`, passing the full 40-character SHA of
   the head commit that was reviewed (for example
   `scripts/fork-sync-pr.sh 978 3f2a9c1e5b7d4a6c8e0f1a2b3c4d5e6f7a8b9c0d`). The script pushes
   that commit to `fork-test/pr-<N>` and opens a `do-not-merge` mirror PR where CI runs normally.
   It refuses to run if the fork PR has new commits since the review.
3. If the PR changes CI or dependency files (`.github/`, `scripts/`, `src/scripts/`,
   `.pre-commit-config.yaml`, `pyproject.toml`, `requirements*`, `package.json`,
   `package-lock.json`, `.npmrc`, lockfiles), the script lists them and stops. Those files decide
   what runs with the credentials, so review them line by line, then run the script again with
   `--allow-sensitive-paths`.
4. Re-runs the script with the new SHA after each update to the fork PR, and closes the mirror PR
   (deleting its branch) once the original PR is merged or closed.

The `do-not-merge` check fails while a PR has the `do-not-merge` label, so a mirror PR can't be
merged by mistake once that check is required in the `development` ruleset.

Contributors from forks: run the backend and frontend checks from
[Pre-commit Checks](#pre-commit-checks) locally and mention the results in the PR.

---

## Questions?

- Open an issue for bugs or feature requests
- Start a discussion for questions or ideas
- Check existing issues before creating new ones

Thank you for contributing to Ontos! 🎉

