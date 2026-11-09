/**
 * Links between docs: `other-doc.md#section` (as written in src/docs, which
 * works on GitHub) opens /user-docs/<key>#section in the app, in the same tab.
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import MarkdownViewer from '@/components/ui/markdown-viewer';
import { docFileKeys, resolveDocHref } from './doc-links';

const FILES = docFileKeys({
  'user-guide': { file: 'USER-GUIDE.md' },
  'compliance-dsl-reference': { file: 'compliance-dsl-reference.md' },
});

describe('resolveDocHref', () => {
  it('maps a doc file name to its key, keeping the section', () => {
    expect(resolveDocHref('compliance-dsl-reference.md#tag-functions', FILES)).toBe(
      '/user-docs/compliance-dsl-reference#tag-functions',
    );
    expect(resolveDocHref('./USER-GUIDE.md', FILES)).toBe('/user-docs/user-guide');
    expect(resolveDocHref('/user-docs/user-guide#roles', FILES)).toBe('/user-docs/user-guide#roles');
  });

  it('leaves other links alone', () => {
    expect(resolveDocHref('README.md', FILES)).toBeUndefined();
    expect(resolveDocHref('https://example.com/x.md', FILES)).toBeUndefined();
    expect(resolveDocHref('#local-section', FILES)).toBeUndefined();
    expect(resolveDocHref('/api/docs', FILES)).toBeUndefined();
    expect(resolveDocHref(undefined, FILES)).toBeUndefined();
  });
});

describe('MarkdownViewer links between docs', () => {
  it('opens a link to another doc in the same tab, through the app router', () => {
    const navigate = vi.fn();
    render(
      <MarkdownViewer
        markdown="See the [DSL reference](compliance-dsl-reference.md#tag-functions) and [Databricks](https://databricks.com)."
        resolveLink={(href) => resolveDocHref(href, FILES)}
        onNavigate={navigate}
      />,
    );

    const doc = screen.getByRole('link', { name: 'DSL reference' });
    expect(doc).toHaveAttribute('href', '/user-docs/compliance-dsl-reference#tag-functions');
    expect(doc).not.toHaveAttribute('target');
    fireEvent.click(doc);
    expect(navigate).toHaveBeenCalledWith('/user-docs/compliance-dsl-reference#tag-functions');

    expect(screen.getByRole('link', { name: 'Databricks' })).toHaveAttribute('target', '_blank');
  });
});
