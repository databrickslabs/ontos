import { useState, useEffect, useCallback } from 'react';
import { Wand2, Loader2, Copy, Download, Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { useKnowledgeGraphStore } from '@/stores/knowledge-graph-store';
import type { Connection } from '@/types/connections';
import SchemaBrowser from '@/components/schema-importer/schema-browser';

interface OntologyClass {
  uri: string;
  name: string;
  label: string;
  comment: string;
  emoji: string;
  parent: string;
  dataProperties: { name: string; label: string; uri: string }[];
}

interface OntologyProperty {
  uri: string;
  name: string;
  label: string;
  comment: string;
  type: string;
  domain: string;
  range: string;
}

interface AgentStep {
  step_type: string;
  content: string;
  tool_name: string;
  duration_ms: number;
}

interface GenerateResponse {
  success: boolean;
  owl_content: string;
  classes: OntologyClass[];
  properties: OntologyProperty[];
  ontology_info: { uri: string; label: string; comment: string; namespace: string };
  constraints: Record<string, unknown>[];
  axioms: Record<string, unknown>[];
  steps: AgentStep[];
  iterations: number;
  error: string;
  usage: { prompt_tokens: number; completion_tokens: number };
}

export default function OntologyGeneratorView() {
  const { get: apiGet, post } = useApi();
  const { toast } = useToast();
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);
  const bumpKnowledgeGraphRefresh = useKnowledgeGraphStore((s) => s.bumpRefreshNonce);

  const [connections, setConnections] = useState<Connection[]>([]);
  const [isLoadingConnections, setIsLoadingConnections] = useState(true);
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());

  // Generation options
  const [guidelines, setGuidelines] = useState('');
  const [baseUri, setBaseUri] = useState('http://ontos.example.org/ontology#');
  const [includeDataProperties, setIncludeDataProperties] = useState(true);
  const [includeRelationships, setIncludeRelationships] = useState(true);
  const [includeInheritance, setIncludeInheritance] = useState(true);

  const [isGenerating, setIsGenerating] = useState(false);
  const [result, setResult] = useState<GenerateResponse | null>(null);

  // Save to collection
  const [isSaveDialogOpen, setIsSaveDialogOpen] = useState(false);
  const [collectionName, setCollectionName] = useState('');
  const [collectionDescription, setCollectionDescription] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle('Ontology Generator');
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [setStaticSegments, setDynamicTitle]);

  const fetchConnections = useCallback(async () => {
    setIsLoadingConnections(true);
    try {
      const resp = await apiGet<Connection[]>('/api/connections');
      if (resp.data) {
        const enabled = resp.data.filter((c) => c.enabled);
        setConnections(enabled);
        if (enabled.length === 1) {
          setSelectedConnectionId(enabled[0].id);
        }
      }
    } catch (err) {
      console.error('Failed to fetch connections:', err);
    } finally {
      setIsLoadingConnections(false);
    }
  }, [apiGet]);

  useEffect(() => {
    fetchConnections();
  }, [fetchConnections]);

  const handleConnectionChange = (id: string) => {
    setSelectedConnectionId(id);
    setSelectedPaths(new Set());
    setResult(null);
  };

  const selectedConnection = connections.find((c) => c.id === selectedConnectionId);
  const canGenerate = selectedPaths.size > 0 && !isGenerating;

  const handleGenerate = async () => {
    if (!selectedConnectionId || selectedPaths.size === 0) return;

    setIsGenerating(true);
    setResult(null);

    try {
      const response = await post<GenerateResponse>('/api/ontology/generate-from-connection', {
        connection_id: selectedConnectionId,
        selected_paths: Array.from(selectedPaths),
        guidelines,
        base_uri: baseUri,
        include_data_properties: includeDataProperties,
        include_relationships: includeRelationships,
        include_inheritance: includeInheritance,
      });

      if (response.error) {
        toast({ title: 'Generation failed', description: response.error, variant: 'destructive' });
        return;
      }

      setResult(response.data ?? null);

      if (response.data?.success) {
        toast({
          title: 'Ontology generated',
          description: `${response.data.classes.length} classes, ${response.data.properties.length} properties in ${response.data.iterations} iteration(s).`,
        });
      } else if (response.data?.error) {
        toast({ title: 'Generation incomplete', description: response.data.error, variant: 'destructive' });
      }
    } catch (err) {
      toast({ title: 'Error', description: String(err), variant: 'destructive' });
    } finally {
      setIsGenerating(false);
    }
  };

  const copyTurtle = () => {
    if (result?.owl_content) {
      navigator.clipboard.writeText(result.owl_content);
      toast({ title: 'Copied', description: 'Turtle content copied to clipboard.' });
    }
  };

  const downloadTurtle = () => {
    if (result?.owl_content) {
      const blob = new Blob([result.owl_content], { type: 'text/turtle' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'ontology.ttl';
      a.click();
      URL.revokeObjectURL(url);
    }
  };

  const handleSaveToCollection = async () => {
    if (!result?.owl_content || !collectionName.trim()) return;

    setIsSaving(true);
    try {
      const response = await post<{
        success: boolean;
        collection_iri: string;
        triples_imported: number;
        error: string;
      }>('/api/ontology/save-to-collection', {
        owl_content: result.owl_content,
        collection_name: collectionName.trim(),
        collection_description: collectionDescription.trim(),
      });

      if (response.error) {
        toast({ title: 'Save failed', description: response.error, variant: 'destructive' });
        return;
      }

      if (response.data?.success) {
        toast({
          title: 'Saved to collection',
          description: `${response.data.triples_imported} triples imported into "${collectionName}".`,
        });
        setIsSaveDialogOpen(false);
        setCollectionName('');
        setCollectionDescription('');
        // Refresh any open Concepts/Graph views so the new collection
        // appears without requiring a manual reload.
        bumpKnowledgeGraphRefresh('ontology-save');
      } else {
        toast({
          title: 'Save failed',
          description: response.data?.error || 'Unknown error',
          variant: 'destructive',
        });
      }
    } catch (err) {
      toast({ title: 'Error', description: String(err), variant: 'destructive' });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Ontology Generator</h2>
        <p className="text-muted-foreground">
          Browse a remote system, select tables, and generate an OWL ontology from their schemas.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        {/* Left panel: connection + options */}
        <div className="space-y-4">
          {/* Connection selector */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Connection</CardTitle>
              <CardDescription className="text-xs">
                Select a data platform connection
              </CardDescription>
            </CardHeader>
            <CardContent>
              {isLoadingConnections ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading...
                </div>
              ) : connections.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No connections configured. Add one in Settings &gt; Connectors.
                </p>
              ) : (
                <Select
                  value={selectedConnectionId || ''}
                  onValueChange={handleConnectionChange}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Choose connection..." />
                  </SelectTrigger>
                  <SelectContent>
                    {connections.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        <div className="flex items-center gap-2">
                          <span>{c.name}</span>
                          <Badge variant="outline" className="text-[10px] px-1 py-0">
                            {c.connector_type}
                          </Badge>
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </CardContent>
          </Card>

          {/* Generation options */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Generation Options</CardTitle>
              <CardDescription className="text-xs">
                Customize the ontology generation
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label htmlFor="guidelines" className="text-xs">Guidelines</Label>
                <Textarea
                  id="guidelines"
                  placeholder="E.g., Create a domain ontology for e-commerce data..."
                  value={guidelines}
                  onChange={(e) => setGuidelines(e.target.value)}
                  rows={3}
                  className="mt-1 text-sm"
                />
              </div>
              <div>
                <Label htmlFor="baseUri" className="text-xs">Base URI</Label>
                <Input
                  id="baseUri"
                  value={baseUri}
                  onChange={(e) => setBaseUri(e.target.value)}
                  className="mt-1 font-mono text-xs"
                />
              </div>
              <Separator />
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="incDataProps" className="text-xs">Data properties</Label>
                  <Switch id="incDataProps" checked={includeDataProperties} onCheckedChange={setIncludeDataProperties} />
                </div>
                <div className="flex items-center justify-between">
                  <Label htmlFor="incRels" className="text-xs">Relationships</Label>
                  <Switch id="incRels" checked={includeRelationships} onCheckedChange={setIncludeRelationships} />
                </div>
                <div className="flex items-center justify-between">
                  <Label htmlFor="incInherit" className="text-xs">Inheritance</Label>
                  <Switch id="incInherit" checked={includeInheritance} onCheckedChange={setIncludeInheritance} />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Generate button */}
          <Button onClick={handleGenerate} disabled={!canGenerate} className="w-full">
            {isGenerating ? (
              <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Generating...</>
            ) : (
              <><Wand2 className="h-4 w-4 mr-2" /> Generate Ontology ({selectedPaths.size} selected)</>
            )}
          </Button>
        </div>

        {/* Right panel: tree + results */}
        <div className="space-y-4">
          {/* Tree browser */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-sm font-medium">
                    {selectedConnection
                      ? `${selectedConnection.name} — Resources`
                      : 'Resources'}
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Select the catalogs, schemas, or tables to generate an ontology from
                  </CardDescription>
                </div>
                {selectedPaths.size > 0 && (
                  <Badge variant="secondary">{selectedPaths.size} selected</Badge>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <SchemaBrowser
                connectionId={selectedConnectionId}
                selectedPaths={selectedPaths}
                onSelectionChange={setSelectedPaths}
              />
            </CardContent>
          </Card>

          {/* Results */}
          {isGenerating && (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-12 text-center">
                <Loader2 className="h-10 w-10 mb-3 animate-spin text-primary" />
                <p className="text-lg font-medium">Generating ontology...</p>
                <p className="text-sm text-muted-foreground mt-1">
                  The LLM agent is fetching schemas and building the ontology.
                </p>
              </CardContent>
            </Card>
          )}

          {result && (
            <Tabs defaultValue="classes">
              <TabsList className="w-full">
                <TabsTrigger value="classes">Classes ({result.classes.length})</TabsTrigger>
                <TabsTrigger value="properties">Properties ({result.properties.length})</TabsTrigger>
                <TabsTrigger value="turtle">Turtle</TabsTrigger>
                <TabsTrigger value="agent">Agent Log</TabsTrigger>
              </TabsList>

              <TabsContent value="classes">
                <Card>
                  <CardContent className="pt-4">
                    <ScrollArea className="h-[400px]">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Class</TableHead>
                            <TableHead>Parent</TableHead>
                            <TableHead>Attributes</TableHead>
                            <TableHead>Description</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {result.classes.map((cls) => (
                            <TableRow key={cls.uri}>
                              <TableCell className="font-mono font-medium">
                                {cls.emoji && <span className="mr-1">{cls.emoji}</span>}
                                {cls.name}
                              </TableCell>
                              <TableCell className="font-mono text-muted-foreground">{cls.parent || '—'}</TableCell>
                              <TableCell>
                                <div className="flex flex-wrap gap-1">
                                  {cls.dataProperties.map((dp) => (
                                    <Badge key={dp.name} variant="secondary" className="text-xs font-mono">
                                      {dp.name}
                                    </Badge>
                                  ))}
                                  {cls.dataProperties.length === 0 && (
                                    <span className="text-muted-foreground text-xs">none</span>
                                  )}
                                </div>
                              </TableCell>
                              <TableCell className="text-sm text-muted-foreground max-w-[200px] truncate">
                                {cls.comment || '—'}
                              </TableCell>
                            </TableRow>
                          ))}
                          {result.classes.length === 0 && (
                            <TableRow>
                              <TableCell colSpan={4} className="text-center text-muted-foreground">
                                No classes generated
                              </TableCell>
                            </TableRow>
                          )}
                        </TableBody>
                      </Table>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="properties">
                <Card>
                  <CardContent className="pt-4">
                    <ScrollArea className="h-[400px]">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Property</TableHead>
                            <TableHead>Type</TableHead>
                            <TableHead>Domain</TableHead>
                            <TableHead>Range</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {result.properties.map((prop) => (
                            <TableRow key={prop.uri}>
                              <TableCell className="font-mono font-medium">{prop.name}</TableCell>
                              <TableCell>
                                <Badge
                                  variant={prop.type === 'ObjectProperty' ? 'default' : 'secondary'}
                                  className="text-xs"
                                >
                                  {prop.type === 'ObjectProperty' ? 'Object' : 'Data'}
                                </Badge>
                              </TableCell>
                              <TableCell className="font-mono text-sm">{prop.domain || '—'}</TableCell>
                              <TableCell className="font-mono text-sm">{prop.range || '—'}</TableCell>
                            </TableRow>
                          ))}
                          {result.properties.length === 0 && (
                            <TableRow>
                              <TableCell colSpan={4} className="text-center text-muted-foreground">
                                No properties generated
                              </TableCell>
                            </TableRow>
                          )}
                        </TableBody>
                      </Table>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="turtle">
                <Card>
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-sm">Generated Turtle</CardTitle>
                      <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={copyTurtle}>
                          <Copy className="h-3.5 w-3.5 mr-1" /> Copy
                        </Button>
                        <Button variant="outline" size="sm" onClick={downloadTurtle}>
                          <Download className="h-3.5 w-3.5 mr-1" /> Download
                        </Button>
                        <Button size="sm" onClick={() => setIsSaveDialogOpen(true)}>
                          <Save className="h-3.5 w-3.5 mr-1" /> Save to Collection
                        </Button>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <ScrollArea className="h-[400px]">
                      <pre className="text-xs font-mono whitespace-pre-wrap bg-muted p-4 rounded-md">
                        {result.owl_content || '(empty)'}
                      </pre>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="agent">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">Agent Execution Log</CardTitle>
                    <CardDescription>
                      {result.iterations} iteration(s) ·{' '}
                      {result.usage.prompt_tokens ?? 0} prompt tokens ·{' '}
                      {result.usage.completion_tokens ?? 0} completion tokens
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ScrollArea className="h-[400px]">
                      <div className="space-y-2">
                        {result.steps.map((step, i) => (
                          <div key={i} className="border rounded-md p-3">
                            <div className="flex items-center gap-2 mb-1">
                              <Badge
                                variant={
                                  step.step_type === 'tool_call'
                                    ? 'default'
                                    : step.step_type === 'tool_result'
                                      ? 'secondary'
                                      : 'outline'
                                }
                                className="text-xs"
                              >
                                {step.step_type}
                              </Badge>
                              {step.tool_name && (
                                <span className="text-xs font-mono text-muted-foreground">
                                  {step.tool_name}
                                </span>
                              )}
                              {step.duration_ms > 0 && (
                                <span className="text-xs text-muted-foreground ml-auto">
                                  {step.duration_ms}ms
                                </span>
                              )}
                            </div>
                            <pre className="text-xs font-mono whitespace-pre-wrap text-muted-foreground mt-1 max-h-32 overflow-auto">
                              {step.content}
                            </pre>
                          </div>
                        ))}
                        {result.steps.length === 0 && (
                          <p className="text-center text-muted-foreground text-sm">
                            No agent steps recorded
                          </p>
                        )}
                      </div>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          )}

          {result && !result.success && result.error && (
            <Card className="border-destructive">
              <CardContent className="pt-4">
                <p className="text-sm text-destructive">{result.error}</p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Save to Collection dialog */}
      <Dialog open={isSaveDialogOpen} onOpenChange={setIsSaveDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save to Concept Collection</DialogTitle>
            <DialogDescription>
              Create a new ontology collection and import the generated triples into the knowledge graph.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label htmlFor="collName">Collection Name</Label>
              <Input
                id="collName"
                placeholder="e.g., Customer Domain Ontology"
                value={collectionName}
                onChange={(e) => setCollectionName(e.target.value)}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="collDesc">Description (optional)</Label>
              <Textarea
                id="collDesc"
                placeholder="Describe the purpose of this ontology collection..."
                value={collectionDescription}
                onChange={(e) => setCollectionDescription(e.target.value)}
                rows={3}
                className="mt-1"
              />
            </div>
            {result && (
              <p className="text-xs text-muted-foreground">
                {result.classes.length} classes and {result.properties.length} properties will be imported.
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsSaveDialogOpen(false)} disabled={isSaving}>
              Cancel
            </Button>
            <Button onClick={handleSaveToCollection} disabled={isSaving || !collectionName.trim()}>
              {isSaving ? (
                <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Saving...</>
              ) : (
                <><Save className="h-4 w-4 mr-2" /> Save</>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
