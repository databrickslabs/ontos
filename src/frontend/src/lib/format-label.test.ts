import { describe, it, expect } from 'vitest';
import { formatFieldLabel } from './format-label';

describe('formatFieldLabel', () => {
  it('returns an empty string for falsy input', () => {
    expect(formatFieldLabel('')).toBe('');
    expect(formatFieldLabel(null)).toBe('');
    expect(formatFieldLabel(undefined)).toBe('');
  });

  describe('English (title case)', () => {
    it('capitalizes words and lowercases minor words (except first)', () => {
      expect(formatFieldLabel('owner of the dataset', 'en')).toBe('Owner of the Dataset');
    });

    it('capitalizes a minor word when it is the first word', () => {
      expect(formatFieldLabel('the owner')).toBe('The Owner');
    });

    it('preserves acronyms', () => {
      expect(formatFieldLabel('API endpoint', 'en')).toBe('API Endpoint');
    });

    it('defaults to English when no locale is supplied', () => {
      expect(formatFieldLabel('data product')).toBe('Data Product');
    });
  });

  describe('other Latin-script locales (sentence case)', () => {
    it('capitalizes only the first word', () => {
      expect(formatFieldLabel('owner of the dataset', 'de')).toBe('Owner of the dataset');
    });

    it('strips the regional suffix from the locale', () => {
      expect(formatFieldLabel('hello world', 'fr-FR')).toBe('Hello world');
    });

    it('preserves acronyms in sentence case too', () => {
      expect(formatFieldLabel('the API spec', 'es')).toBe('The API spec');
    });
  });

  describe('CJK locales (no transformation)', () => {
    it('returns the label unchanged', () => {
      expect(formatFieldLabel('オーナー', 'ja')).toBe('オーナー');
      expect(formatFieldLabel('owner', 'zh')).toBe('owner');
      expect(formatFieldLabel('owner', 'ko')).toBe('owner');
    });
  });
});
