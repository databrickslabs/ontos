/**
 * Turns a selected tag into what the tag-saving APIs accept (`tags:set`, and the
 * `tags` field of products, contracts, projects, teams and domains).
 *
 * A tag picked in the TagSelector is a bare FQN string. A tag that was already
 * assigned is an object with its `assigned_value`; it is sent with that value, so
 * saving doesn't depend on the backend keeping it (#1420).
 */
export type SelectedTag =
  | string
  | {
      fully_qualified_name?: string;
      tag_id?: string;
      id?: string;
      assigned_value?: string | null;
    };

export type TagAssignment = string | { tag_fqn?: string; tag_id?: string; assigned_value?: string };

export function toTagAssignment(tag: SelectedTag): TagAssignment {
  if (typeof tag === 'string') return tag;
  const value = tag.assigned_value ?? undefined;
  const fqn = tag.fully_qualified_name;
  if (fqn && value === undefined) return fqn;
  const ref = fqn ? { tag_fqn: fqn } : { tag_id: tag.tag_id ?? tag.id };
  return value === undefined ? ref : { ...ref, assigned_value: value };
}

export function toTagAssignments(tags: SelectedTag[] | null | undefined): TagAssignment[] {
  return (tags ?? []).map(toTagAssignment);
}
