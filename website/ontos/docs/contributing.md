---
sidebar_position: 8
---

# Contributing

Thank you for your interest in contributing to Ontos! This document provides guidelines and instructions for contributing to the project.

## Code of Conduct

Please be respectful and professional in all interactions. We're building a collaborative community around data governance.

## Getting Started

### Prerequisites

- **Python 3.10 - 3.12** (as defined in `pyproject.toml`)
- **Node.js 18+** (includes npm for installing Yarn)
- **Yarn** package manager (Version 1.x - Classic):
  ```bash
  npm install --global yarn
  ```
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

## Development Setup

### 1. Install Dependencies

```bash
# Frontend dependencies
cd src/frontend
yarn install

# Backend dependencies are managed by Hatch and installed automatically
```

### 2. Configure Environment

Create a `.env` file in the project root:

```bash
cp .env.example .env
# Edit .env with your configuration
```

**See CONFIGURING for complete documentation on:**


- All environment variables
- Database setup (local PostgreSQL and Lakebase)
- Connection pool tuning
- Default roles configuration

### 3. Start Development Servers

**Frontend** (Terminal 1):
```bash
cd src/frontend
yarn dev:frontend
```

**Backend** (Terminal 2):
```bash
cd src
yarn dev:backend
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs (Swagger): http://localhost:8000/docs


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
   cd src/frontend && yarn test:run
   ```

2. **Linting passes**:
   ```bash
   # Backend
   cd src && hatch -e dev run lint:all
   
   # Frontend
   cd src/frontend && yarn type-check
   ```

3. **Commit message follows convention**


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
| `src/frontend/package.json` | Node/Yarn frontend |
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
   cd src/frontend && yarn test:run
   ```

3. **Check types and lint**:
   ```bash
   cd src/frontend && yarn type-check
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
yarn test:run

# Run with coverage
yarn test:coverage

# Run in watch mode
yarn test:watch

# Run E2E tests
yarn test:e2e
```

### Writing Tests

- Place unit tests next to the code or in `tests/unit/`
- Name tests descriptively: `test_create_data_product_validates_schema`
- Use fixtures for common setup
- Aim for >80% coverage on new code

## License

By contributing to Ontos, you agree that your contributions will be licensed under the project's license (see LICENSE.txt).

## Questions?

- Open an issue for bugs or feature requests
- Start a discussion for questions or ideas
- Check existing issues before creating new ones

Thank you for contributing to Ontos! 🎉


