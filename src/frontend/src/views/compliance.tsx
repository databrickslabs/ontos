import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';
import { 
  Plus, 
  Scale, 
  MoreHorizontal, 
} from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ColumnDef } from "@tanstack/react-table";
import { useApi } from '@/hooks/use-api';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { DataTable } from '@/components/ui/data-table';
import {
  ListViewSkeleton,
  StatCardsSkeleton,
} from '@/components/common/list-view-skeleton';

interface CompliancePolicy {
  id: string; // UUID
  name: string;
  description: string;
  failure_message?: string;  // Human-readable message shown when policy fails
  rule: string;
  compliance: number;
  history: number[];
  created_at: string;
  updated_at: string;
  is_active: boolean;
  severity: 'low' | 'medium' | 'high' | 'critical';
  category: string;
}

interface ComplianceStats {
  overall_compliance: number;
  active_policies: number;
  critical_issues: number;
}

interface ComplianceApiResponse {
  policies: CompliancePolicy[];
  stats: ComplianceStats;
}

export default function Compliance() {
  const { t } = useTranslation(['compliance', 'common']);
  const { toast } = useToast();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { get: apiGet, post: apiPost, put: apiPut, delete: apiDeleteApi, loading: apiIsLoading } = useApi();
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);
  const [policies, setPolicies] = useState<CompliancePolicy[]>([]);
  const [stats, setStats] = useState<ComplianceStats>({
    overall_compliance: 0,
    active_policies: 0,
    critical_issues: 0
  });
  const [selectedPolicy, setSelectedPolicy] = useState<CompliancePolicy | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [componentError, setComponentError] = useState<string | null>(null);

  const loadPolicies = useCallback(async () => {
    setComponentError(null);
    try {
      const response = await apiGet<ComplianceApiResponse>('/api/compliance/policies');
      if (response.error) {
        throw new Error(response.error);
      }
      if (response.data) {
        setPolicies(response.data.policies || []);
        setStats(response.data.stats || {
          overall_compliance: 0,
          active_policies: 0,
          critical_issues: 0
        });
      } else {
        setPolicies([]);
        setStats({ overall_compliance: 0, active_policies: 0, critical_issues: 0 });
        throw new Error("No data received from compliance policies endpoint.");
      }
    } catch (error) {
      console.error('Error loading policies:', error);
      const errorMessage = error instanceof Error ? error.message : "Failed to load compliance policies";
      setComponentError(errorMessage);
      toast({
        title: t('compliance:errors.loadingPolicies'),
        description: errorMessage,
        variant: "destructive"
      });
      setPolicies([]);
      setStats({ overall_compliance: 0, active_policies: 0, critical_issues: 0 });
    }
  }, [apiGet, toast, t]);

  useEffect(() => {
    loadPolicies();
    setStaticSegments([]);
    setDynamicTitle(t('compliance:title'));

    return () => {
        setStaticSegments([]);
        setDynamicTitle(null);
    };
  }, [loadPolicies, setStaticSegments, setDynamicTitle, t]);

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    setComponentError(null);
    try {
      const form = event.target as HTMLFormElement;
      const policyData: Omit<CompliancePolicy, 'id' | 'created_at' | 'updated_at' | 'compliance' | 'history'> & Partial<Pick<CompliancePolicy, 'id' | 'compliance' | 'history' | 'created_at' | 'updated_at'>> = {
        name: (form.querySelector('#name') as HTMLInputElement).value,
        description: (form.querySelector('#description') as HTMLTextAreaElement).value,
        failure_message: (form.querySelector('#failure_message') as HTMLTextAreaElement)?.value || undefined,
        category: (form.querySelector('select[name="category"]') as HTMLSelectElement)?.value || 'General',
        severity: (form.querySelector('select[name="severity"]') as HTMLSelectElement)?.value as CompliancePolicy['severity'] || 'medium',
        rule: (form.querySelector('#rule') as HTMLTextAreaElement).value,
        is_active: selectedPolicy?.is_active ?? true,
      };

      let response;
      if (selectedPolicy?.id) {
        const updatePayload: CompliancePolicy = {
          ...selectedPolicy,
          ...policyData,
          updated_at: new Date().toISOString(),
        };
        response = await apiPut<CompliancePolicy>(`/api/compliance/policies/${selectedPolicy.id}`, updatePayload);
      } else {
        const createPayload: Omit<CompliancePolicy, 'id'> = {
          ...policyData,
          compliance: 0,
          history: [],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        } as Omit<CompliancePolicy, 'id'>;
        response = await apiPost<CompliancePolicy>('/api/compliance/policies', createPayload);
      }
      
      if (response.error || !response.data) {
        throw new Error(response.error || 'Failed to save policy: No data returned');
      }
      
      toast({
        title: t('common:toast.success'),
        description: t('compliance:toast.policySaved', { name: response.data.name })
      });
      
      setIsDialogOpen(false);
      loadPolicies();
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Failed to save policy";
      setComponentError(errorMessage);
      toast({
        variant: "destructive",
        title: t('compliance:errors.savingPolicy'),
        description: errorMessage
      });
    }
  };

  const handleDelete = async (id: string) => {
    setComponentError(null);
    try {
      const response = await apiDeleteApi(`/api/compliance/policies/${id}`);
      
      if (response.error) {
        throw new Error(response.error || 'Failed to delete policy');
      }
      
      toast({
        title: t('common:toast.success'),
        description: t('compliance:toast.policyDeleted')
      });
      
      loadPolicies();
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Failed to delete policy";
      setComponentError(errorMessage);
      toast({
        variant: "destructive",
        title: t('compliance:errors.deletingPolicy'),
        description: errorMessage
      });
    }
  };

  const overallCompliance = stats.overall_compliance;
  const activePolicies = stats.active_policies;
  const criticalIssues = stats.critical_issues;

  const handleCreateRule = () => {
    setSelectedPolicy(null);
    setIsDialogOpen(true);
  };

  const handleEditRule = (policy: CompliancePolicy) => {
    setSelectedPolicy(policy);
    setIsDialogOpen(true);
  };

  const getComplianceColor = (score: number) => {
    if (score >= 90) return 'text-green-600 dark:text-green-400';
    if (score >= 70) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-red-600 dark:text-red-400';
  };

  const getSeverityBadge = (severity: string) => {
    const variants = {
      low: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
      medium: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
      high: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300',
      critical: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300'
    };
    return variants[severity as keyof typeof variants] || 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300';
  };

  const columns: ColumnDef<CompliancePolicy>[] = [
    {
      accessorKey: "name",
      header: t('common:labels.name'),
      cell: ({ row }) => (
        <div className="font-medium">{row.getValue("name")}</div>
      ),
    },
    {
      accessorKey: "category",
      header: t('common:labels.category'),
      cell: ({ row }) => (
        <Badge variant="outline">{row.getValue("category")}</Badge>
      ),
    },
    {
      accessorKey: "severity",
      header: t('common:labels.severity'),
      cell: ({ row }) => (
        <Badge className={getSeverityBadge(row.getValue("severity"))}>
          {row.getValue("severity")}
        </Badge>
      ),
    },
    {
      accessorKey: "compliance",
      header: t('common:labels.compliance'),
      cell: ({ row }) => (
        <div className={`font-semibold ${getComplianceColor(row.getValue("compliance"))}`}>
          {row.getValue("compliance")}%
        </div>
      ),
    },
    {
      accessorKey: "is_active",
      header: t('common:labels.status'),
      cell: ({ row }) => (
        <Badge variant={row.getValue("is_active") ? "default" : "secondary"}>
          {row.getValue("is_active") ? t('common:labels.active') : t('common:labels.inactive')}
        </Badge>
      ),
    },
    {
      id: "actions",
      enableHiding: false,
      cell: ({ row }) => {
        const policy = row.original;
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="h-8 w-8 p-0">
                <span className="sr-only">{t('common:actions.open')}</span>
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>{t('common:labels.actions')}</DropdownMenuLabel>
              <DropdownMenuItem onClick={() => handleEditRule(policy)}>
                {t('common:actions.edit')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-red-600 dark:text-red-400"
                onClick={() => handleDelete(policy.id)}
              >
                {t('common:actions.delete')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ];

  return (
    <div className="py-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold mb-6 flex items-center gap-2">
          <Scale className="w-8 h-8" />
          {t('compliance:title')}
        </h1>
        <Button onClick={handleCreateRule} className="gap-2" disabled={apiIsLoading}>
          <Plus className="h-4 w-4" />
          {t('compliance:createRule')}
        </Button>
      </div>

      {apiIsLoading && !isDialogOpen && (
        <div className="space-y-4">
          <StatCardsSkeleton count={4} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" />
          <ListViewSkeleton columns={6} rows={5} showToolbar={false} toolbarButtons={0} />
        </div>
      )}

      {componentError && (
         <div className="bg-red-100 border border-red-400 text-red-700 dark:bg-red-900/30 dark:border-red-800 dark:text-red-400 px-4 py-3 rounded relative mb-4" role="alert">
           <strong className="font-bold">Error: </strong>
           <span className="block sm:inline">{componentError}</span>
         </div>
      )}

      {!apiIsLoading && !componentError && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">{t('compliance:stats.overallCompliance')}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className={`text-3xl font-bold ${getComplianceColor(overallCompliance)}`}>
                  {overallCompliance.toFixed(0)}%
                </div>
                <p className="text-sm text-muted-foreground mt-2">{t('compliance:stats.acrossAllRules')}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">{t('compliance:stats.activeRules')}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{activePolicies}</div>
                <p className="text-sm text-muted-foreground mt-2">{t('compliance:stats.currentlyEnforced')}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">{t('compliance:stats.criticalIssues')}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold text-red-600 dark:text-red-400">{criticalIssues}</div>
                <p className="text-sm text-muted-foreground mt-2">{t('compliance:stats.requireAttention')}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">{t('compliance:stats.lastUpdated')}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{t('compliance:stats.today')}</div>
                <p className="text-sm text-muted-foreground mt-2">12:30 PM</p>
              </CardContent>
            </Card>
          </div>

          <DataTable
            columns={columns}
            data={policies}
            searchColumn="name"
            storageKey="compliance-policies-sort"
            onRowClick={(row) => navigate(`${pathname}/policies/${row.original.id}`)}
          />

          <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>
                  {selectedPolicy ? t('compliance:editRule') : t('compliance:createNewRule')}
                </DialogTitle>
              </DialogHeader>
              <form onSubmit={handleSave} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="name">{t('common:labels.name')}</Label>
                  <Input
                    id="name"
                    defaultValue={selectedPolicy?.name}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="description">{t('common:labels.description')}</Label>
                  <Textarea
                    id="description"
                    defaultValue={selectedPolicy?.description}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="category">{t('common:labels.category')}</Label>
                  <Select name="category" defaultValue={selectedPolicy?.category}>
                    <SelectTrigger>
                      <SelectValue placeholder={t('common:placeholders.selectCategory')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="Security">{t('compliance:categories.security')}</SelectItem>
                      <SelectItem value="Data Quality">{t('compliance:categories.dataQuality')}</SelectItem>
                      <SelectItem value="Privacy">{t('compliance:categories.privacy')}</SelectItem>
                      <SelectItem value="Governance">{t('compliance:categories.governance')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="severity">{t('common:labels.severity')}</Label>
                  <Select name="severity" defaultValue={selectedPolicy?.severity}>
                    <SelectTrigger>
                      <SelectValue placeholder={t('common:placeholders.selectSeverity')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="low">{t('compliance:severity.low')}</SelectItem>
                      <SelectItem value="medium">{t('compliance:severity.medium')}</SelectItem>
                      <SelectItem value="high">{t('compliance:severity.high')}</SelectItem>
                      <SelectItem value="critical">{t('compliance:severity.critical')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="rule">{t('compliance:form.ruleCode')}</Label>
                  <Textarea
                    id="rule"
                    defaultValue={selectedPolicy?.rule}
                    className="font-mono text-sm"
                    rows={8}
                    required
                    placeholder={t('compliance:form.rulePlaceholder')}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="failure_message">{t('compliance:form.failureMessage')}</Label>
                  <Textarea
                    id="failure_message"
                    defaultValue={selectedPolicy?.failure_message}
                    rows={3}
                    placeholder={t('compliance:form.failureMessagePlaceholder')}
                  />
                  <p className="text-xs text-muted-foreground">
                    {t('compliance:form.failureMessageHint')}
                  </p>
                </div>
                <DialogFooter>
                  <Button type="button" variant="outline" onClick={() => setIsDialogOpen(false)} disabled={apiIsLoading}>
                    {t('common:actions.cancel')}
                  </Button>
                  <Button type="submit" disabled={apiIsLoading}>
                    {apiIsLoading ? t('common:states.saving') : t('common:actions.save')}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        </>
      )}
    </div>
  );
}
