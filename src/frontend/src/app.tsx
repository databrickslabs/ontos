import { useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from './components/theme';
import Layout from './components/layout/layout';
import { TooltipProvider } from './components/ui/tooltip';
import { Toaster } from './components/ui/toaster';
import { useUserStore } from './stores/user-store';
import { usePermissions } from './stores/permissions-store';
import { useNotificationsStore } from './stores/notifications-store';
import './i18n/config'; // Initialize i18n

// Import views
import Home from './views/home';
import DataDomainsView from './views/data-domains';
import DataProducts from './views/data-products';
import DataProductDetails from './views/data-product-details';
import DataContracts from './views/data-contracts';
import DataContractDetails from './views/data-contract-details';
import Datasets from './views/datasets';
import DatasetDetails from './views/dataset-details';
import BusinessGlossaryView from './views/business-glossary';
import Compliance from './views/compliance';
import CompliancePolicyDetails from './views/compliance-policy-details';
import ComplianceRunDetails from './views/compliance-run-details';
import CreateUcObject from './views/create-uc-object';
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
import Settings from './views/settings';
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
import GraphExplorer from './views/graph-explorer';

export default function App() {
  const fetchUserInfo = useUserStore((state: any) => state.fetchUserInfo);
  const { fetchPermissions, fetchAvailableRoles } = usePermissions();
  const { startPolling: startNotificationPolling, stopPolling: stopNotificationPolling } = useNotificationsStore();

  useEffect(() => {
    console.log("App component mounted, fetching initial user info and permissions...");
    fetchUserInfo();
    fetchPermissions();
    fetchAvailableRoles();

    console.log("Starting notification polling...");
    startNotificationPolling();

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
          v7_startTransition: true 
        }}>
          <Layout>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/data-domains" element={<DataDomainsView />} />
              <Route path="/data-domains/:domainId" element={<DataDomainDetailsView />} />
              <Route path="/data-products" element={<DataProducts />} />
              <Route path="/data-products/:productId" element={<DataProductDetails />} />
              <Route path="/data-contracts" element={<DataContracts />} />
              <Route path="/data-contracts/:contractId" element={<DataContractDetails />} />
              <Route path="/datasets" element={<Datasets />} />
              <Route path="/datasets/:datasetId" element={<DatasetDetails />} />
              <Route path="/semantic-models" element={<BusinessGlossaryView />} />
              <Route path="/master-data" element={<MasterDataManagement />} />
              <Route path="/entitlements" element={<Entitlements />} />
              <Route path="/security" element={<SecurityFeatures />} />
              <Route path="/entitlements-sync" element={<EntitlementsSync />} />
              <Route path="/compliance" element={<Compliance />} />
              <Route path="/compliance/policies/:policyId" element={<CompliancePolicyDetails />} />
              <Route path="/compliance/runs/:runId" element={<ComplianceRunDetails />} />
              <Route path="/workflows" element={<Workflows />} />
              <Route path="/workflows/new" element={<WorkflowDesignerView />} />
              <Route path="/workflows/:workflowId" element={<WorkflowDesignerView />} />
              <Route path="/catalog-commander" element={<CatalogCommander />} />
              <Route path="/create-uc" element={<CreateUcObject />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/settings/:tab" element={<Settings />} />
              <Route path="/teams" element={<TeamsView />} />
              <Route path="/projects" element={<ProjectsView />} />
              <Route path="/search" element={<SearchView />} />
              <Route path="/search/llm" element={<SearchView />} />
              <Route path="/search/index" element={<SearchView />} />
              <Route path="/search/concepts" element={<SearchView />} />
              <Route path="/search/kg" element={<SearchView />} />
              <Route path="/about" element={<About />} />
              <Route path="/user-guide" element={<UserGuide />} />
              <Route path="/database-schema" element={<DatabaseSchema />} />
              <Route path="/user-docs/:docName" element={<DocumentationViewer />} />
              <Route path="/estate-manager" element={<EstateManager />} />
              <Route path="/estates/:estateId" element={<EstateDetailsView />} />
              <Route path="/data-asset-reviews" element={<DataAssetReviews />} />
              <Route path="/data-asset-reviews/:requestId" element={<DataAssetReviewDetails />} />
              <Route path="/data-catalog" element={<DataCatalog />} />
              <Route path="/data-catalog/*" element={<DataCatalogDetails />} />
              <Route path="/graph-explorer" element={<GraphExplorer />} />
              <Route path="/audit" element={<AuditTrail />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Layout>
        </Router>
        <Toaster />
      </TooltipProvider>
    </ThemeProvider>
  );
}
