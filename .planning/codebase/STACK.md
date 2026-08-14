# Technology Stack

**Analysis Date:** 2026-03-11

## Languages

**Primary:**
- Python 3.11 - Backend API and business logic (`src/backend/src/`)
- TypeScript 5.3 - Frontend application and UI components (`src/frontend/src/`)

**Supporting:**
- YAML 6.0+ - Configuration files, workflows, app manifests
- HTML5 / CSS3 - Templates and styling
- RDF/Turtle - Semantic ontology definitions (`src/backend/src/data/taxonomies/`)

## Runtime

**Environment:**
- Python 3.11.x (requires >=3.11,<3.13 per `pyproject.toml`)
- Node.js 18+ (`"engines": {"node": ">=18"}` in `package.json`)

**Package Managers:**
- Python: `pip` with `hatch` build system
- Node.js: `npm` (project uses npm exclusively)
- Lockfile: `package-lock.json` for frontend, `requirements.txt` pinned for backend

## Frameworks

**Core:**
- FastAPI 0.110.2+ - REST API framework, async Python web server
- React 18.2 - Frontend UI framework
- Uvicorn 0.32.0+ - ASGI server for FastAPI

**Build/Dev:**
- Vite 6.2.4 - Frontend build tool (configured in `src/frontend/vite.config.ts`)
- Hatch - Python package manager and test runner (`pyproject.toml`)
- Alembic 1.11.1+ - Database migrations

**UI Library:**
- Shadcn UI - Component library built on Radix UI primitives
- Tailwind CSS 3.4.1 - Utility-first CSS framework
- Radix UI - Unstyled, accessible component primitives

**Form/Validation:**
- React Hook Form 7.56.1 - Form state management
- Zod 3.24.3 - TypeScript-first schema validation
- Pydantic 1.8-2.8 - Python data validation and settings management
- Pydantic Settings 2.2.1 - Settings management with environment support

**Testing:**
- Vitest 3.2.4 - Unit/component testing (TypeScript)
- Jest/React Testing Library - Component testing utilities
- Playwright 1.55.0+ - E2E testing (`src/frontend/src/tests/`)
- Pytest 7.0+ - Unit testing (Python backend)
- Pytest-cov 4.0+ - Coverage reporting

**Database/ORM:**
- SQLAlchemy 1.4-2.1 - SQL toolkit and ORM for Python
- Alembic 1.11.1+ - Database migration tool

**Linting/Formatting:**
- Ruff 0.8.0+ - Python linter and formatter
- ESLint 9.39.2 - JavaScript/TypeScript linting
- Prettier 3.8.1 - Code formatter (JavaScript/TypeScript)
- TypeScript 5.3.3 - Type checking (`tsc --noEmit`)

## Key Dependencies

**Critical:**

- `databricks-sdk>=0.60.0` - Databricks Python SDK for workspace operations, Unity Catalog access
- `databricks-sql-connector>=4.0.0` - SQL connector for Databricks warehouses
- `databricks-sqlalchemy>=2.0.0` - SQLAlchemy dialect for Databricks SQL

**Infrastructure & Data Access:**

- `sqlalchemy>=1.4,<2.1` - ORM and database layer
- `psycopg2-binary>=2.9.10` - PostgreSQL adapter (for metadata database)
- `pyarrow>=21.0.0` - Arrow format support for data interchange
- `pandas>=2.1.0` - Data manipulation and analysis
- `numpy>=2.2.2` - Numerical computing

**Semantic & Knowledge Graphs:**

- `rdflib>=7.1.0` - RDF/OWL/SKOS graph processing (ontology handling)
- `jsonschema>=4.22.0` - JSON schema validation (for ODCS/ODPS contracts)

**External Services & APIs:**

- `requests>=2.31.0` - HTTP client library
- `openai>=2.4.0` - OpenAI API client (for LLM features - optional, see `LLM_ENABLED`)
- `google-cloud-bigquery>=3.25.0` - Google BigQuery connector
- `GitPython>=3.1.44` - Git operations for configuration sync

**ML & Analytics:**

- `mlflow>=3.4.0` - ML experiment tracking and model registry integration

**Server & Async:**

- `python-multipart>=0.0.19` - File upload handling for FastAPI
- `sse-starlette>=1.6.0,<2.0.0` - Server-Sent Events for real-time streams
- `flask-cors>=5.0.0` - CORS middleware

**Configuration & Logging:**

- `python-dotenv>=1.0.1` - Environment variable loading from `.env`
- `pyyaml>=6.0.1` - YAML parsing and generation
- `werkzeug>=3.0.1` - Utilities for WSGI and HTTP

**Security:**

- `bcrypt>=4.0.0` - Password hashing
- `bleach>=6.0.0` - HTML sanitization

**Utilities:**

- `filelock>=3.13.0` - Cross-platform file locking
- `typing-extensions>=4.9.0` - Backports of typing features
- `python-dateutil>=2.8.2` - Date/time utilities
- `pytz>=2025.1` - Timezone database
- `six>=1.16.0` - Python 2/3 compatibility
- `reportlab>=4.0.0` - PDF generation
- `openpyxl>=3.1.0` - Excel workbook creation
- `pip-licenses>=5.1.0` - License compliance reporting

**Frontend Libraries:**

- React Router DOM 6.22.0 - Client-side routing
- React Markdown 10.1.0 - Markdown rendering
- React Syntax Highlighter 15.6.1 - Code block highlighting
- Recharts 2.15.1 - Charts and visualization
- Cytoscape 3.33.1 - Graph/network visualization (via react-cytoscapejs)
- Reactflow 11.11.4 - Node-based diagram builder
- Framer Motion 12.6.3 - Animation library
- Zustand 5.0.3 - Lightweight state management
- i18next 25.5.3 - Internationalization framework
- Clsx 2.1.1 - Conditional className utility
- Tailwind Merge 3.1.0 - Merge Tailwind classes safely
- Date-fns 4.1.0 - Date utility library
- AJV 8.17.1 - JSON Schema validator
- Lucide React 0.487.0 - Icon library

**Build/Dev-only:**

- @vitejs/plugin-react 4.3.4 - React Fast Refresh plugin for Vite
- @types/node, @types/react, @types/react-dom - TypeScript type definitions
- @vitest/ui 3.2.4 - Test UI dashboard
- @vitest/coverage-v8 3.2.4 - Coverage reporting
- @playwright/test 1.55.0 - Playwright test framework
- @testing-library/react 16.3.0 - React component testing utilities
- @testing-library/jest-dom 6.8.0 - DOM matchers
- dagre 0.8.5 - Graph layout library
- jsdom 27.0.0 - DOM implementation for Node.js
- license-checker 25.0.1 - License compliance checker

## Configuration

**Environment Variables:**
- `.env` file (required for local development) - connection strings, credentials, feature flags
- Example template: `.env.example` in `src/backend/` with all documented options
- Key vars: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `POSTGRES_HOST/PORT/USER/PASSWORD/DB`, `LLM_ENABLED`, `LLM_ENDPOINT`
- See `src/backend/src/common/config.py` for Settings model parsing

**Build Configuration:**
- `src/pyproject.toml` - Python project metadata, dependencies, test/lint config
- `src/frontend/package.json` - Node.js dependencies, scripts, version
- `src/frontend/tsconfig.json` - TypeScript compiler options (target ES2020, strict mode)
- `src/frontend/vite.config.ts` - Build pipeline, dev server port 3000, static output
- `src/frontend/tailwind.config.cjs` - Tailwind CSS customization
- `src/frontend/vitest.config.ts` - Unit test configuration
- `src/frontend/playwright.config.ts` - E2E test configuration
- `src/backend/requirements.txt` - Pinned Python dependencies

**Application Configuration:**
- `src/app.yaml` - Databricks App manifest (Asset Bundle format)
  - Command: `['python', 'backend/src/app.py']`
  - Environment: Databricks-injected vars (PGHOST, PGPORT, PGUSER, PGDATABASE)
  - Features: LLM_ENABLED, SQL_WAREHOUSE_ID, Databricks VOLUME binding

**Linting/Formatting:**
- Ruff config in `pyproject.toml`: target 0.5.4, line-length 100, isort rules
- ESLint config: `src/frontend/eslint.config.js` with TypeScript, React, React Hooks rules
- Prettier config: `src/frontend/.prettierrc` for consistent formatting

## Platform Requirements

**Development:**
- Python 3.11.x (macOS/Linux/Windows)
- Node.js 18+ with npm package manager
- Git (for repository operations and optional Git sync feature)
- PostgreSQL 9.6+ or compatible (for metadata storage)
- Databricks workspace account with Unity Catalog enabled
- Databricks Personal Access Token (for local testing)
- (Optional) Databricks SQL Warehouse for query execution
- (Optional) Google Cloud credentials for BigQuery connector

**Production:**
- Deployment target: Databricks Apps platform (serverless container runtime)
- Requires: Databricks workspace, Unity Catalog, SQL warehouse
- Frontend: Static files served from backend (Vite build output → `src/backend/static/`)
- Database: PostgreSQL or Databricks SQL (via JDBC/connection string)
- Runtime: Python 3.11 in Databricks App container
- Optional: Google Cloud access (for BigQuery integration), GitHub credentials (for Git sync)

## Build & Deployment

**Development Build:**
```bash
# Frontend: Vite dev server on port 3000
npm run dev:frontend

# Backend: Uvicorn with auto-reload on port 8000
hatch -e dev run dev-backend

# Both together (if scripts available)
npm run build  # Builds frontend static + copies to backend
```

**Production Build:**
```bash
# Frontend production build (outputs to src/frontend/static/)
npm run build

# Python package build via Hatch
hatch build

# Databricks deployment
databricks bundle deploy --var="catalog=app_data" --var="schema=app_ontos"
```

---

*Stack analysis: 2026-03-11*
