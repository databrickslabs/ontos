import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import {
  complianceHiddenResultsText,
  complianceRunCoverageText,
  complianceRunScoreText,
  complianceScoreColor,
} from './compliance-run-warning';

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('complianceRunScoreText', () => {
  it('shows the score of a run that has one', () => {
    expect(complianceRunScoreText(i18n.t, { score: 85.5 })).toBe('85.5%');
    expect(complianceRunScoreText(i18n.t, { score: 0 })).toBe('0%');
  });

  it('shows "no score", not 0 %, for a run without one', async () => {
    expect(complianceRunScoreText(i18n.t, { score: null })).toBe('No score');
    await i18n.changeLanguage('pt');
    expect(complianceRunScoreText(i18n.t, {})).toBe('Sem pontuação');
  });
});

describe('complianceRunCoverageText', () => {
  it('says how many objects the score is measured on', () => {
    const text = complianceRunCoverageText(i18n.t, {
      coverage: { evaluated: 50, not_evaluated: 4950 },
    });

    expect(text).toContain('50 of 5000 objects evaluated');
  });

  it('is empty when every object was evaluated, or without coverage', () => {
    expect(complianceRunCoverageText(i18n.t, { coverage: { evaluated: 3, not_evaluated: 0 } }))
      .toBe('');
    expect(complianceRunCoverageText(i18n.t, {})).toBe('');
  });
});

describe('complianceHiddenResultsText', () => {
  it('counts the results on objects the viewer cannot read', () => {
    expect(complianceHiddenResultsText(i18n.t, 2)).toContain('2 results');
    expect(complianceHiddenResultsText(i18n.t, 0)).toBe('');
    expect(complianceHiddenResultsText(i18n.t, undefined)).toBe('');
  });
});

describe('complianceScoreColor', () => {
  it('colors a score by its band and leaves no score muted, not red', () => {
    expect(complianceScoreColor(95)).toContain('green');
    expect(complianceScoreColor(70)).toContain('yellow');
    expect(complianceScoreColor(0)).toContain('red');
    expect(complianceScoreColor(null)).toBe('text-muted-foreground');
    expect(complianceScoreColor(undefined)).toBe('text-muted-foreground');
  });
});
