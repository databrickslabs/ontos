import { describe, it, expect } from 'vitest';
import type { TFunction } from 'i18next';
import { documentUploadErrorText } from './document-upload-error';

const t = ((key: string, opts?: Record<string, unknown>) =>
  `${key}:${opts?.value}`) as unknown as TFunction;

describe('documentUploadErrorText', () => {
  it('translates volume_invalid with its params', () => {
    const body = JSON.stringify({
      detail: { code: 'volume_invalid', message: 'english', params: { value: 'a.b' } },
    });
    expect(documentUploadErrorText(body, t)).toBe('metadata:documents.messages.volume_invalid:a.b');
  });

  it('keeps any other response text', () => {
    expect(documentUploadErrorText('{"detail":"Failed to upload document"}', t)).toBe(
      '{"detail":"Failed to upload document"}'
    );
    expect(documentUploadErrorText('Bad gateway', t)).toBe('Bad gateway');
  });
});
