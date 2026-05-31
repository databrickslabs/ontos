# CLAUDE.md

Project-specific guidance for Claude Code lives in [`.cursor/rules/`](./.cursor/rules/). Read those files — they apply to Claude as well as Cursor:

- [`01-expertise-and-principles.mdc`](./.cursor/rules/01-expertise-and-principles.mdc) — stack, naming conventions
- [`02-project-overview.mdc`](./.cursor/rules/02-project-overview.mdc) — what this app is, core features
- [`03-system-components-and-requirements.mdc`](./.cursor/rules/03-system-components-and-requirements.mdc) — controller/repository/manager pattern, tagging, search, startup
- [`04-project-structure.mdc`](./.cursor/rules/04-project-structure.mdc) — backend + frontend layout
- [`05-code-style-and-structure.mdc`](./.cursor/rules/05-code-style-and-structure.mdc) — Python + TS rules, error/logging security
- [`07-project-conventions.mdc`](./.cursor/rules/07-project-conventions.mdc) — auth, config, permissions store, breadcrumbs
- [`08-testing-and-deployment.mdc`](./.cursor/rules/08-testing-and-deployment.mdc) — local dev, log paths, ports, Playwright MCP
- [`09-package-management.mdc`](./.cursor/rules/09-package-management.mdc) — yarn (not npm)
- [`10-entity-panel-matrix.mdc`](./.cursor/rules/10-entity-panel-matrix.mdc) — which polymorphic panels apply to which entity/asset type
- [`11-database-migrations.mdc`](./.cursor/rules/11-database-migrations.mdc) — Alembic short-revision convention, single-head rule, new-migration workflow

## Claude-specific

- This repo intentionally does **not** ship project-level subagents or slash commands. Use Claude Code's built-in subagent types (e.g., `backend-architect`, `code-reviewer`, `frontend-developer`, `test-engineer`) and built-in PR/commit flows.
- **MCP servers** typically configured in this workspace: Databricks, Playwright, Shadcn UI, Ref, magicui, sequential-thinking, context7, memory. Prefer them over ad-hoc shell commands when applicable.

## Operational must-knows (mirrors of the rules above; repeated here because they bite)

- **NEVER restart the dev server processes.** Backend and frontend run with auto-reload. See `08-testing-and-deployment.mdc`.
- Backend logs: `/tmp/backend.log`. Frontend logs: `/tmp/frontend.log`. Read them for debugging.
- Backend port: **8000**. Frontend port: **3000**.
- Run Python via `hatch -e dev run ...`.
- Frontend package manager is **yarn**, not npm.
