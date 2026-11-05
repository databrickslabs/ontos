import type { DocumentItem } from '@/hooks/use-entity-metadata';

// Replace image references in markdown to target our document content endpoint.
// Supports: ![alt](doc:ID) or ![alt](file:filename.ext)
export function rewriteImageLinks(markdown: string, documents: DocumentItem[]): string {
  if (!markdown) return markdown;

  const byId = new Map(documents.map(d => [String(d.id), d]));
  const byName = new Map(documents.map(d => [d.original_filename, d]));

  const replaceUrl = (url: string): string => {
    if (url.startsWith('doc:')) {
      const id = url.slice(4);
      if (byId.has(id)) return `/api/documents/${id}/content`;
    }
    if (url.startsWith('file:')) {
      const name = url.slice(5);
      const doc = byName.get(name);
      if (doc) return `/api/documents/${doc.id}/content`;
    }
    return url;
  };

  let out = markdown.replace(/!\[[^\]]*\]\(([^)]+)\)/g, (m, p1) => m.replace(p1, replaceUrl(p1)));
  out = out.replace(/\[[^\]]*\]\(([^)]+)\)/g, (m, p1) => m.replace(p1, replaceUrl(p1)));
  return out;
}
