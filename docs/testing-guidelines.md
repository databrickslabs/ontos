# Testing Guidelines

This document provides guidelines and best practices for writing tests in the UC App project.

## Table of Contents

1. [General Principles](#general-principles)
2. [Backend Testing (Python/pytest)](#backend-testing-pythonpytest)
3. [Frontend Testing (TypeScript/Vitest)](#frontend-testing-typescriptvitest)
4. [E2E Testing (Playwright)](#e2e-testing-playwright)
5. [Common Patterns](#common-patterns)
6. [Running Tests](#running-tests)

---

## General Principles

### Test Structure

Follow the **AAA** pattern (Arrange, Act, Assert):

```python
def test_example():
    # Arrange - Set up test data and dependencies
    user = create_test_user()

    # Act - Execute the functionality
    result = user.get_name()

    # Assert - Verify the outcome
    assert result == "Test User"
```

### Test Naming

Use descriptive test names that explain the scenario:

**Good:**
- `test_create_data_product_success`
- `test_create_data_product_with_invalid_name_fails`
- `test_get_data_product_by_id_not_found_returns_404`

**Bad:**
- `test_product_1`
- `test_create`
- `test_error`

### Test Independence

Each test should be independent and not rely on other tests:

```python
# Good - Each test sets up its own data
def test_update_product(db_session):
    product = create_test_product(db_session)
    updated = update_product(product.id, {"name": "New Name"})
    assert updated.name == "New Name"

# Bad - Relies on data from another test
def test_update_product():
    # Assumes product from previous test exists
    updated = update_product("test-id", {"name": "New Name"})
```

### Test Coverage Goals

- **Critical paths**: 100%
- **Business logic**: 85%+
- **Routes/API endpoints**: 80%+
- **Utilities**: 75%+
- **Overall project**: 80%+

---

## Backend Testing (Python/pytest)

### File Organization

```
src/backend/src/tests/
├── unit/              # Unit tests for managers, repositories, utilities
│   ├── test_data_products_manager.py
│   ├── test_data_contracts_manager.py
│   └── ...
├── integration/       # Integration tests for routes and database
│   ├── test_data_product_routes.py
│   ├── test_data_contracts_routes.py
│   └── ...
├── conftest.py        # Shared fixtures
└── helpers.py         # Test utilities
```

### Unit Tests - Managers

Test business logic in isolation:

```python
import pytest
from unittest.mock import Mock, patch
from src.controller.data_products_manager import DataProductsManager

class TestDataProductsManager:
    @pytest.fixture
    def manager(self, db_session, test_settings, mock_workspace_client):
        """Create manager instance for testing."""
        return DataProductsManager(
            db=db_session,
            settings=test_settings,
            workspace_client=mock_workspace_client
        )

    def test_create_data_product_success(self, manager, db_session):
        """Test successful data product creation."""
        product_data = {
            "name": "Test Product",
            "description": "Test Description",
            "version": "1.0.0",
            "owner": "test@example.com"
        }

        result = manager.create_data_product(product_data)

        assert result.name == "Test Product"
        assert result.version == "1.0.0"
        assert result.id is not None

    def test_create_data_product_duplicate_name_fails(self, manager, sample_data_product):
        """Test that duplicate names are rejected."""
        duplicate_data = {
            "name": sample_data_product.name,  # Same name
            "version": "2.0.0",
        }

        with pytest.raises(HTTPException) as exc:
            manager.create_data_product(duplicate_data)

        assert exc.value.status_code == 409  # Conflict

    def test_sync_from_databricks_handles_sdk_error(
        self, manager, mock_workspace_client
    ):
        """Test handling of Databricks SDK errors."""
        from databricks.sdk.core import DatabricksError

        mock_workspace_client.tables.list.side_effect = DatabricksError(
            "Connection timeout"
        )

        with pytest.raises(HTTPException) as exc:
            manager.sync_from_databricks()

        assert exc.value.status_code in [500, 502, 503]
```

### Integration Tests - Routes

Test API endpoints end-to-end:

```python
import pytest
from fastapi.testclient import TestClient

class TestDataProductRoutes:
    def test_list_data_products(self, client, db_session, sample_data_product):
        """Test listing data products."""
        response = client.get("/api/data-products")

        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert any(p["id"] == sample_data_product.id for p in data)

    def test_create_data_product_success(
        self, client, verify_audit_log
    ):
        """Test POST /api/data-products."""
        product_data = {
            "name": "New Product",
            "description": "Test",
            "version": "1.0.0",
            "owner": "test@example.com"
        }

        response = client.post("/api/data-products", json=product_data)

        assert response.status_code == 201
        result = response.json()
        assert result["name"] == "New Product"

        # Verify audit log
        verify_audit_log("data_products", "create", success=True)

    def test_create_data_product_validation_error(self, client):
        """Test validation errors."""
        invalid_data = {
            "name": "",  # Empty name should fail
        }

        response = client.post("/api/data-products", json=invalid_data)

        assert response.status_code == 422
        assert "validation" in response.json()["detail"].lower()

    def test_update_requires_permission(self, client, mock_test_user):
        """Test authorization."""
        mock_test_user.groups = []  # Remove permissions

        response = client.put(
            "/api/data-products/test-id",
            json={"name": "Updated"}
        )

        assert response.status_code == 403
```

### Using Fixtures

Leverage shared fixtures from `conftest.py`:

```python
def test_with_fixtures(
    client,                 # TestClient with mocked dependencies
    db_session,             # Database session
    test_settings,          # Test configuration
    mock_workspace_client,  # Mocked Databricks SDK client
    mock_test_user,         # Test user with permissions
    sample_data_product,    # Pre-created data product
    verify_audit_log,       # Helper to verify audit logs
):
    # Your test here
    pass
```

### Mocking Databricks SDK

```python
def test_catalog_sync(manager, mock_workspace_client):
    """Test syncing catalogs from Databricks."""
    # Set up mock response
    mock_workspace_client.catalogs.list.return_value = [
        Mock(
            name="catalog1",
            comment="Test Catalog",
            properties={"key": "value"}
        ),
        Mock(
            name="catalog2",
            comment="Another Catalog",
            properties={}
        )
    ]

    # Execute
    result = manager.sync_catalogs()

    # Verify
    assert len(result) == 2
    assert result[0].name == "catalog1"
    mock_workspace_client.catalogs.list.assert_called_once()
```

---

## Frontend Testing (TypeScript/Vitest)

### File Organization

```
src/frontend/src/
├── components/
│   ├── data-products/
│   │   ├── data-product-form.tsx
│   │   └── data-product-form.test.tsx
│   └── ui/
├── views/
│   ├── data-products.tsx
│   └── data-products.test.tsx
├── stores/
│   ├── permissions-store.ts
│   └── permissions-store.test.ts
├── hooks/
│   ├── use-api.ts
│   └── use-api.test.ts
└── test/
    ├── setup.ts
    └── utils.tsx
```

### Component Tests

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DataProductForm } from './data-product-form';

// Mock API
const mockApi = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({
    post: mockApi,
    get: mockApi,
  })
}));

describe('DataProductForm', () => {
  const defaultProps = {
    onSubmit: vi.fn(),
    onCancel: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering', () => {
    it('renders all form fields', () => {
      render(<DataProductForm {...defaultProps} />);

      expect(screen.getByLabelText('Name')).toBeInTheDocument();
      expect(screen.getByLabelText('Description')).toBeInTheDocument();
      expect(screen.getByLabelText('Version')).toBeInTheDocument();
    });

    it('renders with initial data', () => {
      const initialData = {
        name: 'Existing Product',
        version: '1.0.0',
      };

      render(<DataProductForm {...defaultProps} initialData={initialData} />);

      expect(screen.getByDisplayValue('Existing Product')).toBeInTheDocument();
      expect(screen.getByDisplayValue('1.0.0')).toBeInTheDocument();
    });
  });

  describe('User Interactions', () => {
    it('handles form submission', async () => {
      const user = userEvent.setup();
      const onSubmit = vi.fn();

      render(<DataProductForm {...defaultProps} onSubmit={onSubmit} />);

      // Fill in form
      await user.type(screen.getByLabelText('Name'), 'New Product');
      await user.type(screen.getByLabelText('Description'), 'Test Description');
      await user.type(screen.getByLabelText('Version'), '1.0.0');

      // Submit
      await user.click(screen.getByRole('button', { name: 'Submit' }));

      // Verify
      await waitFor(() => {
        expect(onSubmit).toHaveBeenCalledWith(
          expect.objectContaining({
            name: 'New Product',
            description: 'Test Description',
            version: '1.0.0',
          })
        );
      });
    });

    it('validates required fields', async () => {
      const user = userEvent.setup();

      render(<DataProductForm {...defaultProps} />);

      // Submit without filling fields
      await user.click(screen.getByRole('button', { name: 'Submit' }));

      // Verify validation errors
      expect(screen.getByText('Name is required')).toBeInTheDocument();
      expect(screen.getByText('Version is required')).toBeInTheDocument();
    });

    it('calls onCancel when cancel button clicked', async () => {
      const user = userEvent.setup();
      const onCancel = vi.fn();

      render(<DataProductForm {...defaultProps} onCancel={onCancel} />);

      await user.click(screen.getByRole('button', { name: 'Cancel' }));

      expect(onCancel).toHaveBeenCalled();
    });
  });

  describe('Data Fetching', () => {
    it('loads domains on mount', async () => {
      mockApi.mockResolvedValue({
        data: [{ id: '1', name: 'Domain 1' }]
      });

      render(<DataProductForm {...defaultProps} />);

      await waitFor(() => {
        expect(mockApi).toHaveBeenCalledWith('/api/domains');
      });
    });

    it('displays loading state', () => {
      mockApi.mockImplementation(() => new Promise(() => {})); // Never resolves

      render(<DataProductForm {...defaultProps} />);

      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });

    it('handles API errors', async () => {
      mockApi.mockRejectedValue(new Error('API Error'));

      render(<DataProductForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByText(/error/i)).toBeInTheDocument();
      });
    });
  });
});
```

### Store Tests (Zustand)

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { usePermissionsStore } from './permissions-store';

describe('Permissions Store', () => {
  beforeEach(() => {
    // Reset store before each test
    const { result } = renderHook(() => usePermissionsStore());
    act(() => {
      result.current.reset();
    });
  });

  it('has correct initial state', () => {
    const { result } = renderHook(() => usePermissionsStore());

    expect(result.current.permissions).toEqual({});
    expect(result.current.isLoading).toBe(false);
  });

  it('sets permissions correctly', () => {
    const { result } = renderHook(() => usePermissionsStore());

    const testPermissions = {
      'data-products': 'read-write',
      'data-contracts': 'read-only',
    };

    act(() => {
      result.current.setPermissions(testPermissions);
    });

    expect(result.current.permissions).toEqual(testPermissions);
  });

  it('checks permissions correctly', () => {
    const { result } = renderHook(() => usePermissionsStore());

    act(() => {
      result.current.setPermissions({
        'data-products': 'read-write',
      });
    });

    expect(result.current.hasPermission('data-products', 'read')).toBe(true);
    expect(result.current.hasPermission('data-products', 'write')).toBe(true);
    expect(result.current.hasPermission('data-contracts', 'read')).toBe(false);
  });
});
```

### Hook Tests

```typescript
import { describe, it, expect, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useDataProducts } from './use-data-products';

const mockApi = vi.fn();
vi.mock('./use-api', () => ({
  useApi: () => ({ get: mockApi })
}));

describe('useDataProducts', () => {
  it('fetches data products on mount', async () => {
    const mockData = [
      { id: '1', name: 'Product 1' },
      { id: '2', name: 'Product 2' },
    ];

    mockApi.mockResolvedValue({ data: mockData });

    const { result } = renderHook(() => useDataProducts());

    expect(result.current.isLoading).toBe(true);

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
      expect(result.current.products).toEqual(mockData);
    });
  });

  it('handles errors gracefully', async () => {
    mockApi.mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => useDataProducts());

    await waitFor(() => {
      expect(result.current.error).toBeDefined();
      expect(result.current.products).toEqual([]);
    });
  });
});
```

### Using Test Utilities

```typescript
import { renderWithRouter, createMockApiResponse } from '@/test/utils';

it('navigates on click', async () => {
  const user = userEvent.setup();

  renderWithRouter(<DataProductList />, { route: '/data-products' });

  await user.click(screen.getByText('View Details'));

  expect(window.location.pathname).toBe('/data-products/123');
});
```

---

## E2E Testing (Playwright)

### File Organization

```
src/frontend/src/tests/
├── data-product-creation.spec.ts
├── data-contract-lifecycle.spec.ts
└── access-review.spec.ts
```

### E2E Test Structure

```typescript
import { test, expect } from '@playwright/test';

test.describe('Data Product Creation Workflow', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to app
    await page.goto('/');

    // Add any necessary setup (login, etc.)
  });

  test('creates a data product successfully', async ({ page }) => {
    // Navigate to data products
    await page.click('nav >> text=Data Products');

    // Click create button
    await page.click('button:has-text("Create Product")');

    // Fill in form
    await page.fill('input[name="name"]', 'E2E Test Product');
    await page.fill('textarea[name="description"]', 'Created by E2E test');
    await page.fill('input[name="version"]', '1.0.0');

    // Select domain
    await page.click('select[name="domain"]');
    await page.click('option:has-text("Test Domain")');

    // Submit
    await page.click('button:has-text("Create")');

    // Verify success
    await expect(page.locator('.toast')).toContainText('successfully');

    // Verify in list
    await expect(page.locator('text=E2E Test Product')).toBeVisible();
  });

  test('validates required fields', async ({ page }) => {
    await page.click('nav >> text=Data Products');
    await page.click('button:has-text("Create Product")');

    // Submit without filling fields
    await page.click('button:has-text("Create")');

    // Verify validation errors
    await expect(page.locator('text=Name is required')).toBeVisible();
    await expect(page.locator('text=Version is required')).toBeVisible();
  });

  test('cancels creation', async ({ page }) => {
    await page.click('nav >> text=Data Products');
    await page.click('button:has-text("Create Product")');

    // Fill some data
    await page.fill('input[name="name"]', 'Cancelled Product');

    // Cancel
    await page.click('button:has-text("Cancel")');

    // Verify dialog closed
    await expect(page.locator('dialog')).not.toBeVisible();

    // Verify product not created
    await expect(page.locator('text=Cancelled Product')).not.toBeVisible();
  });
});
```

---

## Common Patterns

### Testing Async Operations

```typescript
// Wait for specific condition
await waitFor(() => {
  expect(screen.getByText('Loaded')).toBeInTheDocument();
});

// Wait with timeout
await waitFor(
  () => {
    expect(mockApi).toHaveBeenCalled();
  },
  { timeout: 5000 }
);
```

### Testing Error States

```python
def test_handles_error(manager):
    with pytest.raises(HTTPException) as exc:
        manager.invalid_operation()

    assert exc.value.status_code == 400
    assert "error message" in exc.value.detail.lower()
```

```typescript
it('displays error message', async () => {
  mockApi.mockRejectedValue(new Error('Something went wrong'));

  render(<Component />);

  await waitFor(() => {
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
  });
});
```

### Testing Loading States

```typescript
it('shows loading spinner', () => {
  mockApi.mockImplementation(() => new Promise(() => {}));

  render(<Component />);

  expect(screen.getByRole('progressbar')).toBeInTheDocument();
});
```

### Testing Conditional Rendering

```typescript
it('shows edit button only for owners', () => {
  const { rerender } = render(<Component isOwner={false} />);

  expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();

  rerender(<Component isOwner={true} />);

  expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument();
});
```

---

## Running Tests

### Backend

```bash
# All tests
cd src
hatch -e dev run test

# With coverage
hatch -e dev run test-cov

# Unit tests only
hatch -e dev run test-unit

# Integration tests only
hatch -e dev run test-integration

# Specific file
hatch -e dev run pytest backend/src/tests/unit/test_data_products_manager.py

# Specific test
hatch -e dev run pytest backend/src/tests/unit/test_data_products_manager.py::TestDataProductsManager::test_create_success
```

### Frontend

```bash
cd src/frontend

# Interactive mode
npm test

# Run once
npm run test:run

# With coverage
npm run test:coverage

# Watch mode
npm run test:watch

# UI mode
npm run test:ui

# Specific file
npm test -- data-product-form.test.tsx
```

### E2E

```bash
cd src/frontend

# Run all E2E tests
npm run test:e2e

# Interactive mode
npm run test:e2e:ui

# Debug mode
npm run test:e2e:debug

# Specific test
npm run test:e2e -- data-product-creation.spec.ts
```

---

## Best Practices Summary

1. **Write tests first** (TDD) when possible
2. **Keep tests simple** - One assertion per test when feasible
3. **Use descriptive names** - Test names should explain the scenario
4. **Test behavior, not implementation** - Don't test internal details
5. **Mock external dependencies** - Database, APIs, SDK calls
6. **Use fixtures and helpers** - Don't repeat setup code
7. **Test edge cases** - Empty inputs, null values, errors
8. **Maintain tests** - Update tests when code changes
9. **Run tests frequently** - Before commits, in CI/CD
10. **Aim for coverage** - But don't sacrifice quality for quantity

---

## Resources

- [pytest Documentation](https://docs.pytest.org/)
- [Vitest Documentation](https://vitest.dev/)
- [Testing Library](https://testing-library.com/)
- [Playwright Documentation](https://playwright.dev/)
- [TESTING_PLAN.md](../TESTING_PLAN.md) - Project testing roadmap
