/**
 * Graph Query Panel
 *
 * Collapsible panel for running Cypher/Gremlin queries against the graph.
 * Queries are translated to SQL via a backend LLM endpoint, executed on
 * Databricks, and the resulting nodes/edges are applied to the graph.
 */

import React, { useState, useCallback, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from '@/components/ui/collapsible';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  Sparkles,
  Play,
  Code2,
  ChevronDown,
  ChevronUp,
  Copy,
  X,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Info,
  AlertTriangle,
  Database,
} from 'lucide-react';
import type { GraphNode, GraphEdge, GraphData } from '@/types/graph-explorer';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type QueryLanguage = 'natural' | 'cypher' | 'gremlin';

interface GraphQueryResult {
  success: boolean;
  nodes: GraphNode[];
  edges: GraphEdge[];
  sql: string;
  language: QueryLanguage;
  originalQuery: string;
  rawRowCount?: number;
  hasEdgeColumns?: boolean;
  message?: string;
  metadata?: {
    source: string;
    timestamp: string;
    duration: string;
    translationModel: string;
    graphSchema?: string;
  };
}

interface LlmConfig {
  enabled: boolean;
  defaultModel: string;
  maxTokens: number;
  provider: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildExampleQueries(
  nodes: GraphNode[],
  edges: GraphEdge[],
): Record<QueryLanguage, { label: string; query: string }[]> {
  const nodeTypes = [...new Set(nodes.map((n) => n.type).filter(Boolean))];
  const relTypes = [...new Set(edges.map((e) => e.relationshipType).filter(Boolean))];

  const t1 = nodeTypes[0];
  const t2 = nodeTypes[1];
  const t3 = nodeTypes[2];
  const r1 = relTypes[0];
  const r2 = relTypes[1];

  const unhelpfulValues = new Set(['unknown', 'null', 'undefined', 'n/a', 'none', '']);
  let samplePropKey: string | null = null;
  let samplePropVal: string | null = null;

  if (t1) {
    const candidates = nodes.filter(
      (n) => n.type === t1 && n.properties && Object.keys(n.properties).length > 0,
    );
    for (const node of candidates) {
      for (const [key, val] of Object.entries(node.properties)) {
        if (val != null && !unhelpfulValues.has(String(val).toLowerCase().trim())) {
          samplePropKey = key;
          samplePropVal = String(val);
          break;
        }
      }
      if (samplePropKey) break;
    }
  }

  // Cypher
  const cypher: { label: string; query: string }[] = [];
  if (t1) cypher.push({ label: `All ${t1} nodes`, query: `MATCH (n:${t1}) RETURN n` });
  if (t1 && r1 && t2) cypher.push({ label: `${t1} -[${r1}]-> ${t2}`, query: `MATCH (a:${t1})-[:${r1}]->(b:${t2}) RETURN a, b` });
  else if (t1 && r1) cypher.push({ label: `${t1} via ${r1}`, query: `MATCH (a:${t1})-[:${r1}]->(b) RETURN a, b` });
  if (t1 && r1 && t2 && r2 && t3) cypher.push({ label: `2-hop: ${t1} → ${t2} → ${t3}`, query: `MATCH (a:${t1})-[:${r1}]->(b:${t2})-[:${r2}]->(c:${t3}) RETURN a, b, c` });
  else if (t1 && r1 && r2) cypher.push({ label: '2-hop path', query: `MATCH (a:${t1})-[:${r1}]->(b)-[:${r2}]->(c) RETURN a, b, c` });
  if (t1 && samplePropKey && samplePropVal) cypher.push({ label: `Filter by ${samplePropKey}`, query: `MATCH (n:${t1}) WHERE n.${samplePropKey} = '${samplePropVal}' RETURN n` });
  cypher.push({ label: 'All relationships', query: 'MATCH (a)-[r]->(b) RETURN a, r, b LIMIT 100' });

  // Gremlin
  const gremlin: { label: string; query: string }[] = [];
  if (t1) gremlin.push({ label: `All ${t1} nodes`, query: `g.V().hasLabel('${t1}')` });
  if (t1 && r1 && t2) gremlin.push({ label: `${t1} -[${r1}]-> ${t2}`, query: `g.V().hasLabel('${t1}').out('${r1}').hasLabel('${t2}')` });
  else if (t1 && r1) gremlin.push({ label: `${t1} via ${r1}`, query: `g.V().hasLabel('${t1}').out('${r1}')` });
  if (t1 && r1 && t2 && r2 && t3) gremlin.push({ label: `2-hop: ${t1} → ${t2} → ${t3}`, query: `g.V().hasLabel('${t1}').out('${r1}').hasLabel('${t2}').out('${r2}').hasLabel('${t3}')` });
  else if (t1 && r1 && r2) gremlin.push({ label: '2-hop path', query: `g.V().hasLabel('${t1}').out('${r1}').out('${r2}')` });
  if (t1 && samplePropKey && samplePropVal) gremlin.push({ label: `Filter by ${samplePropKey}`, query: `g.V().hasLabel('${t1}').has('${samplePropKey}', '${samplePropVal}')` });
  gremlin.push({ label: 'All edges', query: 'g.E().limit(100)' });

  return { cypher, gremlin };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface GraphQueryPanelProps {
  /** Called when query results should be applied to the graph */
  onApplyResults: (nodes: GraphNode[], edges: GraphEdge[]) => void;
  /** Called when the user clears an active query to restore the full dataset */
  onClearQuery: () => void;
  /** Full graph data — used to generate contextual example queries */
  graphData?: GraphData;
  /** Current table name for context */
  tableName?: string;
  /** Whether the panel is initially expanded */
  defaultExpanded?: boolean;
}

const GraphQueryPanel: React.FC<GraphQueryPanelProps> = ({
  onApplyResults,
  onClearQuery,
  graphData,
  tableName,
  defaultExpanded = false,
}) => {
  const { t } = useTranslation(['graph-explorer']);

  // Example queries derived from current graph data
  const exampleQueries = useMemo(
    () => buildExampleQueries(graphData?.nodes ?? [], graphData?.edges ?? []),
    [graphData],
  );

  // Panel state
  const [expanded, setExpanded] = useState(defaultExpanded);

  // Query state
  const [language, setLanguage] = useState<QueryLanguage>('natural');
  const [query, setQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // LLM availability
  const [llmEnabled, setLlmEnabled] = useState<boolean | null>(null);
  const [llmModel, setLlmModel] = useState('');

  // Fetch LLM config on mount
  useEffect(() => {
    fetch('/api/graph-explorer/llm-config')
      .then((res) => (res.ok ? res.json() : null))
      .then((cfg: LlmConfig | null) => {
        if (cfg) {
          setLlmEnabled(cfg.enabled);
          setLlmModel(cfg.defaultModel);
        } else {
          setLlmEnabled(false);
        }
      })
      .catch(() => setLlmEnabled(false));
  }, []);

  // Result state
  const [result, setResult] = useState<GraphQueryResult | null>(null);
  const [showSql, setShowSql] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queryApplied, setQueryApplied] = useState(false);

  // --- Handlers ---

  const handleLanguageChange = useCallback((value: string) => {
    setLanguage(value as QueryLanguage);
    setResult(null);
    setError(null);
  }, []);

  const handleExampleSelect = useCallback((value: string) => {
    if (value) {
      setQuery(value);
      setResult(null);
      setError(null);
    }
  }, []);

  const handleRunQuery = useCallback(async () => {
    if (!query.trim()) return;

    setIsLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch('/api/graph-explorer/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, language, tableName }),
      });

      const data: GraphQueryResult = await response.json();
      setResult(data);

      if (!data.success) {
        setError(data.message || 'Query failed');
      } else if (data.nodes.length > 0 || data.edges.length > 0) {
        let nodes = data.nodes;
        let edges = data.edges;

        // Vertex-only / edge-only heuristics only apply to structured query languages
        if (language !== 'natural') {
          const q = query.trim().toLowerCase();
          const isVertexOnly =
            language === 'gremlin'
              ? /^g\.v\(\)/.test(q) && !/(\.out\(|\.in\(|\.both\(|\.oute\(|\.ine\(|\.bothe\(|g\.e\()/.test(q)
              : language === 'cypher'
                ? !/-\[/.test(query) && !/\]-/.test(query)
                : false;
          const isEdgeOnly = language === 'gremlin' ? /^g\.e\(\)/.test(q) : false;

          if (isEdgeOnly) nodes = [];
          if (isVertexOnly) edges = [];

          // Filter nodes for vertex-only queries
          if (isVertexOnly && nodes.length > 0) {
            const labelSet = new Set<string>();
            if (language === 'cypher') {
              const matches = query.matchAll(/\(\w*:(\w+)/g);
              for (const m of matches) labelSet.add(m[1]);
            } else if (language === 'gremlin') {
              const matches = q.matchAll(/\.haslabel\('([^']+)'\)/g);
              for (const m of matches) labelSet.add(m[1]);
            }
            if (labelSet.size > 0) {
              const lowerSet = new Set([...labelSet].map((l) => l.toLowerCase()));
              nodes = nodes.filter((n) => lowerSet.has(n.type.toLowerCase()));
            }
          }
        }

        onApplyResults(nodes, edges);
        setQueryApplied(true);
      } else if (data.success) {
        onApplyResults([], []);
        setQueryApplied(true);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unexpected error occurred');
    } finally {
      setIsLoading(false);
    }
  }, [query, language, tableName, onApplyResults]);

  const handleRemoveLimit = useCallback(async () => {
    if (!result?.sql) return;
    const sqlWithoutLimit = result.sql.replace(/\s+LIMIT\s+\d+\s*$/i, '');
    if (sqlWithoutLimit === result.sql) return;

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/graph-explorer/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, language, tableName, sql: sqlWithoutLimit }),
      });
      const data: GraphQueryResult = await response.json();
      setResult(data);

      if (!data.success) {
        setError(data.message || 'Query failed');
      } else if (data.nodes.length > 0 || data.edges.length > 0) {
        onApplyResults(data.nodes, data.edges);
        setQueryApplied(true);
      } else {
        onApplyResults([], []);
        setQueryApplied(true);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unexpected error occurred');
    } finally {
      setIsLoading(false);
    }
  }, [result, query, language, tableName, onApplyResults]);

  const handleCopySql = useCallback(() => {
    if (result?.sql) {
      navigator.clipboard.writeText(result.sql);
    }
  }, [result]);

  const handleClearQuery = useCallback(() => {
    setQuery('');
    setResult(null);
    setError(null);
    setShowSql(false);
    setQueryApplied(false);
    onClearQuery();
  }, [onClearQuery]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        handleRunQuery();
      }
    },
    [handleRunQuery],
  );

  const placeholderText = useMemo(() => {
    if (language === 'natural') {
      return t('queryPanel.naturalPlaceholder');
    }
    const examples = exampleQueries[language];
    const hop = examples.length > 1 ? examples[1] : examples[0];
    if (hop) return hop.query;
    return language === 'cypher'
      ? 'MATCH (a)-[r]->(b) RETURN a, r, b LIMIT 100'
      : 'g.E().limit(100)';
  }, [exampleQueries, language, t]);

  // SQL LIMIT detection for warning
  const limitMatch = result?.sql?.match(/LIMIT\s+(\d+)/i);
  const sqlLimit = limitMatch ? parseInt(limitMatch[1], 10) : null;
  const isLimitHit =
    sqlLimit != null && result?.rawRowCount != null && result.rawRowCount >= sqlLimit;

  return (
    <Collapsible open={expanded} onOpenChange={setExpanded}>
      <div className="rounded-lg border bg-card text-card-foreground">
        {/* Header */}
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center justify-between px-4 py-3 hover:bg-muted/50 transition-colors cursor-pointer"
          >
            <div className="flex items-center gap-2">
              <Sparkles
                className={`h-4 w-4 ${llmEnabled === false ? 'text-muted-foreground' : 'text-primary'}`}
              />
              <span
                className={`text-sm font-semibold ${llmEnabled === false ? 'text-muted-foreground' : ''}`}
              >
                {t('queryPanel.title')}
              </span>
              {llmEnabled === false ? (
                <Badge variant="outline" className="text-[0.65rem] px-1.5 py-0 opacity-60">
                  {t('queryPanel.notConfigured')}
                </Badge>
              ) : (
                <Badge variant="outline" className="text-[0.65rem] px-1.5 py-0">
                  {llmModel || 'Cypher / Gremlin'}
                </Badge>
              )}
              {queryApplied && (
                <Badge variant="secondary" className="text-[0.65rem] px-1.5 py-0 bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400 font-semibold">
                  {t('queryPanel.queryActive')}
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-1">
              {queryApplied && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-xs text-amber-600 hover:text-amber-700"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleClearQuery();
                  }}
                >
                  <X className="h-3 w-3 mr-1" />
                  {t('queryPanel.clearQuery')}
                </Button>
              )}
              {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </div>
          </button>
        </CollapsibleTrigger>

        {/* Collapsible body */}
        <CollapsibleContent>
          <div className="px-4 pb-4 space-y-3 border-t">
            {/* LLM not configured */}
            {llmEnabled === false && (
              <Alert className="mt-3">
                <Info className="h-4 w-4" />
                <AlertTitle className="text-sm font-semibold">{t('queryPanel.llmNotConfiguredTitle')}</AlertTitle>
                <AlertDescription className="text-xs text-muted-foreground">
                  {t('queryPanel.llmNotConfiguredDescription')}
                </AlertDescription>
              </Alert>
            )}

            {/* Loading LLM config */}
            {llmEnabled === null && (
              <div className="flex items-center gap-2 py-3 mt-3">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span className="text-sm text-muted-foreground">{t('queryPanel.checkingConfig')}</span>
              </div>
            )}

            {/* Query controls */}
            {llmEnabled && (
              <>
                {/* Language toggle + examples + run */}
                <div className="flex items-center gap-3 mt-3 flex-wrap">
                  {/* Language selector */}
                  <div className="flex rounded-md border overflow-hidden">
                    <button
                      type="button"
                      onClick={() => handleLanguageChange('natural')}
                      className={`flex items-center gap-1 px-3 py-1.5 text-xs font-semibold transition-colors ${
                        language === 'natural'
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-muted/50 hover:bg-muted'
                      }`}
                    >
                      <Sparkles className="h-3 w-3" />
                      {t('queryPanel.naturalLanguage')}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleLanguageChange('cypher')}
                      className={`flex items-center gap-1 px-3 py-1.5 text-xs font-semibold transition-colors ${
                        language === 'cypher'
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-muted/50 hover:bg-muted'
                      }`}
                    >
                      <Code2 className="h-3 w-3" />
                      Cypher
                    </button>
                    <button
                      type="button"
                      onClick={() => handleLanguageChange('gremlin')}
                      className={`flex items-center gap-1 px-3 py-1.5 text-xs font-semibold transition-colors ${
                        language === 'gremlin'
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-muted/50 hover:bg-muted'
                      }`}
                    >
                      <Code2 className="h-3 w-3" />
                      Gremlin
                    </button>
                  </div>

                  {/* Example queries dropdown — only for Cypher/Gremlin */}
                  {language !== 'natural' && (
                    <Select key={language} onValueChange={handleExampleSelect}>
                      <SelectTrigger className="w-[180px] h-8 text-xs">
                        <SelectValue placeholder={t('queryPanel.examples')} />
                      </SelectTrigger>
                      <SelectContent>
                        {exampleQueries[language].map((ex) => (
                          <SelectItem key={ex.label} value={ex.query} className="text-xs">
                            {ex.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}

                  {/* Run button */}
                  <Button
                    size="sm"
                    onClick={handleRunQuery}
                    disabled={isLoading || !query.trim()}
                    className="h-8 text-xs font-semibold"
                  >
                    {isLoading ? (
                      <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                    ) : (
                      <Play className="h-3.5 w-3.5 mr-1.5" />
                    )}
                    {isLoading ? t('queryPanel.translating') : t('queryPanel.runQuery')}
                  </Button>

                  <span className={`text-[0.7rem] text-muted-foreground ${isLoading ? 'animate-pulse' : ''}`}>
                    {isLoading ? t('queryPanel.translatingViaLlm') : '⌘+Enter'}
                  </span>
                </div>

                {/* Query input */}
                <Textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={placeholderText}
                  disabled={isLoading}
                  rows={3}
                  className="font-mono text-sm resize-none"
                />

                {/* Error */}
                {error && (
                  <Alert variant="destructive">
                    <AlertCircle className="h-4 w-4" />
                    <AlertDescription className="text-xs">{error}</AlertDescription>
                  </Alert>
                )}

                {/* Results */}
                {result?.success && (
                  <div className="space-y-3">
                    {/* Stats badges */}
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge variant="outline" className="text-xs">
                        {result.nodes.length} nodes
                      </Badge>
                      <Badge variant="outline" className="text-xs">
                        {result.edges.length} edges
                      </Badge>
                      {result.rawRowCount !== undefined && (
                        <Badge variant="outline" className="text-xs">
                          {result.rawRowCount} rows
                        </Badge>
                      )}
                      {result.metadata?.duration && (
                        <span className="text-xs text-muted-foreground">
                          {result.metadata.duration}
                        </span>
                      )}
                    </div>

                    {/* Generated SQL toggle */}
                    {result.sql && (
                      <div>
                        <button
                          type="button"
                          onClick={() => setShowSql(!showSql)}
                          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                        >
                          <Database className="h-3.5 w-3.5" />
                          <span className="font-semibold">{t('queryPanel.generatedSql')}</span>
                          {showSql ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                        </button>
                        {showSql && (
                          <div className="mt-2 relative rounded bg-muted/50 p-3 font-mono text-xs whitespace-pre-wrap break-words overflow-auto max-h-48">
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="absolute top-1 right-1 h-6 w-6 opacity-60 hover:opacity-100"
                                    onClick={handleCopySql}
                                  >
                                    <Copy className="h-3 w-3" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent side="left">{t('queryPanel.copySql')}</TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                            {result.sql}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Graph schema context (debug) */}
                    {result.metadata?.graphSchema && showSql && (
                      <div className="rounded bg-muted/30 p-2 text-[0.65rem] font-mono whitespace-pre-wrap text-muted-foreground overflow-auto max-h-32">
                        <span className="font-semibold text-foreground/60">Schema context sent to LLM:</span>
                        {'\n'}{result.metadata.graphSchema}
                      </div>
                    )}

                    {/* Success message */}
                    {(result.nodes.length > 0 || result.edges.length > 0) && (
                      <Alert className="bg-green-50 border-green-200 dark:bg-green-950/20 dark:border-green-800">
                        <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
                        <AlertDescription className="text-xs flex items-center justify-between">
                          <span>
                            {t('queryPanel.applied', {
                              nodeCount: result.nodes.length,
                              edgeCount: result.edges.length,
                            })}
                          </span>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 px-2 text-xs"
                            onClick={handleClearQuery}
                          >
                            <X className="h-3 w-3 mr-1" />
                            {t('queryPanel.clear')}
                          </Button>
                        </AlertDescription>
                      </Alert>
                    )}

                    {/* SQL LIMIT truncation warning */}
                    {isLimitHit && (
                      <Alert className="bg-amber-50 border-amber-200 dark:bg-amber-950/20 dark:border-amber-800">
                        <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                        <AlertDescription className="text-xs flex items-center justify-between">
                          <span>
                            {t('queryPanel.limitWarning', { limit: sqlLimit!.toLocaleString() })}
                          </span>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 px-2 text-xs"
                            onClick={handleRemoveLimit}
                            disabled={isLoading}
                          >
                            {t('queryPanel.removeLimit')}
                          </Button>
                        </AlertDescription>
                      </Alert>
                    )}

                    {/* No graph data */}
                    {result.nodes.length === 0 && result.edges.length === 0 && (
                      <Alert>
                        <Info className="h-4 w-4" />
                        <AlertDescription className="text-xs">
                          {t('queryPanel.noGraphData', { rowCount: result.rawRowCount ?? 0 })}
                        </AlertDescription>
                      </Alert>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
};

export default GraphQueryPanel;
