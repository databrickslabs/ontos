# Ontos E2E API Tests

End-to-end tests that exercise the Ontos REST API against a running instance (local or deployed as a Databricks App).

## Prerequisites

- Python 3.11+
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) installed and authenticated (`databricks auth login`)
- A running Ontos instance (local dev server **or** a deployed Databricks App)

## Setup

```bash
cd src/e2e
pip install -r requirements.txt
```

## Configuration

All settings live in **`config.yaml`** (checked into git, shared defaults).
To override for your environment, create **`config.local.yaml`** (gitignored) with only the keys you need:

```yaml
# config.local.yaml
base_url: "https://my-ontos-app-1234567890.aws.databricksapps.com"
databricks:
  host: "https://my-workspace.cloud.databricks.com"
  profile: "MY_PROFILE"
```

Environment variables take the highest priority and override both files:

| Variable              | Description                                        |
|-----------------------|----------------------------------------------------|
| `E2E_BASE_URL`        | Base URL of the Ontos instance to test              |
| `DATABRICKS_HOST`     | Databricks workspace URL (for token generation)     |
| `DATABRICKS_PROFILE`  | Databricks CLI profile name (default: `DEFAULT`)    |
| `E2E_DATABRICKS_TOKEN`| Skip CLI auth and use this token directly (for CI)  |

**Precedence:** env vars > `config.local.yaml` > `config.yaml`

## Running locally

Start the Ontos backend dev server first (from the project root):

```bash
# Terminal 1 - start the backend
cd src && hatch -e dev run uvicorn backend.src.app:app --reload --port 8000
```

Then, in `config.local.yaml` (or leave the default):

```yaml
base_url: "http://localhost:8000"
```

Run the tests:

```bash
cd src/e2e

# Run all tests
pytest

# Run only smoke / health-check tests
pytest -m smoke

# Run only read-only (safe) tests
pytest -m readonly

# Run a specific test file
pytest tests/test_00_health.py -v

# Run with verbose output
pytest -v --tb=short
```

## Running against a Databricks App deployment

1. Deploy Ontos as a Databricks App (see project root docs).

2. Create `config.local.yaml`:

```yaml
base_url: "https://<app-name>-<workspace-id>.<cloud>.databricksapps.com"
databricks:
  host: "https://<workspace-url>.cloud.databricks.com"
  profile: "DEFAULT"
```

3. Make sure you're authenticated with the Databricks CLI:

```bash
databricks auth login --host https://<workspace-url>.cloud.databricks.com
```

4. Run the tests:

```bash
cd src/e2e
pytest -v
```

## CI / Service Principal

For CI pipelines where the Databricks CLI is not available, set `E2E_DATABRICKS_TOKEN` directly:

```bash
export E2E_BASE_URL="https://my-app.databricksapps.com"
export E2E_DATABRICKS_TOKEN="dapi..."
pytest
```

## Test markers

Tests are tagged with pytest markers so you can run subsets:

| Marker        | Description                                               |
|---------------|-----------------------------------------------------------|
| `smoke`       | Quick connectivity and health checks                      |
| `readonly`    | Tests that only read data (safe to run anytime)            |
| `crud`        | Tests that create, modify, and delete data                 |
| `slow`        | Tests that may take longer (profiling, jobs)                |
| `destructive` | Tests that affect external resources (skipped by default)   |
| `lifecycle`   | Tests for status transitions, approval flows, clone/commit  |

Example:

```bash
# Run everything except destructive tests
pytest -m "not destructive"

# Run only smoke + readonly
pytest -m "smoke or readonly"
```

## Test file naming

Test files are numbered to control execution order (pytest runs them alphabetically):

- `test_00_health.py` - Health / connectivity checks (run first)
- `test_01_user.py` through `test_26_*` - Feature-specific CRUD tests
- `test_30_*` and above - Cross-cutting workflows and advanced scenarios

## Project structure

```
src/e2e/
  config.yaml          # Default configuration (committed)
  config.local.yaml    # Your local overrides (gitignored)
  conftest.py          # Auth + session fixtures
  pytest.ini           # Pytest settings and markers
  requirements.txt     # Python dependencies
  helpers/
    assertions.py      # Custom assertion helpers
    test_data.py       # Shared test data fixtures
  tests/
    test_00_health.py  # ... through test_36_*.py
```
