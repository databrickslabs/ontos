/**
 * Tags in entity create/update payloads (data products, data contracts).
 *
 * On update, `tags` replaces the entity's tags: `[]` removes them all and a
 * missing field keeps them (#1435). So an edit sends tags only when the user
 * changed the selection; that also keeps tags a workflow changed while the
 * dialog was open. Loaded tags go by FQN, without their value: the backend
 * keeps the stored value of a tag that stays (#1420).
 */

export type TagSelection = string | {
  tag_id?: string;
  fully_qualified_name?: string;
  tag_name?: string;
  assigned_value?: string | null;
};

export type TagPayloadItem = string | { tag_id?: string; assigned_value?: string | null };

function tagKey(tag: TagSelection): string {
  if (typeof tag === 'string') return tag;
  return tag.fully_qualified_name || tag.tag_id || tag.tag_name || '';
}

export function normalizeTagsForPayload(tags: TagSelection[] | undefined | null): TagPayloadItem[] {
  return (tags || []).map((tag) => {
    if (typeof tag === 'string') return tag;
    return tag.fully_qualified_name || { tag_id: tag.tag_id, assigned_value: tag.assigned_value };
  });
}

/** Tags for an update: the new selection if it differs from the loaded one, otherwise undefined. */
export function tagsForUpdate(
  current: TagSelection[] | undefined | null,
  initial: TagSelection[] | undefined | null,
): TagPayloadItem[] | undefined {
  const before = new Set((initial || []).map(tagKey));
  const after = new Set((current || []).map(tagKey));
  const unchanged = before.size === after.size && [...after].every((key) => before.has(key));
  return unchanged ? undefined : normalizeTagsForPayload(current);
}

/** Tags for a create: omitted when none are selected. */
export function tagsForCreate(current: TagSelection[] | undefined | null): TagPayloadItem[] | undefined {
  const normalized = normalizeTagsForPayload(current);
  return normalized.length > 0 ? normalized : undefined;
}
