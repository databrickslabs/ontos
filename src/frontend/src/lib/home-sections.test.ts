import { describe, it, expect } from 'vitest';
import { HomeSection } from '@/types/settings';
import { homeSectionBlocked, normalizeHomeSections } from './home-sections';

const { JOURNEY, DISCOVERY, DATA_CURATION } = HomeSection;

describe('home sections in the role editor', () => {
  it('blocks the journey while another section is selected', () => {
    expect(homeSectionBlocked([DISCOVERY], JOURNEY)).toBe(true);
    expect(homeSectionBlocked([], JOURNEY)).toBe(false);
  });

  it('blocks the other sections while the journey is selected', () => {
    expect(homeSectionBlocked([JOURNEY], DISCOVERY)).toBe(true);
    expect(homeSectionBlocked([JOURNEY], DATA_CURATION)).toBe(true);
  });

  it('keeps the other sections combinable', () => {
    expect(homeSectionBlocked([DISCOVERY], DATA_CURATION)).toBe(false);
  });

  it('lets a role saved with both unselect either one', () => {
    expect(homeSectionBlocked([JOURNEY, DISCOVERY], JOURNEY)).toBe(false);
    expect(homeSectionBlocked([JOURNEY, DISCOVERY], DISCOVERY)).toBe(false);
  });

  it('reads the form value as a list', () => {
    expect(normalizeHomeSections(false)).toEqual([]);
    expect(normalizeHomeSections('JOURNEY')).toEqual([JOURNEY]);
    expect(normalizeHomeSections([DISCOVERY])).toEqual([DISCOVERY]);
  });
});
