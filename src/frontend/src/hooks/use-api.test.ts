import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useApi } from './use-api';

// Mock fetch globally
global.fetch = vi.fn();

describe('useApi Hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('Initial State', () => {
    it('initializes with loading false', () => {
      const { result } = renderHook(() => useApi());
      expect(result.current.loading).toBe(false);
    });

    it('provides all HTTP methods', () => {
      const { result } = renderHook(() => useApi());
      expect(typeof result.current.get).toBe('function');
      expect(typeof result.current.post).toBe('function');
      expect(typeof result.current.put).toBe('function');
      expect(typeof result.current.delete).toBe('function');
    });
  });

  describe('GET Request', () => {
    it('performs successful GET request with JSON response', async () => {
      // Arrange
      const mockData = { id: 1, name: 'Test' };
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({
          'Content-Type': 'application/json',
        }),
        json: async () => mockData,
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.get('/api/test');
      });

      // Assert
      expect(response.data).toEqual(mockData);
      expect(response.error).toBeUndefined();
      expect(global.fetch).toHaveBeenCalledWith('/api/test');
    });

    it('sets loading state during GET request', async () => {
      // Arrange
      let resolvePromise: (value: any) => void;
      const promise = new Promise((resolve) => {
        resolvePromise = resolve;
      });

      (global.fetch as any).mockReturnValueOnce(promise);

      const { result } = renderHook(() => useApi());

      // Act
      let responsePromise: Promise<any>;
      act(() => {
        responsePromise = result.current.get('/api/test');
      });

      // Assert - Loading should be true during request
      await waitFor(() => {
        expect(result.current.loading).toBe(true);
      });

      // Resolve the promise
      resolvePromise!({
        ok: true,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => ({ data: 'test' }),
      });

      await act(async () => {
        await responsePromise!;
      });

      // Loading should be false after request
      expect(result.current.loading).toBe(false);
    });

    it('handles 404 error with JSON detail', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 404,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => ({ detail: 'Not found' }),
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.get('/api/test');
      });

      // Assert
      expect(response.error).toBe('Not found');
      expect(response.data).toEqual({});
    });

    it('handles 500 error with text response', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        headers: new Headers({ 'Content-Type': 'text/plain' }),
        text: async () => 'Server error occurred',
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.get('/api/test');
      });

      // Assert
      expect(response.error).toBe('Server error occurred');
    });

    it('handles 204 No Content response', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 204,
        headers: new Headers({ 'Content-Length': '0' }),
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.get('/api/test');
      });

      // Assert
      expect(response.data).toEqual([]);
      expect(response.error).toBeUndefined();
    });

    it('handles response with Content-Length: 0', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ 'Content-Length': '0' }),
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.get('/api/test');
      });

      // Assert
      expect(response.data).toEqual([]);
    });

    it('handles text/plain response that looks like JSON', async () => {
      // Arrange
      const jsonText = '{"id": 1, "name": "Test"}';
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ 'Content-Type': 'text/plain' }),
        text: async () => jsonText,
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.get('/api/test');
      });

      // Assert
      expect(response.data).toEqual({ id: 1, name: 'Test' });
    });

    it('handles plain text response', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ 'Content-Type': 'text/plain' }),
        text: async () => 'plain text response',
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.get('/api/test');
      });

      // Assert
      expect(response.data).toBe('plain text response');
    });

    it('handles network error', async () => {
      // Arrange
      (global.fetch as any).mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.get('/api/test');
      });

      // Assert
      expect(response.error).toBe('Network error');
      expect(response.data).toEqual({});
    });

    it('handles error parsing error response', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => {
          throw new Error('Parse error');
        },
        text: async () => {
          throw new Error('Parse error');
        },
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.get('/api/test');
      });

      // Assert
      expect(response.error).toBe('Internal Server Error');
    });
  });

  describe('POST Request', () => {
    it('performs successful POST request with JSON body', async () => {
      // Arrange
      const mockData = { id: 1, name: 'Created' };
      const postBody = { name: 'New Item' };

      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 201,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => mockData,
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.post('/api/test', postBody);
      });

      // Assert
      expect(response.data).toEqual(mockData);
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/test',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(postBody),
        })
      );
    });

    it('performs POST request with FormData', async () => {
      // Arrange
      const formData = new FormData();
      formData.append('file', new Blob(['test']), 'test.txt');

      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => ({ success: true }),
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.post('/api/upload', formData);
      });

      // Assert
      expect(response.data).toEqual({ success: true });
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/upload',
        expect.objectContaining({
          method: 'POST',
          body: formData,
        })
      );
    });

    it('handles POST error with FastAPI validation detail', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 422,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => ({
          detail: [{ msg: 'Field is required', type: 'value_error' }],
        }),
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.post('/api/test', {});
      });

      // Assert
      expect(response.error).toBe('Field is required');
    });

    it('returns the code of a structured POST error next to its message', async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 403,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => ({
          detail: { code: 'own_owner_approval', message: "You can't approve your own request." },
        }),
      });

      const { result } = renderHook(() => useApi());

      let response: any;
      await act(async () => {
        response = await result.current.post('/api/test', {});
      });

      expect(response.error).toBe("You can't approve your own request.");
      expect(response.errorCode).toBe('own_owner_approval');
    });

    it('has no error code for a plain detail string', async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 400,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => ({ detail: 'Bad request' }),
      });

      const { result } = renderHook(() => useApi());

      let response: any;
      await act(async () => {
        response = await result.current.post('/api/test', {});
      });

      expect(response.errorCode).toBeNull();
    });

    it('returns the parameters of a structured POST error', async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 400,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => ({
          detail: {
            code: 'status_change_blocked',
            message: "Status transition from 'draft' to 'active' blocked by workflow: Gate: failed",
            params: { fromStatus: 'draft', toStatus: 'active', reasons: [] },
          },
        }),
      });

      const { result } = renderHook(() => useApi());

      let response: any;
      await act(async () => {
        response = await result.current.post('/api/test', {});
      });

      expect(response.error).toBe("Status transition from 'draft' to 'active' blocked by workflow: Gate: failed");
      expect(response.errorParams).toEqual({ fromStatus: 'draft', toStatus: 'active', reasons: [] });
    });

    it('handles POST error with simple detail string', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 400,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => ({ detail: 'Bad request' }),
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.post('/api/test', {});
      });

      // Assert
      expect(response.error).toBe('Bad request');
    });

    it('handles POST response with no content (204)', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 204,
        headers: new Headers({ 'Content-Length': '0' }),
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.post('/api/test', {});
      });

      // Assert
      expect(response.data).toEqual({});
    });

    it('handles POST response with text content', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ 'Content-Type': 'text/plain' }),
        text: async () => 'Success message',
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.post('/api/test', {});
      });

      // Assert
      expect(response.data).toBe('Success message');
    });

    it('handles POST parse error on successful response', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => {
          throw new Error('Parse failed');
        },
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.post('/api/test', {});
      });

      // Assert
      expect(response.error).toContain('Failed to parse response');
    });

    it('handles POST network error', async () => {
      // Arrange
      (global.fetch as any).mockRejectedValueOnce(new Error('Network failure'));

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.post('/api/test', {});
      });

      // Assert
      expect(response.error).toBe('Network failure');
    });
  });

  describe('PUT Request', () => {
    it('performs successful PUT request', async () => {
      // Arrange
      const mockData = { id: 1, name: 'Updated' };
      const putBody = { name: 'Updated Item' };

      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => mockData,
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.put('/api/test/1', putBody);
      });

      // Assert
      expect(response.data).toEqual(mockData);
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/test/1',
        expect.objectContaining({
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(putBody),
        })
      );
    });

    it('handles PUT error response', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 404,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => ({ detail: 'Resource not found' }),
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.put('/api/test/999', {});
      });

      // Assert
      expect(response.error).toBe('Resource not found');
    });

    it('handles PUT network error', async () => {
      // Arrange
      (global.fetch as any).mockRejectedValueOnce(new Error('Connection refused'));

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.put('/api/test/1', {});
      });

      // Assert
      expect(response.error).toBe('Connection refused');
    });

    it('handles PUT error with text response', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        headers: new Headers({ 'Content-Type': 'text/plain' }),
        text: async () => 'Server error text',
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.put('/api/test/1', {});
      });

      // Assert
      expect(response.error).toBe('Server error text');
    });
  });

  describe('DELETE Request', () => {
    it('performs successful DELETE request', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 204,
        headers: new Headers(),
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.delete('/api/test/1');
      });

      // Assert
      expect(response.data).toEqual({});
      expect(response.error).toBeNull();
      expect(global.fetch).toHaveBeenCalledWith('/api/test/1', {
        method: 'DELETE',
      });
    });

    it('handles DELETE error with JSON detail', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 404,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => ({ detail: 'Item not found' }),
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.delete('/api/test/999');
      });

      // Assert
      expect(response.error).toBe('Item not found');
    });

    it('handles DELETE error with text response', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 403,
        statusText: 'Forbidden',
        headers: new Headers({ 'Content-Type': 'text/plain' }),
        text: async () => 'Access denied',
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.delete('/api/test/1');
      });

      // Assert
      expect(response.error).toBe('Access denied');
    });

    it('handles DELETE network error', async () => {
      // Arrange
      (global.fetch as any).mockRejectedValueOnce(new Error('Timeout'));

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.delete('/api/test/1');
      });

      // Assert
      expect(response.error).toBe('Timeout');
    });

    it('handles DELETE error parse failure', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Server Error',
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => {
          throw new Error('Parse error');
        },
        text: async () => {
          throw new Error('Parse error');
        },
      });

      const { result } = renderHook(() => useApi());

      // Act
      let response: any;
      await act(async () => {
        response = await result.current.delete('/api/test/1');
      });

      // Assert
      expect(response.error).toBe('Server Error');
    });
  });

  describe('Hook Stability', () => {
    it('maintains function identity across renders', () => {
      // Arrange
      const { result, rerender } = renderHook(() => useApi());
      const firstGet = result.current.get;
      const firstPost = result.current.post;
      const firstPut = result.current.put;
      const firstDelete = result.current.delete;

      // Act
      rerender();

      // Assert - Functions should be the same (useCallback ensures this)
      expect(result.current.get).toBe(firstGet);
      expect(result.current.post).toBe(firstPost);
      expect(result.current.put).toBe(firstPut);
      expect(result.current.delete).toBe(firstDelete);
    });
  });

  describe('Loading State Management', () => {
    it('resets loading state after successful request', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        headers: new Headers({ 'Content-Type': 'application/json' }),
        json: async () => ({ data: 'test' }),
      });

      const { result } = renderHook(() => useApi());

      // Act
      await act(async () => {
        await result.current.get('/api/test');
      });

      // Assert
      expect(result.current.loading).toBe(false);
    });

    it('resets loading state after failed request', async () => {
      // Arrange
      (global.fetch as any).mockRejectedValueOnce(new Error('Failed'));

      const { result } = renderHook(() => useApi());

      // Act
      await act(async () => {
        await result.current.get('/api/test');
      });

      // Assert
      expect(result.current.loading).toBe(false);
    });
  });
});
