import { describe, it, expect, vi } from 'vitest';
import {
  systemRdfNamespaceDisplayLabel,
  SYSTEM_RDF_NAMESPACE_KEY_SET,
} from './system-rdf-namespace-labels';
import { humanizeRdfFilename } from './rdf-filename';

describe('systemRdfNamespaceDisplayLabel', () => {
  // Minimal stand-in for i18next's `t`: echoes the supplied defaultValue.
  const t = ((key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key) as any;

  it('returns the translated default label for a known system key', () => {
    expect(systemRdfNamespaceDisplayLabel('urn:meta:sources', t)).toBe('Source registry metadata');
    expect(systemRdfNamespaceDisplayLabel('urn:semantic-links', t)).toBe('Semantic links');
    expect(systemRdfNamespaceDisplayLabel('urn:x-rdflib:default', t)).toBe('Default graph');
    expect(systemRdfNamespaceDisplayLabel('urn:app-entities', t)).toBe('App Entities');
    expect(systemRdfNamespaceDisplayLabel('urn:demo', t)).toBe('Demo business concepts');
  });

  it('passes the i18n key and default through to t', () => {
    const spy = vi.fn((_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? '');
    systemRdfNamespaceDisplayLabel('urn:demo', spy as any);
    expect(spy).toHaveBeenCalledWith(
      'rdfSources.systemNamespaces.demoGraph',
      expect.objectContaining({ defaultValue: 'Demo business concepts' }),
    );
  });

  it('humanizes an unknown namespace key as a fallback', () => {
    expect(systemRdfNamespaceDisplayLabel('urn:something-else', t)).toBe(
      humanizeRdfFilename('urn:something-else'),
    );
  });
});

describe('SYSTEM_RDF_NAMESPACE_KEY_SET', () => {
  it('contains all known internal namespaces used to filter RDF Sources', () => {
    for (const key of [
      'urn:meta:sources',
      'urn:semantic-links',
      'urn:x-rdflib:default',
      'urn:app-entities',
      'urn:demo',
    ]) {
      expect(SYSTEM_RDF_NAMESPACE_KEY_SET.has(key)).toBe(true);
    }
  });

  it('does not include user-facing taxonomy contexts', () => {
    expect(SYSTEM_RDF_NAMESPACE_KEY_SET.has('urn:taxonomy:foo')).toBe(false);
  });
});
