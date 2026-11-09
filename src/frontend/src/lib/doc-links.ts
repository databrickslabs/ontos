/**
 * Links between the docs served at /user-docs/<key>.
 *
 * The markdown files link to each other by file name (`compliance-dsl-reference.md#tag-functions`),
 * which works on GitHub; in the app the same href pointed to a doc named "<file>.md" in a new tab.
 * docs.yaml maps each file to its key, so such a link resolves to /user-docs/<key>#<anchor>.
 */

/** File name (as in docs.yaml) → doc key, from GET /api/user-docs. */
export type DocFileKeys = Record<string, string>;

export function docFileKeys(docs: Record<string, { file?: string }>): DocFileKeys {
  const keys: DocFileKeys = {};
  for (const [key, doc] of Object.entries(docs)) {
    if (doc.file) keys[doc.file] = key;
  }
  return keys;
}

/**
 * The in-app path of a link to another doc, or undefined for any other link
 * (external URLs, in-page anchors, files that aren't in docs.yaml).
 */
export function resolveDocHref(href: string | undefined, files: DocFileKeys): string | undefined {
  if (!href) return undefined;
  if (href.startsWith('/user-docs/')) return href;
  if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith('/') || href.startsWith('#')) return undefined;
  const [path, anchor] = href.split('#', 2);
  const file = path.replace(/^\.\//, '');
  const key = files[file];
  if (!key) return undefined;
  return anchor ? `/user-docs/${key}#${anchor}` : `/user-docs/${key}`;
}
