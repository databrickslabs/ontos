# Codebase Structure

**Analysis Date:** 2026-03-11

## Directory Layout

```
ucapp/
├── src/
│   ├── backend/
│   │   ├── src/
│   │   │   ├── app.py                      # FastAPI application entry point
│   │   │   ├── routes/                     # API route handlers (40+ route modules)
│   │   │   ├── controller/                 # Manager classes (49 managers)
│   │   │   ├── repositories/               # Data access layer (repository pattern)
│   │   │   ├── models/                     # Pydantic API models
│   │   │   ├── db_models/                  # SQLAlchemy database models
│   │   │   ├── common/                     # Cross-cutting utilities (40+ modules)
│   │   │   ├── workflows/                  # Databricks workflow/job definitions (12+ workflows)
│   │   │   ├── data/                       # Demo data, taxonomies, schemas
│   │   │   ├── tests/                      # Unit & integration tests
│   │   │   ├── schemas/                    # JSON schemas (validation)
│   │   │   ├── connectors/                 # External system connectors
│   │   │   ├── tools/                      # Utility scripts and tools
│   │   │   ├── file_models/                # File-based model definitions
│   │   │   └── utils/                      # Startup tasks, utilities
│   │   ├── app.yaml                        # Databricks App configuration
│   │   └── pyproject.toml                  # Python dependencies, hatch config
│   └── frontend/
│       ├── src/
│       │   ├── app.tsx                     # React app root component
│       │   ├── views/                      # Page-level components (40+ views)
│       │   ├── components/                 # Reusable UI components (feature-grouped)
│       │   │   ├── ui/                     # Base Shadcn UI components
│       │   │   ├── common/                 # App-specific common components
│       │   │   ├── layout/                 # Navigation, sidebar, header
│       │   │   └── [feature]/               # Feature-specific components (data-products/, compliance/, etc.)
│       │   ├── stores/                     # Zustand global state (14+ stores)
│       │   ├── hooks/                      # Custom React hooks
│       │   ├── types/                      # TypeScript type definitions
│       │   ├── utils/                      # Utility functions
│       │   ├── config/                     # Feature flags, configuration
│       │   ├── lib/                        # Library functions
│       │   ├── i18n/                       # Internationalization
│       │   └── tests/                      # React component tests
│       ├── index.html                      # HTML entry point
│       ├── vite.config.ts                  # Vite build configuration
│       ├── tailwind.config.js              # Tailwind CSS configuration
│       ├── tsconfig.json                   # TypeScript configuration
│       └── package.json                    # Node dependencies
├── docs/                                   # Project documentation
│   └── user-journeys/                      # User journey documentation
├── .planning/codebase/                     # GSD analysis documents (THIS FOLDER)
└── .github/workflows/                      # CI/CD workflows
```

## Directory Purposes

**`src/backend/src/`** (Main backend source)
- Purpose: Implement FastAPI application with RORO pattern and manager/repository abstraction
- Contains: Python source code, database models, API schemas, Pydantic validators
- Key files: `app.py` (server entry), 40+ route modules, 49 manager classes

**`src/backend/src/routes/`** (HTTP API Endpoints)
- Purpose: FastAPI routers exposing HTTP endpoints grouped by feature
- Contains: One route module per feature (e.g., `data_product_routes.py`, `compliance_routes.py`)
- Pattern: Each imports a Manager, uses FastAPI's dependency injection for auth/DB
- Examples: `data_product_routes.py`, `data_contracts_routes.py`, `search_routes.py`

**`src/backend/src/controller/`** (Business Logic)
- Purpose: Manager classes implementing domain logic, coordinating repositories and services
- Contains: 49 manager classes (some pairs with `_manager.py` suffix)
- Examples: `DataProductsManager`, `DataContractsManager`, `ComplianceManager`, `SearchManager`
- Pattern: Each manager handles one feature domain; many implement `SearchableAsset` for indexing

**`src/backend/src/repositories/`** (Data Access Layer)
- Purpose: Abstract database operations, map between API (Pydantic) and DB (SQLAlchemy) models
- Contains: One repository per entity type
- Pattern: Each class extends `CRUDBase[DBModel, CreateModel, UpdateModel]` generic base
- Examples: `DataProductRepository`, `DataContractRepository`, `ComplianceRepository`

**`src/backend/src/models/`** (Pydantic API Models)
- Purpose: Define request/response schema for API, validate inputs
- Contains: One Pydantic model file per feature
- Pattern: Classes with `Create`, `Update`, `Response` suffixes (RORO pattern)
- Examples: `data_products.py` (has `DataProductCreate`, `DataProductUpdate`, `DataProduct`), `compliance.py`
- Key: ODPS-compliant structure (`apiVersion`, `kind`, `spec`, `status`) with Databricks extensions

**`src/backend/src/db_models/`** (SQLAlchemy Database Models)
- Purpose: Define database table schemas and relationships
- Contains: One file per table or table group
- Pattern: Classes extending SQLAlchemy Base, with `__tablename__` and column definitions
- Examples: `data_products.py`, `data_contracts.py`, `compliance.py`

**`src/backend/src/common/`** (Cross-Cutting Utilities)
- Purpose: Shared utilities, configuration, middleware, authorization
- Contains: 40+ utility modules
- Key modules:
  - `database.py` — Session factory, DB initialization
  - `config.py` — Settings loader (Pydantic BaseSettings)
  - `authorization.py` — Permission checking, user fetching from Databricks SDK
  - `dependencies.py` — FastAPI dependency providers (managers, sessions, users)
  - `middleware.py` — Logging, error handling middleware
  - `search_interfaces.py` — `SearchableAsset` interface
  - `search_registry.py` — `@searchable_asset` decorator, manager registry
  - `logging.py` — Structured logger setup
  - `workspace_client.py` — Databricks SDK client instantiation

**`src/backend/src/workflows/`** (Databricks Jobs/Workflows)
- Purpose: Define long-running or scheduled tasks (separate from API)
- Contains: 12+ workflow definitions, each in its own directory
- Examples: `compliance_checks/`, `data_quality_checks/`, `data_product_sync/`
- Pattern: Each workflow has its own `task.py` (Databricks task) and optional config

**`src/backend/src/data/`** (Demo Data & Static Config)
- Purpose: Store seed data, demo fixtures, ontology definitions
- Contains:
  - `taxonomies/` — RDF ontologies (e.g., `ontos-ontology.ttl`)
  - Demo data files: one self-contained pack per preset, named `demo_data_{preset}.sql`
    (presets: `retail` (default), `hls`, `fsi`, `mfg`, `auto`).
    Loaded via `POST /api/settings/demo-data/load?preset=<name>`.

**`src/backend/src/tests/`** (Test Suite)
- Purpose: Unit and integration tests
- Contains:
  - `unit/` — Unit tests for individual functions/classes
  - `integration/` — Full API endpoint tests
  - `data/` — Test fixtures
- Pattern: pytest-based; one test file per feature (e.g., `test_data_products_routes.py`)

**`src/frontend/src/`** (React Application)
- Purpose: Single-page application for user interface
- Contains: React components, stores, hooks, types, utilities

**`src/frontend/src/views/`** (Page-Level Components)
- Purpose: Full page components corresponding to routes
- Contains: 40+ view components (one per major feature)
- Examples: `data-products.tsx`, `data-contracts.tsx`, `compliance.tsx`, `settings-general.tsx`
- Pattern: Import feature-specific components and layout components; manage page-level state

**`src/frontend/src/components/`** (Reusable Components)
- Purpose: Reusable UI components organized by feature and type
- Contains: 30+ subdirectories
- Structure:
  - `ui/` — Base Shadcn UI components (button, dialog, form, etc.)
  - `common/` — App-specific common components (RelativeDate, UserInfo, etc.)
  - `layout/` — Navigation (sidebar, header, breadcrumbs)
  - `[feature]/` — Feature-specific components (e.g., `data-products/`, `compliance/`, `concepts/`)
- Pattern: Each feature may have multiple components (list, form, detail, card, etc.)

**`src/frontend/src/stores/`** (Global State - Zustand)
- Purpose: Centralized state management for cross-component concerns
- Contains: 14+ Zustand stores
- Examples:
  - `permissions-store.ts` — User permissions, role overrides
  - `user-store.ts` — Current user info
  - `notifications-store.ts` — Toast notifications
  - `copilot-store.ts` — Copilot conversation state
  - `breadcrumb-store.ts` — Page breadcrumb navigation
- Pattern: Create stores with `create()`, expose via `useStore()` hook

**`src/frontend/src/hooks/`** (Custom React Hooks)
- Purpose: Reusable hook logic
- Contains: 15+ custom hooks
- Examples:
  - `use-api.ts` — Wraps fetch with error/loading handling
  - `use-comments.ts` — Comment management
  - `use-toast.ts` — Toast notifications
  - `use-domains.ts` — Domain list fetching
- Pattern: Each hook manages a specific data flow or interaction

**`src/frontend/src/types/`** (TypeScript Type Definitions)
- Purpose: Define interfaces/types for API responses, components
- Contains: One file per feature domain
- Examples: `data-product.ts`, `settings.ts`, `compliance.ts`

## Key File Locations

**Entry Points:**
- Backend: `src/backend/src/app.py` — FastAPI application bootstrap
- Frontend: `src/frontend/src/app.tsx` — React app root and routing
- Frontend HTML: `src/frontend/index.html` — DOM anchor point

**Configuration:**
- Backend settings: `src/backend/src/common/config.py` — Pydantic BaseSettings (loads `.env`)
- Frontend config: `src/frontend/src/config/features.ts` — Feature flags
- Database: `src/backend/src/common/database.py` — Session factory and models
- Build (Frontend): `src/frontend/vite.config.ts`, `src/frontend/tailwind.config.js`
- Build (Backend): `src/backend/pyproject.toml` — Hatch configuration
- Build (App): `src/backend/app.yaml` — Databricks App Bundle format

**Core Logic:**
- Data Products: `src/backend/src/controller/data_products_manager.py`, `src/backend/src/models/data_products.py`
- Data Contracts: `src/backend/src/controller/data_contracts_manager.py`, `src/backend/src/models/data_contracts.py`
- Search: `src/backend/src/controller/search_manager.py`, `src/backend/src/models/search.py`
- Compliance: `src/backend/src/controller/compliance_manager.py`, `src/backend/src/models/compliance.py`
- Authentication/Authorization: `src/backend/src/common/authorization.py`

**Testing:**
- Backend tests: `src/backend/src/tests/integration/test_data_product_routes.py` (example)
- Frontend tests: `src/frontend/src/**/*.test.tsx` (Playwright-based)
- Test config: `src/backend/pyproject.toml` (pytest config)

## Naming Conventions

**Files:**

**Backend Python:**
- Routes: `{feature}_routes.py` (e.g., `data_product_routes.py`)
- Managers: `{feature}_manager.py` (e.g., `data_products_manager.py`)
- Repositories: `{entity}_repository.py` (e.g., `data_products_repository.py`)
- Models (API): `{entity}.py` (e.g., `data_products.py`)
- Models (DB): `{entity}.py` (e.g., `data_products.py`)
- Tests: `test_{module}_routes.py` or `test_{module}_repository.py`
- Utilities: `{utility_name}.py` (e.g., `workspace_client.py`)

**Frontend TypeScript:**
- Views: `{view-name}.tsx` (e.g., `data-products.tsx`, `data-product-details.tsx`)
- Components: `{component-name}.tsx` (e.g., `data-product-form.tsx`)
- Stores: `{store-name}-store.ts` (e.g., `permissions-store.ts`)
- Hooks: `use-{hook-name}.ts` (e.g., `use-api.ts`, `use-comments.ts`)
- Types: `{entity-name}.ts` (e.g., `data-product.ts`)
- Utils: `{utility-name}.ts` (e.g., `utils.ts`, `api.ts`)

**Directories:**

**Backend:**
- Pluralized: `routes/`, `models/`, `repositories/`, `db_models/`, `workflows/`
- Singular: `controller/`, `common/`, `utils/`, `data/`

**Frontend:**
- Pluralized: `views/`, `components/`, `stores/`, `hooks/`, `types/`, `utils/`, `tests/`
- Singular: `lib/`, `config/`, `context/`
- Feature-grouped components: `components/{feature-name}/` (hyphenated, plural)

## Where to Add New Code

**New Feature (Full Feature Lifecycle):**
1. **Database schema:** `src/backend/src/db_models/{entity}.py` (SQLAlchemy model)
2. **API models:** `src/backend/src/models/{entity}.py` (Pydantic models with Create/Update/Response)
3. **Repository:** `src/backend/src/repositories/{entity}_repository.py` (extends CRUDBase)
4. **Manager:** `src/backend/src/controller/{entity}_manager.py` (business logic, optionally implement SearchableAsset)
5. **Routes:** `src/backend/src/routes/{entity}_routes.py` (FastAPI endpoints, register in `app.py`)
6. **Frontend types:** `src/frontend/src/types/{entity}.ts` (TypeScript interfaces)
7. **Frontend views:** `src/frontend/src/views/{entity}.tsx` (page component)
8. **Frontend components:** `src/frontend/src/components/{entity}/` directory (create form, list, detail components)
9. **Tests:** `src/backend/src/tests/integration/test_{entity}_routes.py` (API tests)

**New Component/Module (UI Only):**
- Implementation: `src/frontend/src/components/{feature}/{component-name}.tsx`
- Use existing patterns (Shadcn UI + Tailwind, react-hook-form for forms)

**New Utility Function:**
- Backend: `src/backend/src/common/{utility_name}.py` or `src/backend/src/utils/{utility_name}.py`
- Frontend: `src/frontend/src/lib/` or `src/frontend/src/utils/`

**New API Endpoint:**
- Add method to Manager class: `src/backend/src/controller/{manager}.py`
- Add route in corresponding route file: `src/backend/src/routes/{feature}_routes.py`
- Register route in `app.py` if new router: `{feature}_routes.register_routes(app)`

**New Permission/Feature:**
- Define in: `src/backend/src/common/features.py` (add FeatureAccessLevel enum entry)
- Use in route: `@router.post(..., dependencies=[Depends(PermissionChecker('feature-id', FeatureAccessLevel.READ_WRITE))])`
- Check in UI: `hasPermission('feature-id', FeatureAccessLevel.READ_WRITE)` from `permissions-store`

## Special Directories

**`src/backend/src/workflows/`** (Generated/Managed)
- Purpose: Databricks Workflow/Job definitions
- Generated: Partially (managed by SettingsManager; users create via UI)
- Committed: Yes (stored as task.py and config files)
- Examples: `compliance_checks/`, `data_quality_checks/`, `data_product_sync/`

**`src/frontend/src/components/ui/`** (Generated/Third-Party)
- Purpose: Shadcn UI components (generated via CLI)
- Generated: Yes (via `npx shadcn-ui add`)
- Committed: Yes (checked in as source)
- Purpose: Base components (Button, Dialog, Form, Input, etc.)

**`src/backend/src/data/`** (Static Content)
- Purpose: Demo data, ontologies, seed data
- Generated: No (hand-curated)
- Committed: Yes
- Examples: `taxonomies/ontos-ontology.ttl`, demo data YAML files

**`.planning/codebase/`** (GSD Analysis - THIS FOLDER)
- Purpose: Codebase analysis documents for GSD planner/executor
- Generated: By gsd:map-codebase command
- Committed: Yes
- Files: ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md, STACK.md, INTEGRATIONS.md, CONCERNS.md

---

*Structure analysis: 2026-03-11*
