import { describe, expect, it } from 'vitest';
import { normalizeTagsForPayload, omitTags, tagsForCreate, tagsForUpdate } from './tag-payload';

const loaded = (fqn: string, value: string | null = null) => ({
  tag_id: `id-${fqn}`, fully_qualified_name: fqn, assigned_value: value,
});

describe('normalizeTagsForPayload', () => {
  it('sends loaded tags by FQN and keeps plain strings', () => {
    expect(normalizeTagsForPayload([loaded('ns/a', 'x'), 'ns/b'])).toEqual(['ns/a', 'ns/b']);
  });

  it('falls back to the tag id when a tag has no FQN', () => {
    expect(normalizeTagsForPayload([{ tag_id: 't1', assigned_value: 'v' }])).toEqual([
      { tag_id: 't1', assigned_value: 'v' },
    ]);
  });
});

describe('tagsForUpdate', () => {
  it('sends an empty list when the user removed every tag (#1435)', () => {
    expect(tagsForUpdate([], [loaded('ns/a')])).toEqual([]);
  });

  it('leaves tags out when they were not changed', () => {
    expect(tagsForUpdate([loaded('ns/a', 'x')], [loaded('ns/a', 'x')])).toBeUndefined();
  });

  it('treats a re-selected tag as unchanged whatever form it is in', () => {
    expect(tagsForUpdate(['ns/b', 'ns/a'], [loaded('ns/a'), loaded('ns/b')])).toBeUndefined();
  });

  it('sends the new set when a tag was added or removed', () => {
    expect(tagsForUpdate([loaded('ns/a'), 'ns/c'], [loaded('ns/a'), loaded('ns/b')])).toEqual(['ns/a', 'ns/c']);
  });

  it('compares a tag known only by name the same way', () => {
    expect(tagsForUpdate([{ tag_name: 'pii' }], [{ tag_name: 'pii' }])).toBeUndefined();
    expect(tagsForUpdate([], [{ tag_name: 'pii' }])).toEqual([]);
  });

  it('leaves tags out when the entity had none and still has none', () => {
    expect(tagsForUpdate([], [])).toBeUndefined();
    expect(tagsForUpdate([], undefined)).toBeUndefined();
  });
});

describe('tagsForCreate', () => {
  it('omits an empty selection on create', () => {
    expect(tagsForCreate([])).toBeUndefined();
    expect(tagsForCreate(['ns/a'])).toEqual(['ns/a']);
  });
});

describe('omitTags', () => {
  it('drops tags so a whole-entity PUT keeps the stored tags (#1435)', () => {
    const body = omitTags({ id: 'p1', name: 'Port', tags: [loaded('ns/a', 'x')] });
    expect(body).not.toHaveProperty('tags');
    expect(body).toEqual({ id: 'p1', name: 'Port' });
  });

  it('does not drop an empty tag list into the body', () => {
    expect(omitTags({ id: 'p1', tags: [] })).not.toHaveProperty('tags');
  });

  it('leaves the entity it was given unchanged', () => {
    const entity = { id: 'p1', tags: ['ns/a'] };
    omitTags(entity);
    expect(entity.tags).toEqual(['ns/a']);
  });
});
