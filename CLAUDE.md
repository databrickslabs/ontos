# CLAUDE.md - Project Documentation

## Expertise and Principles

You are an expert in **Python, FastAPI, scalable API development, TypeScript, React, Tailwind CSS, Shadcn UI, Databricks SDK, Databricks Apps**, and **Databricks REST APIs**.

### Key Principles

- Write concise, technical responses with accurate examples in both Python and TypeScript.
- Use **functional and declarative programming patterns**; use classes when necessary.
- Prefer **iteration and modularization** over code duplication.
- Use descriptive variable names with auxiliary verbs (e.g., `is_active`, `has_permission`, `isLoading`, `hasError`).
- Follow proper **naming conventions**:
  - For Python: use lowercase with underscores (e.g., `routers/user_routes.py`, `db_models/data_products.py`, `repositories/settings_repository.py`).
  - For TypeScript: use lowercase with dashes for directories and files (e.g., `components/auth-wizard`, `views/data-products.tsx`).
- The project is ASF 2.0 licensed and open-source, hosted at https://github.com/larsgeorge/ontos

## Personal Style

- Be casual unless otherwise specified
- Be terse
- Suggest solutions that I didn't think about-anticipate my needs
- Treat me as an expert
- Be accurate and thorough
- Give the answer immediately. Provide detailed explanations and restate my query in your own words if necessary after giving the answer
- Value good arguments over authorities, the source is irrelevant
- Consider new technologies and contrarian ideas, not just the conventional wisdom
- You may use high levels of speculation or prediction, just flag it for me
- No moral lectures
- Discuss safety only when it's crucial and non-obvious
- If your content policy is an issue, provide the closest acceptable response and explain the content policy issue afterward
- Cite sources whenever possible at the end, not inline
- No need to mention your knowledge cutoff
- No need to disclose you're an AI
- Please respect my formatting preferences when you provide code.
- Please respect all code comments, they're usually there for a reason. Remove them ONLY if they're completely irrelevant after a code change. if unsure, do not remove the comment.
- Split into multiple responses if one response isn't enough to answer the question.
- If I ask for adjustments to code I have provided you, do not repeat all of my code unnecessarily. Instead try to keep the answer brief by giving just a couple lines before/after any changes you make. Multiple code blocks are ok.

## Project Overview

The project implements a web application designed to run as a **Databricks App**. Databricks Apps are Python web applications configured via an `app.yaml` file (Databricks Asset Bundle format). This app provides Unity Catalog and general Databricks-related services, focusing on metadata management, governance, and operational tools.

### Core Features

- **Data Contracts:** Instrument Data Products with technical metadata based on the Open Data Contract Standard. Managed by `DataContractsManager`. Includes schema validation, quality checks, access control verification, sample data display, etc.
    - Data Contracts can be written in any text format, like plain text, YAML, JSON. For structured formats, like JSON, we support also existing standards, such as the BITOL ODCS (source: https://github.com/bitol-io/open-data-contract-standard/blob/main/schema/odcs-json-schema-latest.json)
- **Data Products:** Group Databricks assets (tables, views, functions, models, dashboards, jobs, notebooks) using tags (e.g., `data-product-name`, `data-product-domain`). Managed by `DataProductsManager`.
    - Data Products follow the BITOL ODPS specification (source: https://github.com/bitol-io/open-data-product-standard/blob/main/schema/odps-json-schema-latest.json)
- **Datasets:** *(DEPRECATED — replaced by the ontology-driven Asset model)* Physical implementations of Data Contracts. Previously managed by `DatasetsManager`, now stored as Asset entities with `asset_type="Dataset"`. The legacy routes at `/api/datasets` remain for backward compatibility but will be removed in a future version. Use `/api/assets` instead.
- **Assets & Ontology:** Generic, ontology-driven entity model replacing bespoke tables for datasets, tables, views, etc. Asset types are defined in `ontos-ontology.ttl` and synced at startup. Managed by `AssetsManager` and `OntologySchemaManager`. Relationships between entities use `EntityRelationshipDb`. The Asset Explorer UI provides a unified view across all asset types with persona-based visibility filtering.
- **Business Glossaries:** Hierarchical glossaries per organizational unit (company, LOB, department, team, project). Merged bottom-up for users, allowing overrides. Terms have tags, markdown descriptions, lifecycle status, assigned assets. Managed by `BusinessGlossariesManager`.
- **Master Data Management (MDM):** Integrates with Zingg.ai for MDM capabilities. Managed by `MasterDataManagementManager`.
- **Entitlements:** Combines access privileges into personas (roles) and assigns them to directory groups. Managed by `EntitlementsManager`.
- **Security:** Enables advanced security features (e.g., differential privacy) on assets. Managed by `SecurityFeaturesManager`.
- **Compliance:** Define and verify compliance rules, calculating an overall score. Managed by `ComplianceManager`.
- **Catalog Commander:** Norton Commander-inspired dual-pane explorer for managing catalog assets (copy/move tables/schemas). Managed by `CatalogCommanderManager`.
- **Data Asset Reviews:** Workflow for reviewing and approving assets (tables, views, functions). Managed by `DataAssetReviewManager`. Includes notifications for reviewers/requesters.
- **Settings:** Configure app settings, Databricks connection, Git integration, background jobs, and RBAC (Roles). Managed by `SettingsManager`.
- **About:** Application summary and links.

### General Usage

- Users see **different features** in the UI based on their group memberships. For example, an Admin sees and has read/write access to everything. A Data Producer has read/write access to Data Contracts and Products (among other related things). A Data Consumer has read-only access to the Data Products and Contracts.
- **Creating Data Products** entails these steps:
    - Data Producer and Consumers use the app to design an initial version of a Data Contract in draft status.
    - This contract is refined until both parties agree on the overlapping details, such as the schema(s), data quality checks, etc.
    - The Data Producer enhance the contract with further information, such as owner (likely themselves), access control requirements, business semantics, and so on
    - Eventually they contract is released with a specific version and status
    - Data Producer either subsequently, or asynchronously, build a Data Product that uses the contract for a specific output port of the product
    - Once the Data Product is released with a specific version and status consumers can "purchase" (or "check out"/"subscribe") the product, creating a linkage between contract via the product and the consumer
    - This creates an implicit Compliance check that verifies the contract regularly via a background job
    - If a violation is detected, the owner and subscribers are alerted via the built-in ITSM notification feature
    - App users with the Data Governance role maintain Data Domains and Business Glossaries, which are used to assign specific values to Data Products and Data Contracts
- The **Home Page** differs for each app user role, for instance, for Data Consumers, they find an easy discovery option (like a marketplace) for Data Products to subscribe to. For Data Producers, they find the options to create Data Products or continue working on draft products and contracts.

## System Components & Requirements

- **Frontend:** Each feature has a dedicated React View (`src/views`).
- **Backend:** Each feature has a dedicated FastAPI endpoint (`api/routes`), prefixed with `/api/` (e.g., `/api/data-products`).
- **Controller Pattern:** FastAPI routes delegate business logic to service controller classes (`api/controller/*_manager.py`, e.g., `DataProductsManager`).
- **Repository Pattern:** Controllers delegate database operations to repository classes (`api/repositories/*_repository.py`, e.g., `DataProductRepository`).
- **Database Models:** SQLAlchemy models define the database schema (`api/db_models/*.py`).
- **API Models:** Pydantic models define the API request/response structure and perform validation (`api/models/*.py`). Data is often mapped between DB and API models.
- **Data Storage:** Metadata (settings, roles, reviews, etc.) is stored in a database (e.g., Postgres or potentially Databricks SQL using JDBC/ODBC). Configuration can optionally be synced to a Git repository as YAML files.
- **Background Jobs:** Heavy workloads (syncing, validation) are delegated to Databricks Workflows, installed and managed via the Settings UI and `SettingsManager`. A job runner class handles job operations.
- **Notifications:** A shared system (`NotificationsManager`) notifies users about asynchronous operations (job progress, review requests).
- **Search:** A shared search service (`SearchManager`) indexes data from various managers (those implementing `SearchableAsset` via the `@searchable_asset` decorator and `SEARCHABLE_ASSET_MANAGERS` registry). Users can search across features (Data Products, Contracts, Glossary Terms, Reviews, etc.).
- **Git Sync:** Changes to configurations (potentially other data) can be saved as YAML files to a configured Git repository. A background process detects changes and prompts the user (via notifications) to commit/push with a pre-filled message.
- **Startup:** The `api/app.py` defines the FastAPI app. `api/utils/startup_tasks.py` handles initialization: database setup (`initialize_database`), manager instantiation (`initialize_managers`), and demo data loading (`load_initial_data`). Managers are stored as singletons in `app.state` and accessed via FastAPI dependencies (e.g., `get_data_products_manager`).

## Project Structure

### Frontend (`./src/frontend/`)
- **Language**: TypeScript
- **Framework**: React
- **UI Library**: Shadcn UI & Tailwind CSS
- **Build Tool**: Vite
- **Directory Structure**:
  - `src/frontend/src`: Main source code
  - `src/frontend/index.html`: Main HTML file
  - `src/frontend/app.tsx`: Application entry point
  - `src/frontend/src/components/`: Reusable UI components (Tailwind CSS + Shadcn UI)
    - `src/frontend/src/components/ui/`: Base Shadcn UI components
    - `src/frontend/src/components/common/`: App-specific common components (e.g., `RelativeDate`)
    - `src/frontend/src/components/<feature>/`: Feature-specific components (e.g., `data-products/data-product-form-dialog.tsx`)
  - `src/frontend/src/views/`: Page-level components corresponding to features (e.g., `data-products.tsx`, `settings.tsx`)
  - `src/frontend/src/hooks/`: Custom React hooks (e.g., `useApi`, `useToast`)
  - `src/frontend/src/stores/`: State management (e.g., Zustand for `permissions-store`, `breadcrumb-store`)
  - `src/frontend/src/types/`: TypeScript type definitions (e.g., `data-product.ts`, `settings.ts`)
  - `src/frontend/src/config/`: Application configuration (e.g., `features.ts`)
  - `src/frontend/src/lib/`: Utility functions (e.g., `utils.ts`)
- **Configuration Files**:
  - `tsconfig.json`, `tsconfig.node.json`
  - `vite.config.ts`
  - `tailwind.config.js`
  - `postcss.config.js`
  - `index.html` (entry point)
  - `package.json`

### Backend (`./src/backend/`)
- **Language**: Python
- **Framework**: FastAPI
- **Build Tool**: hatch (`pyproject.toml`)
- **Database ORM**: SQLAlchemy
- **Directory Structure**:
  - `src/backend/src/`: Main source code
  - `src/backend/src/controller/`: Manager classes implementing business logic (e.g., `data_products_manager.py`).
  - `src/backend/src/models/`: Pydantic models for API data structures (e.g., `data_products.py`, `settings.py`).
  - `src/backend/src/db_models/`: SQLAlchemy ORM models defining database tables (e.g., `data_products.py`).
  - `src/backend/src/repositories/`: Database access layer using the Repository pattern (e.g., `data_products_repository.py`).
  - `src/backend/src/routes/`: FastAPI routers defining API endpoints (e.g., `data_product_routes.py`).
  - `src/backend/src/utils/`: Helper classes and functions (e.g., `startup_tasks.py`, `demo_data_loader.py`).
  - `src/backend/src/common/`: Shared utilities and base classes.
    - `src/backend/src/common/database.py`: Database setup and session management.
    - `src/backend/src/common/config.py`: Settings loading (`Settings` model) and management.
    - `src/backend/src/common/logging.py`: Logging setup.
    - `src/backend/src/common/workspace_client.py`: Databricks SDK client setup.
    - `src/backend/src/common/dependencies.py`: FastAPI dependency injectors (e.g., `get_settings_manager`, `get_auth_manager`).
    - `src/backend/src/common/authorization.py`: Permissions checking logic (`PermissionChecker`, user detail fetching).
    - `src/backend/src/common/features.py`: Feature definitions and access levels (`FeatureAccessLevel` enum).
    - `src/backend/src/common/search_interfaces.py`: `SearchableAsset` interface definition.
    - `src/backend/src/common/search_registry.py`: `@searchable_asset` decorator and registry (`SEARCHABLE_ASSET_MANAGERS`).
    - `src/backend/src/common/middleware.py`: Custom FastAPI middleware (Logging, Error Handling).
    - `src/backend/src/common/repository.py`: Base repository class (`CRUDBase`).
  - **Configuration & Data**:
    - `.env` / `.env.example`: Environment variables (loaded by `src/backend/src/common/config.py`).
    - `src/backend/src/data/`: Example/Demo data for services (YAML files, e.g., `data_products.yaml`). Loaded by managers or `demo_data_loader.py`.
    - `src/backend/src/schemas/`: JSON schema files (e.g., for Data Contract validation).
    - `src/backend/src/workflows/`: YAML definitions for Databricks jobs/workflows.
    - `src/backend/src/app.yaml`: Databricks App configuration (Asset Bundle format).
  - `src/backend/src/app.py`: FastAPI application entry point.

## Code Style and Structure

### Backend (Python/FastAPI)

- Use `def` for pure functions and `async def` for asynchronous operations (FastAPI route handlers, SDK calls).
- **Type Hints**: Use Python type hints extensively. Use Pydantic models for API input/output validation and SQLAlchemy models for DB interaction.
- **File Structure**: Maintain clear separation of concerns (routes, controllers, repositories, models, db_models, common utilities).
- **RORO Pattern**: API models follow "Receive an Object, Return an Object". Controllers often receive/return API models, mapping to/from DB models via the repository.
- **Error Handling**:
  - Use FastAPI's `HTTPException` for API errors.
  - Handle specific exceptions (e.g., `SQLAlchemyError`, `ValidationError`, `DatabricksError`, `NotFound`) in controllers/repositories.
  - Use guard clauses and early returns.
  - Implement structured logging via `api/common/logging.py`.
- **Dependency Injection**: Rely heavily on FastAPI's DI for providing database sessions, managers, settings, and workspace clients to routes (see `api/common/dependencies.py` and manager getters in route files). Managers are initialized as singletons in `app.state` during startup.

### Frontend (TypeScript/React)

- **TypeScript Usage**: Use TypeScript strictly. Prefer interfaces (`interface`) over types (`type`) for defining object shapes where applicable. Use mapped types or utility types instead of enums.
- **Functional Components**: Write all components as functional components using hooks.
- **UI and Styling**: Use **Shadcn UI** components built on **Tailwind CSS**. Follow responsive design principles.
- **State Management**: Use `useState`, `useEffect`, `useContext` for local/shared state. Use Zustand (`stores/`) for global state (e.g., permissions, breadcrumbs).
- **Data Fetching**: Use a custom hook (`hooks/useApi`) wrapping `fetch` or `axios` for API interactions. Handle loading and error states explicitly. Use `async/await`.
- **Forms**: Use `react-hook-form` for form management and validation, often integrated with Shadcn UI components and Zod for schema validation.
- **Performance**:
  - Minimize `useEffect`, `useState`.
  - Use `React.memo`, `useMemo`, `useCallback` where appropriate.
  - Consider server-side patterns if applicable, although primary interaction is client-side with API.
  - Use `Suspense` for lazy loading components if needed.

## Performance Optimization

### Backend

- **Asynchronous Operations**: Use `async/await` for SDK calls and potentially database operations if using an async driver.
- **Database Query Optimization**: Use efficient SQLAlchemy queries (e.g., `selectinload` for eager loading relationships in repositories). Add database indexes where needed (`db_models`).
- **Caching**: Consider caching for frequently accessed, rarely changing data (e.g., settings, roles) if performance becomes an issue.

### Frontend

- **Component Memoization**: Use `React.memo`, `useMemo`, `useCallback`.
- **Bundle Size**: Monitor bundle size and use code splitting/lazy loading if necessary.
- **Efficient Data Fetching**: Fetch only necessary data. Use libraries like TanStack Query for caching/staleness management if needed.

## Project Conventions

### Backend

1. Follow **RESTful API design**. Endpoints grouped by resource in `api/routes`.
2. Use **FastAPI's dependency injection** (via `Depends`) extensively. Access singletons via `request.app.state` within dependency functions.
3. Use **SQLAlchemy** for ORM. Employ the **Repository pattern** for database abstraction.
4. Ensure **CORS** is configured in `api/app.py` for local development.
5. **Authorization**: Implemented via `api/common/authorization.py` (`PermissionChecker` dependency) based on user groups and role definitions stored in the database (managed by `SettingsManager` and `AuthorizationManager`). User details (including groups) are fetched via Databricks SDK (`api/controller/users_manager.py`, `api/common/authorization.py`). Permissions defined in `api/common/features.py`.
6. **Configuration**: Managed by `api/common/config.py` using Pydantic's `BaseSettings` loading from `.env` and environment variables.
7. **Search**: Managers implement `SearchableAsset` interface and use `@searchable_asset` decorator. `SearchManager` collects items and provides search endpoint.

### Frontend

1. Optimize **Web Vitals**.
2. Use `useToast` hook (based on Shadcn UI Toaster) for user feedback.
3. Use Zustand stores (`stores/`) for cross-component state.
4. Fetch user permissions via `/api/user/permissions` endpoint and store using `permissions-store`. Use `usePermissions` hook to check access levels (e.g., `hasPermission(featureId, FeatureAccessLevel.READ_WRITE)`). Conditionally render UI elements or disable actions based on permissions.
5. Use `breadcrumb-store` to dynamically update breadcrumbs, especially for detail pages.

## Testing and Deployment

- Implement **unit tests** (e.g., using `pytest` for backend, Jest/React Testing Library for frontend).
- Use **Playwright MCP** for automated UI testing and verification:
  - Navigate to pages using `mcp__playwright__browser_navigate`
  - Take snapshots with `mcp__playwright__browser_snapshot` for visual verification
  - Interact with UI elements via `mcp__playwright__browser_click`, `mcp__playwright__browser_type`, etc.
  - Test form functionality with `mcp__playwright__browser_fill_form`
  - Verify responsive behavior and cross-browser compatibility
  - Capture screenshots for documentation or debugging with `mcp__playwright__browser_take_screenshot`
  - Test user workflows end-to-end (e.g., create data product → assign permissions → verify access)
- Ensure proper input validation (Pydantic on backend, Zod/react-hook-form on frontend) and error handling.
- **Deployment**: Deployed as a Databricks App via `databricks bundle deploy` using `api/app.yaml`.
- **Development Server**: When developing locally (localhost is used), the FastAPI/Uvicorn and Vite server run in dev mode with auto-reload enabled. File changes automatically restart/reload the server - no manual restart needed. **IMPORTANT**: NEVER RESTART SERVER PROCESSES!
- Backend server logs are in `/tmp/backend.log`, frontend server logs in `/tmp/frontend.log`
- **Development Ports**: Backend API runs on port 8000, Frontend UI runs on port 3000.
- Always use `hatch -e dev run ...` to run Python snippets
- IMPORTANT: The backend server (Python) logs are in `/tmp/backend.log` and the frontend (Vite) in `/tmp/frontend.log. Read them as needed.

## Database Migrations

- Alembic migrations live in `src/backend/alembic/versions/`. The history must
  always have **exactly one head**; CI enforces this via the
  `check-alembic-heads` job in `.github/workflows/test-coverage.yml`, which
  runs `scripts/check-alembic-heads.py`.
- When authoring a new migration: rebase onto the current base branch first,
  then run `alembic revision -m '<message>'` so the new revision descends
  from the live head.
- If two PRs landed sibling revisions and a merge revision is genuinely
  needed in this PR, run
  `alembic merge -m 'merge heads' <head_a> <head_b>` and apply the
  `alembic-branch` PR label to bypass the CI gate.

## Package Management

- This project uses **Yarn** for frontend package management. Use `yarn add`, `yarn install`, `yarn remove`, etc., instead of `npm`.
- Upon deploying, Databricks Apps detects if `package.json` is present and calls `npm install`, `npm install -r requirements.txt` (if present), and `npm run build` in that case. This should build the static JavaScript content dynamically and there is no need to ship that explicitly.

## Data Product Lifecycle

### 1. Inception
- **Start with desired business outcomes**
  - Clearly define what the business aims to achieve with the data product.
- **Assign owner**
  - Appoint a responsible product owner for governance and delivery.
- **Assign resources**
  - Allocate the necessary team members and budget.
- **Define business metrics**
  - Set measurable objectives for success.

### 2. Design
- **Create a data contract**
  - Draft an agreement outlining expected data inputs, outputs, quality, and responsibilities.
- **Create a data product design specification**
  - Document technical requirements, features, and integration needs.
- **Ensure semantic consistency**
  - Align definitions, formats, and business logic with existing data products.

### 3. Creation
- **Build modular pipelines**
  - Develop features, models, dashboards, and alerts aligned to design specs.
- **Test against data contract**
  - Validate outputs for compliance with the contract; ensure quality and reliability.

### 4. Publishing
- **Deploy using DataOps or MLOps**
  - Use automated pipelines for reliable deployment and scaling (for models and data apps).
- **Publish to catalog**
  - Register product and metadata in the organization's catalog.
- **Manage access permissions**
  - Set roles and permissions per the established data contract.

### 5. Operation & Governance
- **Monitor metrics, quality, usage, permissions**
  - Continuously track product performance and access.
- **Handle compliance requests**
  - Respond to audits, legal, and regulatory needs as they arise.
- **Audit data product access**
  - Regularly review and update access control records.

### 6. Consumption & Value Creation
- **Enable feedback**
  - Gather and process feedback from data consumers for improvements.
- **Share information**
  - Communicate curations and changes with stakeholders.

### 7. Iteration
- **Iterate new version**
  - Refine product design and contract based on feedback and operational results.

### 8. Retirement
- **Deprecate product**
  - Mark the data product as deprecated and communicate status.
- **Inform consumers**
  - Notify users and stakeholders of planned retirement.
- **Shutdown production**
  - Disable active processing and remove integrations.
- **Archive assets**
  - Store relevant artifacts securely as needed for compliance.
- **Clean up resources**
  - Release or repurpose infrastructure and team resources.

### Roles & Responsibilities
- **Business/consumer:** Define needs, use product, provide feedback.
- **Product owner:** Manages lifecycle, ensures delivery.
- **Data engineer / Data scientist / Business analyst:** Design, create, test, publish, iterate data products.
- **Data steward:** Oversees governance and compliance at all stages.
- **DataOps/MLOps:** Supports deployment, publishing, monitoring.

### Contract Maintenance Principles
- Data contracts should be updated iteratively whenever requirements or data formats change.
- All stakeholders must be notified of contract updates.
- Testing and validation are required for any contract change before production rollout.
- Contracts must be archived alongside retired data products for compliance purposes.