/**
 * Tests for RequestProductActionDialog component
 *
 * Focused on the initial-request-type behavior. The dialog uses Radix Select
 * elements which hang in jsdom when interacted with, so these tests only assert
 * static text rendered by the dialog header — which is driven directly by the
 * initial request-type state.
 */
import { screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import RequestProductActionDialog from './request-product-action-dialog';

// Mock hooks that hit external services
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() })
}));

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({ data: null })
  })
}));

vi.mock('@/stores/notifications-store', () => ({
  useNotificationsStore: (selector: any) =>
    selector({ refreshNotifications: vi.fn() })
}));

describe('RequestProductActionDialog default request type', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("defaults to 'access' when defaultRequestType is not provided", () => {
    renderWithProviders(
      <RequestProductActionDialog
        isOpen={true}
        onOpenChange={vi.fn()}
        productId="prod-1"
        productName="Test Product"
        productStatus="draft"
      />
    );

    // Header title is driven by the active request type. 'access' renders
    // 'Request Access to Product'; 'status_change' would render
    // 'Request Status Change' / 'Change Status'.
    expect(
      screen.getByRole('heading', { name: /Request Access to Product/ })
    ).toBeInTheDocument();
  });

  it("uses 'status_change' when defaultRequestType='status_change' is passed", () => {
    renderWithProviders(
      <RequestProductActionDialog
        isOpen={true}
        onOpenChange={vi.fn()}
        productId="prod-1"
        productName="Test Product"
        productStatus="draft"
        defaultRequestType="status_change"
      />
    );

    // The dialog title (h2) reflects the active request type. Scope the
    // assertion to the heading role so we don't match identical text in the
    // request-type Select dropdown options.
    expect(
      screen.getByRole('heading', { name: /Request Status Change/ })
    ).toBeInTheDocument();
  });

  it("uses 'status_change' direct-change title when canDirectStatusChange is true", () => {
    renderWithProviders(
      <RequestProductActionDialog
        isOpen={true}
        onOpenChange={vi.fn()}
        productId="prod-1"
        productName="Test Product"
        productStatus="draft"
        defaultRequestType="status_change"
        canDirectStatusChange={true}
      />
    );

    // With direct-change permission the title flips to 'Change Status'.
    expect(
      screen.getByRole('heading', { name: /Change Status/ })
    ).toBeInTheDocument();
  });
});
