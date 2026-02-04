import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface MarkdownViewerProps {
  markdown: string;
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-');
}

function extractText(children: React.ReactNode): string {
  const parts: string[] = [];
  React.Children.forEach(children, (child) => {
    if (typeof child === 'string') {
      parts.push(child);
    } else if (typeof child === 'number') {
      parts.push(String(child));
    } else if (React.isValidElement(child)) {
      parts.push(extractText(child.props.children));
    }
  });
  return parts.join(' ');
}

const MarkdownViewer: React.FC<MarkdownViewerProps> = ({ markdown }) => {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ children }) => {
          const id = slugify(extractText(children));
          return (
            <h1
              id={id}
              className="scroll-mt-24 text-3xl font-bold tracking-tight text-foreground mt-8 mb-4 first:mt-0"
            >
              {children}
            </h1>
          );
        },
        h2: ({ children }) => {
          const id = slugify(extractText(children));
          return (
            <h2
              id={id}
              className="scroll-mt-24 text-2xl font-semibold tracking-tight text-foreground mt-6 mb-3"
            >
              {children}
            </h2>
          );
        },
        h3: ({ children }) => {
          const id = slugify(extractText(children));
          return (
            <h3
              id={id}
              className="scroll-mt-24 text-xl font-semibold tracking-tight text-foreground mt-5 mb-2"
            >
              {children}
            </h3>
          );
        },
        h4: ({ children }) => {
          const id = slugify(extractText(children));
          return (
            <h4
              id={id}
              className="scroll-mt-24 text-lg font-semibold text-foreground mt-4 mb-2"
            >
              {children}
            </h4>
          );
        },
        h5: ({ children }) => {
          const id = slugify(extractText(children));
          return (
            <h5
              id={id}
              className="scroll-mt-24 text-base font-semibold text-foreground mt-3 mb-2"
            >
              {children}
            </h5>
          );
        },
        h6: ({ children }) => {
          const id = slugify(extractText(children));
          return (
            <h6
              id={id}
              className="scroll-mt-24 text-sm font-semibold text-muted-foreground uppercase tracking-wide mt-3 mb-2"
            >
              {children}
            </h6>
          );
        },
        p: ({ children }) => (
          <p className="text-base leading-7 text-foreground mb-4 [&:not(:first-child)]:mt-4">
            {children}
          </p>
        ),
        ul: ({ children }) => (
          <ul className="list-disc list-outside pl-6 my-4 space-y-2 text-foreground">
            {children}
          </ul>
        ),
        ol: ({ children }) => (
          <ol className="list-decimal list-outside pl-6 my-4 space-y-2 text-foreground">
            {children}
          </ol>
        ),
        li: ({ children }) => (
          <li className="text-base leading-7">
            {children}
          </li>
        ),
        hr: () => (
          <hr className="my-8 border-t border-border" />
        ),
        a: ({ children, href }) => {
          const isInternalAnchor = href?.startsWith('#');
          const handleClick = isInternalAnchor
            ? (e: React.MouseEvent) => {
                e.preventDefault();
                const id = href?.slice(1) ?? '';
                const element = document.getElementById(id);
                if (element) {
                  const offset = 80;
                  const elementPosition = element.getBoundingClientRect().top + window.scrollY;
                  window.scrollTo({
                    top: elementPosition - offset,
                    behavior: 'smooth'
                  });
                  // Update URL without triggering navigation
                  window.history.pushState(null, '', href);
                }
              }
            : undefined;
          return (
            <a
              href={href}
              onClick={handleClick}
              className="text-primary font-medium underline underline-offset-4 decoration-primary/30 hover:decoration-primary transition-colors"
              {...(!isInternalAnchor && { target: '_blank', rel: 'noopener noreferrer' })}
            >
              {children}
            </a>
          );
        },
        img: ({ src, alt }) => (
          <div className="my-8">
            <img
              src={src as string}
              alt={alt as string}
              className="max-w-full h-auto mx-auto rounded-lg border border-border shadow-md"
            />
            {alt && (
              <p className="text-sm text-muted-foreground text-center mt-2 italic">
                {alt}
              </p>
            )}
          </div>
        ),
        code: ({ children, className }) => {
          // className is set for fenced code blocks (e.g., "language-plaintext")
          // but not for inline code
          const isBlock = Boolean(className);
          
          if (isBlock) {
            // For fenced code blocks, minimal styling - container handled by <pre>
            return (
              <code className="font-mono text-sm text-foreground whitespace-pre block">
                {children}
              </code>
            );
          }
          
          // For inline code, apply the styled box
          return (
            <code className="relative rounded bg-muted px-[0.4rem] py-[0.2rem] font-mono text-sm font-medium text-foreground border border-border/50">
              {children}
            </code>
          );
        },
        pre: ({ children }) => (
          <pre className="my-4 overflow-x-auto rounded-lg border border-border bg-muted/50 p-4">
            {children}
          </pre>
        ),
        blockquote: ({ children }) => (
          <blockquote className="my-6 border-l-4 border-primary/30 bg-muted/30 pl-6 py-2 italic text-muted-foreground">
            {children}
          </blockquote>
        ),
        table: ({ children }) => (
          <div className="my-6 w-full overflow-x-auto rounded-lg border border-border shadow-sm">
            <table className="w-full border-collapse text-sm">
              {children}
            </table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-muted/50 border-b-2 border-border">
            {children}
          </thead>
        ),
        tbody: ({ children }) => (
          <tbody className="divide-y divide-border">
            {children}
          </tbody>
        ),
        tr: ({ children }) => (
          <tr className="transition-colors hover:bg-muted/30">
            {children}
          </tr>
        ),
        th: ({ children }) => (
          <th className="text-left px-4 py-3 font-semibold text-foreground">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="px-4 py-3 align-top text-foreground">
            {children}
          </td>
        ),
        em: ({ children }) => (
          <em className="italic text-muted-foreground">
            {children}
          </em>
        ),
        strong: ({ children }) => (
          <strong className="font-semibold text-foreground">
            {children}
          </strong>
        ),
      }}
    >
      {markdown}
    </ReactMarkdown>
  );
};

export default MarkdownViewer; 