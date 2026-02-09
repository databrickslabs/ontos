import { useState, useRef, useEffect, useMemo } from 'react';
import { Input } from '@/components/ui/input';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Search, X } from 'lucide-react';
import {
  type GraphData,
  type GraphNode,
  getColorForType,
  ChangeStatus,
} from '@/types/graph-explorer';
import { cn } from '@/lib/utils';

interface NodeSearchProps {
  graphData: GraphData;
  onNodeSelect: (nodeId: string) => void;
  disabled?: boolean;
}

interface SearchResult {
  node: GraphNode;
  matchReason: string;
  matchScore: number;
}

export default function NodeSearch({
  graphData,
  onNodeSelect,
  disabled = false,
}: NodeSearchProps) {
  const [query, setQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Derive search results from query + graphData (no useEffect needed)
  const results = useMemo<SearchResult[]>(() => {
    if (!query.trim()) return [];

    const lowerQuery = query.toLowerCase();
    const matches: SearchResult[] = [];

    graphData.nodes.forEach((node) => {
      let matchReason = '';
      let matchScore = 0;

      if (node.label.toLowerCase().includes(lowerQuery)) {
        matchReason = 'Label';
        matchScore = 10;
      }

      if (node.type.toLowerCase().includes(lowerQuery)) {
        matchReason = matchReason ? `${matchReason}, Type` : 'Type';
        matchScore += 5;
      }

      const propertyMatches = Object.entries(node.properties).filter(([_key, value]) => {
        const valueStr = String(value || '').toLowerCase();
        return valueStr.includes(lowerQuery);
      });

      if (propertyMatches.length > 0) {
        matchReason = matchReason
          ? `${matchReason}, Properties`
          : `Properties (${propertyMatches.length})`;
        matchScore += 2;
      }

      if (node.id.toLowerCase() === lowerQuery) {
        matchReason = 'ID';
        matchScore = 20;
      } else if (node.id.toLowerCase().includes(lowerQuery)) {
        matchReason = matchReason ? `${matchReason}, ID` : 'ID';
        matchScore += 3;
      }

      if (matchScore > 0) {
        matches.push({ node, matchReason, matchScore });
      }
    });

    return matches
      .sort((a, b) => b.matchScore - a.matchScore)
      .slice(0, 10);
  }, [query, graphData]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setQuery(e.target.value);
  };

  const handleClear = () => {
    setQuery('');
    setIsOpen(false);
    inputRef.current?.focus();
  };

  const handleNodeClick = (nodeId: string) => {
    onNodeSelect(nodeId);
    setQuery('');
    setIsOpen(false);
  };

  const handleBlur = () => {
    // Delay closing to allow click events to fire
    timeoutRef.current = setTimeout(() => {
      setIsOpen(false);
    }, 200);
  };

  const handleFocus = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (query.trim() && results.length > 0) {
      setIsOpen(true);
    }
  };

  const handleResultClick = (nodeId: string) => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    handleNodeClick(nodeId);
  };

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return (
    <div className="relative w-full">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          ref={inputRef}
          type="text"
          placeholder="Search nodes by label, type, or properties..."
          value={query}
          onChange={handleInputChange}
          onFocus={handleFocus}
          onBlur={handleBlur}
          disabled={disabled}
          className="pl-9 pr-9"
        />
        {query && (
          <button
            onClick={handleClear}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Dropdown Results */}
      {isOpen && results.length > 0 && (
        <Card
          ref={dropdownRef}
          className="absolute z-50 mt-2 w-full max-h-80 overflow-hidden shadow-lg"
        >
          <div className="max-h-80 overflow-y-auto p-2">
            {results.map((result) => {
              const color = getColorForType(result.node.type);
              const isNew = result.node.status === ChangeStatus.NEW;
              return (
                <div
                  key={result.node.id}
                  onClick={() => handleResultClick(result.node.id)}
                  className={cn(
                    'flex items-center gap-3 rounded-md p-2 cursor-pointer transition-colors',
                    'hover:bg-accent'
                  )}
                >
                  {/* Node Icon */}
                  <div
                    className="h-8 w-8 rounded-full border-2 flex-shrink-0"
                    style={{
                      backgroundColor: color,
                      borderColor: color,
                    }}
                  />

                  {/* Node Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm truncate">
                        {result.node.label}
                      </span>
                      {isNew && (
                        <Badge variant="secondary" className="text-xs">
                          New
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <Badge variant="outline" className="text-xs">
                        {result.node.type}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        {result.matchReason}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}
