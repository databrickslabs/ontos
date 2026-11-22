import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { usePersistentState } from './use-persistent-state';

beforeEach(() => localStorage.clear());

describe('usePersistentState', () => {
  it('returns the initial value when nothing is stored', () => {
    const { result } = renderHook(() => usePersistentState('pst-empty', false));
    expect(result.current[0]).toBe(false);
  });

  it('writes changes to localStorage and restores them on a new mount', () => {
    const first = renderHook(() => usePersistentState('pst-roundtrip', false));
    act(() => first.result.current[1](true));
    expect(JSON.parse(localStorage.getItem('pst-roundtrip') ?? 'null')).toBe(true);
    first.unmount();

    const second = renderHook(() => usePersistentState('pst-roundtrip', false));
    expect(second.result.current[0]).toBe(true);
  });

  it('round-trips objects', () => {
    localStorage.setItem('pst-object', JSON.stringify({ pageIndex: 2, pageSize: 20 }));
    const { result } = renderHook(() => usePersistentState('pst-object', { pageIndex: 0, pageSize: 10 }));
    expect(result.current[0]).toEqual({ pageIndex: 2, pageSize: 20 });
  });

  it('falls back to the initial value when the stored value fails the validator', () => {
    const isPage = (v: unknown): v is { pageIndex: number } =>
      typeof v === 'object' && v !== null && typeof (v as { pageIndex?: unknown }).pageIndex === 'number';
    localStorage.setItem('pst-invalid', 'null');
    const { result } = renderHook(() => usePersistentState('pst-invalid', { pageIndex: 0 }, isPage));
    expect(result.current[0]).toEqual({ pageIndex: 0 });
  });

  it('falls back to the initial value when the stored entry is corrupt', () => {
    localStorage.setItem('pst-corrupt', '{not json');
    const { result } = renderHook(() => usePersistentState('pst-corrupt', 'fallback'));
    expect(result.current[0]).toBe('fallback');
  });
});
