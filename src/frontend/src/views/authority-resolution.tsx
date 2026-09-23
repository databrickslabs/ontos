import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApi } from '@/hooks/use-api';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Plus, AlertCircle, ShieldCheck } from 'lucide-react';
import CreateAuthorityRelationDialog from '@/components/authority-resolution/create-authority-relation-dialog';
import type { AuthorityRelation } from '@/types/authority-resolution';

const FEATURE_ID = 'authority-resolution';

function statusVariant(status: string): 'default' | 'secondary' | 'outline' | 'destructive' {
  switch ((status || '').toLowerCase()) {
    case 'active': return 'default';
    case 'needs_review': return 'destructive';
    case 'retired': return 'outline';
    default: return 'secondary'; // draft
  }
}

/** DNAco is a divergence: 0 is best, higher is worse (rendered like a defect rate). */
export function formatDna(magnitude: number | null | undefined, direction?: string | null): string {
  if (magnitude === null || magnitude === undefined) return '—';
  const arrow = direction === 'actual-exceeds-documented' ? ' ▲'
    : direction === 'documented-exceeds-actual' ? ' ▼' : '';
  return `${magnitude.toFixed(2)}${arrow}`;
}

export default function AuthorityResolution() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { get } = useApi();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const canWrite = !permissionsLoading && hasPermission(FEATURE_ID, FeatureAccessLevel.READ_WRITE);

  const [relations, setRelations] = useState<AuthorityRelation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const fetchRelations = useCallback(async () => {
    setLoading(true);
    const { data, error } = await get<AuthorityRelation[]>('/api/authority/relations');
    if (error) {
      setError(error);
      setRelations([]);
    } else {
      setError(null);
      setRelations(Array.isArray(data) ? data : []);
    }
    setLoading(false);
  }, [get]);

  useEffect(() => { fetchRelations(); }, [fetchRelations]);

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-6 w-6 text-muted-foreground" />
          <h1 className="text-2xl font-bold">Authority Resolution</h1>
        </div>
        {canWrite && (
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4 mr-2" /> New Authority Relation
          </Button>
        )}
      </div>

      <p className="text-muted-foreground mb-6 max-w-3xl">
        Author <strong>Authority Relations</strong> (ARF) that make soft decision authority explicit
        and agent-callable. Each relation carries a DNA-Coefficient — a divergence measure where
        <strong> 0.0 is best</strong> — computed from bound evidence, and becomes active only once it
        is within its threshold and fully affirmed.
      </p>

      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>DNAco</TableHead>
                <TableHead>Maturity</TableHead>
                <TableHead>Action</TableHead>
                <TableHead className="text-right">Usage</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground py-8">Loading…</TableCell></TableRow>
              ) : relations.length === 0 ? (
                <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground py-8">No Authority Relations yet.</TableCell></TableRow>
              ) : (
                relations.map((r) => (
                  <TableRow
                    key={r.id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/authority-resolution/${r.id}`)}
                  >
                    <TableCell className="font-medium">{r.name}</TableCell>
                    <TableCell><Badge variant={statusVariant(r.status)}>{r.status}</Badge></TableCell>
                    <TableCell>{formatDna(r.dna_magnitude, r.dna_direction)}</TableCell>
                    <TableCell><Badge variant="outline">{r.maturity_level}</Badge></TableCell>
                    <TableCell className="text-muted-foreground">{r.action || '—'}</TableCell>
                    <TableCell className="text-right">{r.usage_count ?? 0}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <CreateAuthorityRelationDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(created) => {
          setCreateOpen(false);
          toast({ title: 'Authority Relation created', description: created.name });
          if (created.id) navigate(`/authority-resolution/${created.id}`);
          else fetchRelations();
        }}
      />
    </div>
  );
}
