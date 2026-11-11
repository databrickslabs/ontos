import { describe, it, expect } from 'vitest';
import { safeDecodeURIComponent } from './safe-decode';

describe('safeDecodeURIComponent', () => {
  it('decodes valid percent-encoding', () => {
    expect(safeDecodeURIComponent('tag%20functions')).toBe('tag functions');
    expect(safeDecodeURIComponent('%C3%A9')).toBe('é');
  });

  it('returns the raw value when the encoding is malformed', () => {
    expect(safeDecodeURIComponent('%E0%A4%A')).toBe('%E0%A4%A');
    expect(safeDecodeURIComponent('100%')).toBe('100%');
  });

  it('returns an empty string for empty input', () => {
    expect(safeDecodeURIComponent('')).toBe('');
  });
});
