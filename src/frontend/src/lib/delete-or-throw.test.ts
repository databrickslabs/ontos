import { describe, it, expect, vi } from 'vitest';
import { deleteOrThrow } from './delete-or-throw';

describe('deleteOrThrow', () => {
  it('throws with the API error so callers show the error toast and skip navigation', async () => {
    const del = vi.fn().mockResolvedValue({ data: null, error: 'Failed to delete product' });
    await expect(deleteOrThrow(del, '/api/data-products/p1')).rejects.toThrow(
      'Failed to delete product',
    );
    expect(del).toHaveBeenCalledWith('/api/data-products/p1');
  });

  it('resolves when the response has no error', async () => {
    const del = vi.fn().mockResolvedValue({ data: null });
    await expect(deleteOrThrow(del, '/api/data-products/p1')).resolves.toBeUndefined();
  });

  it('lets a rejected request propagate', async () => {
    const del = vi.fn().mockRejectedValue(new Error('network'));
    await expect(deleteOrThrow(del, '/x')).rejects.toThrow('network');
  });
});
