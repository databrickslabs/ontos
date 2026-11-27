import { describe, expect, it } from 'vitest';
import { connectorErrorText } from './connector-error-text';

describe('connectorErrorText', () => {
  it('uses the translation for a known code', () => {
    const t = (key: string, options?: { defaultValue?: string }) =>
      key === 'settings:connectors.errorCodes.tableau_unreachable' ? 'Tableau nicht erreichbar' : options?.defaultValue ?? key;
    expect(connectorErrorText(t, 'tableau_unreachable', 'Fallback')).toBe('Tableau nicht erreichbar');
  });

  it('falls back when there is no code', () => {
    const t = (_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? '';
    expect(connectorErrorText(t, null, 'Fallback')).toBe('Fallback');
    expect(connectorErrorText(t, '', 'Fallback')).toBe('Fallback');
  });

  it('passes the fallback as default for an unknown code', () => {
    const seen: Array<[string, string | undefined]> = [];
    const t = (key: string, options?: { defaultValue?: string }) => {
      seen.push([key, options?.defaultValue]);
      return options?.defaultValue ?? key;
    };
    expect(connectorErrorText(t, 'made_up', 'Fallback')).toBe('Fallback');
    expect(seen).toEqual([['settings:connectors.errorCodes.made_up', 'Fallback']]);
  });
});
