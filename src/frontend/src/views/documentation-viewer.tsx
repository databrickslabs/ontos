import { useEffect, useState, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { BookOpenCheck, ChevronRight } from 'lucide-react';
import MarkdownViewer from '@/components/ui/markdown-viewer';
import { Alert, AlertDescription } from '@/components/ui/alert';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { DocViewerSkeleton } from '@/components/common/list-view-skeleton';

// Helper function to slugify text for anchor IDs
function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-');
}

// Build table of contents from markdown headings
function buildToc(markdown: string) {
  const lines = markdown.split(/\r?\n/);
  const headings: { level: number; text: string; id: string }[] = [];
  for (const line of lines) {
    const m = /^(#{1,3})\s+(.*)$/.exec(line);
    if (m) {
      const level = m[1].length;
      const text = m[2].trim();
      const id = slugify(text);
      headings.push({ level, text, id });
    }
  }
  return headings;
}

export default function DocumentationViewer() {
  useTranslation('common');
  const { docName } = useParams<{ docName: string }>();
  const [markdown, setMarkdown] = useState<string>('');
  const [title, setTitle] = useState<string>('Documentation');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<string>('');
  
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  // Set breadcrumb
  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle(title);
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [setStaticSegments, setDynamicTitle, title]);

  // Fetch documentation content
  useEffect(() => {
    if (!docName) {
      setError('No document specified');
      setLoading(false);
      return;
    }

    const fetchDoc = async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await fetch(`/api/user-docs/${docName}`);
        if (!response.ok) {
          throw new Error(`Failed to load documentation: ${response.statusText}`);
        }
        const data = await response.json();
        setMarkdown(data.content || '');
        setTitle(data.title || 'Documentation');
      } catch (err) {
        console.error('Error loading documentation:', err);
        setError(err instanceof Error ? err.message : 'Failed to load documentation');
      } finally {
        setLoading(false);
      }
    };

    fetchDoc();
  }, [docName]);

  // Build table of contents
  const toc = useMemo(() => buildToc(markdown), [markdown]);

  // Track active section on scroll
  useEffect(() => {
    if (toc.length === 0) return;

    const handleScroll = () => {
      const scrollPosition = window.scrollY + 100; // Offset for header
      
      // Find the current section
      for (let i = toc.length - 1; i >= 0; i--) {
        const element = document.getElementById(toc[i].id);
        if (element && element.offsetTop <= scrollPosition) {
          setActiveSection(toc[i].id);
          break;
        }
      }
    };

    window.addEventListener('scroll', handleScroll);
    handleScroll(); // Call once on mount
    
    return () => window.removeEventListener('scroll', handleScroll);
  }, [toc]);

  // Smooth scroll to section
  const scrollToSection = (id: string) => {
    const element = document.getElementById(id);
    if (element) {
      const offset = 80; // Account for fixed header
      const elementPosition = element.getBoundingClientRect().top + window.scrollY;
      window.scrollTo({
        top: elementPosition - offset,
        behavior: 'smooth'
      });
    }
  };

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="flex items-center gap-3 mb-6">
          <BookOpenCheck className="w-8 h-8" />
          <h1 className="text-4xl font-bold">{title}</h1>
        </div>
        <DocViewerSkeleton showTitle={false} proseRows={14} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="flex items-center gap-3 mb-6">
          <BookOpenCheck className="w-8 h-8" />
          <h1 className="text-4xl font-bold">{title}</h1>
        </div>
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex items-center gap-3 mb-6">
        <BookOpenCheck className="w-8 h-8" />
        <h1 className="text-4xl font-bold">{title}</h1>
      </div>

      <div className="flex gap-8 items-start relative">
        {/* Table of Contents Sidebar */}
        {toc.length > 0 && (
          <aside className="hidden lg:block w-64 shrink-0">
            <div className="sticky top-24 rounded-lg border bg-card p-4 shadow-sm">
              <div className="text-xs uppercase tracking-wider font-semibold text-muted-foreground mb-3">
                Table of Contents
              </div>
              <nav className="space-y-0.5">
                {toc.map((heading, idx) => (
                  <button
                    key={idx}
                    onClick={() => scrollToSection(heading.id)}
                    className={`
                      text-left w-full text-sm hover:text-primary transition-colors py-1.5 px-2 rounded
                      ${activeSection === heading.id ? 'text-primary font-semibold bg-primary/10' : 'text-muted-foreground hover:bg-muted/50'}
                      ${heading.level === 1 ? 'pl-2 font-medium' : heading.level === 2 ? 'pl-6' : heading.level === 3 ? 'pl-10' : 'pl-14'}
                    `}
                  >
                    <div className="flex items-center gap-2">
                      {activeSection === heading.id && (
                        <ChevronRight className="w-3.5 h-3.5 shrink-0" />
                      )}
                      <span className={activeSection !== heading.id && heading.level === 1 ? 'ml-[1.125rem]' : ''}>
                        {heading.text}
                      </span>
                    </div>
                  </button>
                ))}
              </nav>
            </div>
          </aside>
        )}

        {/* Main Content */}
        <div className="flex-1 min-w-0">
          <div className="max-w-4xl">
            <MarkdownViewer markdown={markdown} />
          </div>
        </div>
      </div>
    </div>
  );
}

