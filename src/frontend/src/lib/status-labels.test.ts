/**
 * Status values the API sends raw are shown in the user's language: workflow
 * executions (Recent Executions) and asset reviews.
 */
import { afterEach, describe, expect, it } from 'vitest';
import i18n from '@/i18n/config';
import { executionStatusLabel, reviewStatusLabel } from './status-labels';

describe('status labels', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('translates an execution status', async () => {
    expect(executionStatusLabel('failed', i18n.t)).toBe('Failed');
    await i18n.changeLanguage('pt');
    expect(executionStatusLabel('failed', i18n.t)).toBe('Falhou');
    expect(executionStatusLabel('succeeded', i18n.t)).toBe('Concluída');
  });

  it('translates every review request and asset status', async () => {
    await i18n.changeLanguage('pt');
    const statuses = ['queued', 'in_review', 'approved', 'needs_review', 'denied', 'cancelled',
      'pending', 'rejected', 'needs_clarification'];
    for (const status of statuses) {
      expect(reviewStatusLabel(status, i18n.t)).not.toBe(status);
    }
    expect(reviewStatusLabel('queued', i18n.t)).toBe('Na fila');
  });

  it('shows an unknown status as sent', () => {
    expect(executionStatusLabel('archived', i18n.t)).toBe('archived');
    expect(reviewStatusLabel('archived', i18n.t)).toBe('archived');
  });
});
