import { Dispatch, SetStateAction, useEffect, useState } from 'react';

/**
 * useState that mirrors its value to localStorage under `key`. Missing, corrupt or
 * (when `isValid` is given) wrongly shaped entries fall back to `initial`.
 */
export function usePersistentState<T>(
  key: string,
  initial: T,
  isValid?: (value: unknown) => value is T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw === null) return initial;
      const parsed: unknown = JSON.parse(raw);
      return !isValid || isValid(parsed) ? (parsed as T) : initial;
    } catch {
      return initial;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Storage full or unavailable: the view still works, it just is not restored.
    }
  }, [key, value]);

  return [value, setValue];
}
