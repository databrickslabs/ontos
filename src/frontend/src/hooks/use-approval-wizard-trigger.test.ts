/**
 * Tests for the portable approval-wizard launch helper.
 *
 * Covers the three behaviors call sites depend on:
 *   1. Returns the workflow id on success.
 *   2. Returns ``null`` on 404 (no workflow configured) — so callers fall through
 *      to direct-submit.
 *   3. Never throws on transport / parse errors — also returns ``null``.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

const mockGet = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() }),
}));

import { useApprovalWizardTrigger } from './use-approval-wizard-trigger';

describe('useApprovalWizardTrigger', () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it('returns the workflow id when the lookup succeeds', async () => {
    mockGet.mockResolvedValueOnce({ data: { id: 'wf-abc' } });
    const { result } = renderHook(() => useApprovalWizardTrigger());

    let workflowId: string | null = null;
    await act(async () => {
      workflowId = await result.current.lookupWorkflowId('for_request_access');
    });

    expect(mockGet).toHaveBeenCalledWith('/api/workflows/for-trigger/for_request_access');
    expect(workflowId).toBe('wf-abc');
  });

  it('returns null when the API resolves with no data (404 fallthrough)', async () => {
    mockGet.mockResolvedValueOnce({ data: null });
    const { result } = renderHook(() => useApprovalWizardTrigger());

    let workflowId: string | null = 'sentinel';
    await act(async () => {
      workflowId = await result.current.lookupWorkflowId('for_subscribe');
    });
    expect(workflowId).toBeNull();
  });

  it('returns null when the API throws (never propagates errors to callers)', async () => {
    mockGet.mockRejectedValueOnce(new Error('network down'));
    const { result } = renderHook(() => useApprovalWizardTrigger());

    let workflowId: string | null = 'sentinel';
    await act(async () => {
      workflowId = await result.current.lookupWorkflowId('for_request_certify');
    });
    expect(workflowId).toBeNull();
  });

  it('passes the trigger type through to the URL verbatim', async () => {
    mockGet.mockResolvedValue({ data: { id: 'wf-x' } });
    const { result } = renderHook(() => useApprovalWizardTrigger());

    await act(async () => {
      await result.current.lookupWorkflowId('for_request_publish');
      await result.current.lookupWorkflowId('for_request_status_change');
    });

    expect(mockGet.mock.calls[0][0]).toBe('/api/workflows/for-trigger/for_request_publish');
    expect(mockGet.mock.calls[1][0]).toBe('/api/workflows/for-trigger/for_request_status_change');
  });
});
