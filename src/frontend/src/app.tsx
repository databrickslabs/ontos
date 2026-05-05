import { useEffect, useState, lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './components/theme';
import Layout from './components/layout/layout';
import { TooltipProvider } from './components/ui/tooltip';
import { Toaster } from './components/ui/toaster';
import { RouteErrorBoundary } from './components/layout/route-error-boundary';
import { useUserStore } from './stores/user-store';
import { usePermissions } from './stores/permissions-store';
import { useNotificationsStore } from './stores/notifications-store';
import ApprovalWizardDialog from './components/workflows/approval-wizard-dialog';
import './i18n/config'; // Initialize i18n

// Import views
import Home from './views/home';
import DataDomainsView from './views/data-domains';
import DataProducts from './views/data-products';
import DataProductDetails from './views/data-product-details';
import DataContracts from './views/data-contracts';
import DataContractDetails from './views/data-contract-details';
import BusinessTermsView from './views/business-terms';
import Compliance from './views/compliance';
import CompliancePolicyDetails from './views/compliance-policy-details';
import ComplianceRunDetails from './views/compliance-run-details';
import EstateManager from './views/estate-manager';
import EstateDetailsView from './views/estate-details';
import MasterDataManagement from './views/master-data-management';
import SecurityFeatures from './views/security-features';
import Entitlements from './views/entitlements';
import EntitlementsSync from './views/entitlements-sync';
import DataAssetReviews from './views/data-asset-reviews';
import DataAssetReviewDetails from './views/data-asset-review-details';
import DataCatalog from './views/data-catalog';
import DataCatalogDetails from './views/data-catalog-details';
import CatalogCommander from './views/catalog-commander';
import About from './views/about';
import UserGuide from './views/user-guide';
import DocumentationViewer from './views/documentation-viewer';
import DatabaseSchema from './views/database-schema';
import NotFound from './views/not-found';
import DataDomainDetailsView from "@/views/data-domain-details";
import SearchView from './views/search';
import TeamsView from './views/teams';
import ProjectsView from './views/projects';
import AuditTrail from './views/audit-trail';
import WorkflowDesignerView from './views/workflow-designer';
import Workflows from './views/workflows';

// Marketplace
import MarketplaceView from './components/home/marketplace-view';

// New views added in this branch
import AssetExplorerView from './views/asset-explorer';
import AssetDetailView from './views/asset-detail';
import AssetTypesView from './views/asset-types';
import BusinessRolesView from './views/business-roles';
import DeliveryMethodsView from './views/delivery-methods';
import BusinessOwnersView from './views/business-owners';
import MyProducts from './views/my-products';
import MyRequests from './views/my-requests';
import OntologySearchView from './views/ontology-search';
import OntologyHomeView from './views/ontology-home';
import CollectionsView from './views/collections';
import HierarchyBrowserView from './views/hierarchy-browser';
import SchemaImporterView from './views/schema-importer';
import OwnerConsumersView from './views/owner-consumers';
import OntologyGeneratorView from './views/ontology-generator';

// Dev/prototype components
const DevLineageView = lazy(() => import('./components/lineage/dev-lineage-route'));

// Concepts layout
import ConceptsLayout from './components/concepts/concepts-layout';

// Settings layout and sub-views
import SettingsLayout from './components/settings/settings-layout';
import SettingsGeneralView from './views/settings-general';
import SettingsGitView from './views/settings-git';
import SettingsDeliveryView from './views/settings-delivery';
import SettingsJobsView from './views/settings-jobs';
import SettingsRolesView from './views/settings-roles';
import SettingsTagsView from './views/settings-tags';
import SettingsSearchView from './views/settings-search';
import SettingsMcpView from './views/settings-mcp';
import SettingsUiView from './views/settings-ui';
import SettingsConnectorsView from './views/settings-connectors';
import SettingsSemanticModelsView from './views/settings-semantic-models';
import SettingsCertificationLevelsView from './views/settings-certification-levels';

export default function App() {
  const fetchUserInfo = useUserStore((state: any) => state.fetchUserInfo);
  const { fetchPermissions, fetchAvailableRoles } = usePermissions();
  const { startPolling: startNotificationPolling, stopPolling: stopNotificationPolling } = useNotificationsStore();

  // First-access disclaimer: any active `on_first_access` Approval Workflow the
  // current user hasn't yet accepted at the workflow's current version is
  // returned by GET /api/user/pending-approvals. We render the existing
  // ApprovalWizardDialog against entity_type=user / entity_id=<email>.
  // Walking the wizard creates an `agreements` row keyed on
  // (created_by, workflow_id, workflow_version) — that IS the consent record;
  // no localStorage flag, no separate settings table.
  const [pendingFirstAccess, setPendingFirstAccess] = useState<{
    workflow_id: string;
    workflow_name: string;
    workflow_version: number;
  } | null>(null);
  const [pendingUserEmail, setPendingUserEmail] = useState<string>('');

  useEffect(() => {
    console.log("App component mounted, fetching initial user info and permissions...");
    fetchUserInfo();
    fetchPermissions();
    fetchAvailableRoles();

    console.log("Starting notification polling...");
    startNotificationPolling();

    // Fetch pending on_first_access workflows and (if any) launch the wizard
    // for the first one. Subsequent items get prompted on the next app mount
    // after the current one is accepted.
    Promise.all([
      fetch('/api/user/pending-approvals').then(r => r.ok ? r.json() : { workflows: [] }),
      fetch('/api/user/details').then(r => r.ok ? r.json() : null),
    ])
      .then(([pending, userDetails]) => {
        const list = Array.isArray(pending?.workflows) ? pending.workflows : [];
        const email = (userDetails?.email || userDetails?.user || '') as string;
        if (list.length > 0 && email) {
          setPendingUserEmail(email);
          setPendingFirstAccess(list[0]);
        }
      })
      .catch((err) => {
        // Non-fatal: first-access prompts are best-effort.
        console.warn('Failed to fetch pending first-access approvals:', err);
      });

    return () => {
        console.log("App component unmounting, stopping notification polling...");
        stopNotificationPolling();
    };
  }, [fetchUserInfo, fetchPermissions, fetchAvailableRoles, startNotificationPolling, stopNotificationPolling]);

  return (
    <ThemeProvider defaultTheme="system" storageKey="ucapp-theme">
      <TooltipProvider>
        <Router future={{ 
          v7_relativeSplatPath: true,
        }}>
          <Layout>
            <RouteErrorBoundary>
            <Routes>
              <Route path="/" element={<Home />} />

              {/* Data Products */}
              <Route path="/data-domains" element={<Navigate to="/settings/data-domains" replace />} />
              <Route path="/data-products" element={<DataProducts />} />
              <Route path="/data-products/:productId" element={<DataProductDetails />} />
              <Route path="/data-contracts" element={<DataContracts />} />
              <Route path="/data-contracts/:contractId" element={<DataContractDetails />} />
              <Route path="/my-products" element={<MyProducts />} />
              <Route path="/my-products/:productId" element={<DataProductDetails />} />
              <Route path="/my-requests" element={<MyRequests />} />
              <Route path="/marketplace" element={<MarketplaceView />} />
              <Route path="/owner-consumers" element={<OwnerConsumersView />} />
              <Route path="/teams" element={<Navigate to="/settings/teams" replace />} />
              <Route path="/projects" element={<Navigate to="/settings/projects" replace />} />

              {/* Governance */}
              <Route path="/assets" element={<AssetExplorerView />} />
              <Route path="/assets/:assetId" element={<AssetDetailView />} />
              <Route path="/asset-types" element={<Navigate to="/settings/asset-types" replace />} />
              <Route path="/business-roles" element={<Navigate to="/settings/business-roles" replace />} />
              <Route path="/business-owners" element={<BusinessOwnersView />} />
              <Route path="/schema-importer" element={<SchemaImporterView />} />
              <Route path="/ontology-generator" element={<Navigate to="/concepts/generator" replace />} />
              <Route path="/data-asset-reviews" element={<DataAssetReviews />} />
              <Route path="/data-asset-reviews/:requestId" element={<DataAssetReviewDetails />} />
              <Route path="/data-catalog" element={<DataCatalog />} />
              <Route path="/data-catalog/*" element={<DataCatalogDetails />} />

              {/* Concepts - sidebar layout with nested routes */}
              <Route path="/concepts" element={<ConceptsLayout />}>
                <Route index element={<Navigate to="/concepts/browser" replace />} />
                <Route path="collections" element={<CollectionsView />} />
                <Route path="browser" element={<BusinessTermsView />} />
                <Route path="search" element={<OntologySearchView />} />
                <Route path="graph" element={<OntologyHomeView />} />
                <Route path="hierarchy" element={<HierarchyBrowserView />} />
                <Route path="generator" element={<OntologyGeneratorView />} />
              </Route>
              {/* Backward compat: redirect old concept paths */}
              <Route path="/semantic-models" element={<Navigate to="/concepts/browser" replace />} />
              <Route path="/collections" element={<Navigate to="/concepts/collections" replace />} />
              <Route path="/ontology" element={<Navigate to="/concepts/search" replace />} />
              <Route path="/ontology-graph" element={<Navigate to="/concepts/graph" replace />} />
              <Route path="/hierarchy" element={<Navigate to="/concepts/hierarchy" replace />} />

              {/* Operations */}
              <Route path="/compliance" element={<Compliance />} />
              <Route path="/compliance/policies/:policyId" element={<CompliancePolicyDetails />} />
              <Route path="/compliance/runs/:runId" element={<ComplianceRunDetails />} />
              {/* Backward compat: standalone workflow routes */}
              <Route path="/workflows" element={<Workflows />} />
              <Route path="/workflows/new" element={<WorkflowDesignerView />} />
              <Route path="/workflows/:workflowId" element={<WorkflowDesignerView />} />
              <Route path="/catalog-commander" element={<CatalogCommander />} />
              <Route path="/master-data" element={<MasterDataManagement />} />
              <Route path="/estate-manager" element={<EstateManager />} />
              <Route path="/estates/:estateId" element={<EstateDetailsView />} />

              {/* Security */}
              <Route path="/security-features" element={<SecurityFeatures />} />
              <Route path="/entitlements" element={<Entitlements />} />
              <Route path="/entitlements-sync" element={<EntitlementsSync />} />

              {/* Settings - sidebar layout with nested routes */}
              <Route path="/settings" element={<SettingsLayout />}>
                <Route index element={<Navigate to="/settings/general" replace />} />
                <Route path="general" element={<SettingsGeneralView />} />
                <Route path="git" element={<SettingsGitView />} />
                <Route path="delivery" element={<SettingsDeliveryView />} />
                <Route path="jobs" element={<SettingsJobsView />} />
                <Route path="roles" element={<SettingsRolesView />} />
                <Route path="tags" element={<SettingsTagsView />} />
                <Route path="search" element={<SettingsSearchView />} />
                <Route path="mcp" element={<SettingsMcpView />} />
                <Route path="ui" element={<SettingsUiView />} />
                <Route path="connectors" element={<SettingsConnectorsView />} />
                <Route path="semantic-models" element={<SettingsSemanticModelsView />} />
                <Route path="certification-levels" element={<SettingsCertificationLevelsView />} />
                <Route path="workflows" element={<Workflows />} />
                <Route path="workflows/new" element={<WorkflowDesignerView />} />
                <Route path="workflows/:workflowId" element={<WorkflowDesignerView />} />
                <Route path="audit" element={<AuditTrail />} />
                <Route path="data-domains" element={<DataDomainsView />} />
                <Route path="data-domains/:domainId" element={<DataDomainDetailsView />} />
                <Route path="business-roles" element={<BusinessRolesView />} />
                <Route path="delivery-methods" element={<DeliveryMethodsView />} />
                <Route path="asset-types" element={<AssetTypesView />} />
                <Route path="teams" element={<TeamsView />} />
                <Route path="projects" element={<ProjectsView />} />
              </Route>

              {/* System / Utility */}
              <Route path="/search" element={<SearchView />} />
              <Route path="/search/llm" element={<SearchView />} />
              <Route path="/search/index" element={<SearchView />} />
              <Route path="/audit" element={<Navigate to="/settings/audit" replace />} />
              <Route path="/about" element={<About />} />
              <Route path="/user-guide" element={<UserGuide />} />
              <Route path="/database-schema" element={<DatabaseSchema />} />
              <Route path="/user-docs/:docName" element={<DocumentationViewer />} />

              {/* Temporary dev route for lineage column view prototype */}
              <Route path="/dev/lineage" element={<Suspense fallback={<div className="flex items-center justify-center h-96">Loading…</div>}><DevLineageView /></Suspense>} />

              <Route path="*" element={<NotFound />} />
            </Routes>
            </RouteErrorBoundary>
          </Layout>
        </Router>
        <Toaster />
        {pendingFirstAccess && pendingUserEmail && (
          <ApprovalWizardDialog
            isOpen={true}
            onOpenChange={(open) => { if (!open) setPendingFirstAccess(null); }}
            entityType="user"
            entityId={pendingUserEmail}
            entityName={pendingUserEmail}
            preselectedWorkflowId={pendingFirstAccess.workflow_id}
            autoStartWithPreselected={true}
            onComplete={() => setPendingFirstAccess(null)}
          />
        )}
      </TooltipProvider>
    </ThemeProvider>
  );
}
