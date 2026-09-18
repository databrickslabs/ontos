import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Input } from './input';
import { Button } from './button';
import { Card } from './card';
import { ScrollArea } from './scroll-area';
import {
  Search, FileText, Database, Book, Shield, Loader2,
  BookOpen, Shapes, Tag, Send, Server, Table2, Eye, Columns2,
  LayoutDashboard, Globe, FileCode, Brain, Activity, Package,
} from 'lucide-react';
import { features } from '@/config/features';
import { cn } from '@/lib/utils';

interface SearchResult {
  id: string;
  type: string; // backend may return additional types (e.g., 'data-domain', 'data-asset-review')
  title: string;
  description: string;
  link: string;
  feature_id?: string; // map to features.ts for icon rendering
  tags?: string[];
}

interface SearchBarProps {
  variant?: 'default' | 'large';
  placeholder?: string;
}

export default function SearchBar({ variant = 'default', placeholder }: SearchBarProps) {
  const { t } = useTranslation('common');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    const search = async () => {
      if (!query.trim()) {
        setResults([]);
        return;
      }

      setIsLoading(true);
      try {
        const response = await fetch(`/api/search?search_term=${encodeURIComponent(query)}`);
        if (!response.ok) {
          let errorDetails = await response.text();
          try {
            const errorJson = JSON.parse(errorDetails);
            errorDetails = errorJson.detail || errorDetails;
          } catch (parseError) {
            // Ignore if not JSON
          }
          throw new Error(`API Error: ${response.status} ${response.statusText} - ${errorDetails}`);
        }
        const data = await response.json();
        setResults(Array.isArray(data) ? data : []);
      } catch (error) {
        console.error('Search error:', error);
        setResults([]);
      } finally {
        setIsLoading(false);
      }
    };

    const debounceTimer = setTimeout(search, 300);
    return () => clearTimeout(debounceTimer);
  }, [query]);

  const getIcon = (result: SearchResult) => {
    // Prefer explicit feature-based icon mapping to keep UI consistent with navigation
    if (result.feature_id) {
      const feature = features.find((f) => f.id === result.feature_id);
      if (feature) {
        const Icon = feature.icon;
        return <Icon className="h-4 w-4" />;
      }
    }

    const ASSET_TYPE_ICONS: Record<string, React.ElementType> = {
      'asset-business-term': BookOpen,
      'asset-logical-entity': Shapes,
      'asset-logical-attribute': Tag,
      'asset-delivery-channel': Send,
      'asset-system': Server,
      'asset-dataset': Database,
      'asset-table': Table2,
      'asset-view': Eye,
      'asset-column': Columns2,
      'asset-dashboard': LayoutDashboard,
      'asset-api-endpoint': Globe,
      'asset-notebook': FileCode,
      'asset-ml-model': Brain,
      'asset-stream': Activity,
      'asset-policy': Shield,
    };

    if (result.type.startsWith('asset-')) {
      const AssetIcon = ASSET_TYPE_ICONS[result.type] || Package;
      return <AssetIcon className="h-4 w-4" />;
    }

    switch (result.type) {
      case 'data-product':
        return <Database className="h-4 w-4" />;
      case 'data-contract':
        return <FileText className="h-4 w-4" />;
      case 'glossary-term':
        return <Book className="h-4 w-4" />;
      case 'persona':
        return <Shield className="h-4 w-4" />;
      default:
        return <Search className="h-4 w-4" />;
    }
  };

  const handleResultClick = (result: SearchResult) => {
    navigate(result.link);
    setIsOpen(false);
  };

  return (
    <div ref={searchRef} className="relative w-full">
      <div className={cn(
        "relative",
        variant === 'large' ? "w-full max-w-2xl mx-auto" : "w-full"
      )}>
        <Input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          placeholder={placeholder ?? t('common:placeholders.search')}
          className={cn(
            "w-full",
            variant === 'large' ? "h-12 text-lg" : "h-10"
          )}
        />
        <div className="absolute right-0 top-0 h-full flex items-center gap-1 pr-2">
          <Button
            variant="ghost"
            size="icon"
            className="hover:bg-transparent"
            title={t('common:actions.search')}
          >
            <Search className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="hover:bg-transparent"
            onClick={() => navigate('/search/llm')}
            title={t('common:tooltips.openAdvancedSearch')}
          >
            {t('header.advanced')}
          </Button>
        </div>
      </div>

      {isOpen && (query.trim() || results.length > 0) && (
        <Card className="absolute z-50 w-full mt-1 shadow-lg">
          <ScrollArea className="h-[300px]">
            {isLoading ? (
              <div className="flex items-center justify-center p-4 gap-2 text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin" />
                <span>{t('common:states.loading')}</span>
              </div>
            ) : results.length > 0 ? (
              <div className="p-2">
                {results.map((result) => (
                  <Button
                    key={result.id}
                    variant="ghost"
                    className="w-full justify-start gap-2 p-2 h-auto"
                    onClick={() => handleResultClick(result)}
                  >
                    {getIcon(result)}
                    <div className="flex flex-col items-start">
                      <span className="font-medium">{result.title}</span>
                      <span className="text-sm text-muted-foreground">{result.description}</span>
                    </div>
                  </Button>
                ))}
              </div>
            ) : (
              <div className="p-4 text-center text-muted-foreground">
                {t('common:placeholders.noResults')}
              </div>
            )}
          </ScrollArea>
        </Card>
      )}
    </div>
  );
} 