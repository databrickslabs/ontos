import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Loader2, ShieldX } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import usePermissionsStore, { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import useBreadcrumbStore from '@/stores/breadcrumb-store';

interface SettingsPageWrapperProps {
  title: string;
  /**
   * Per-sub-page permission ID (e.g. `settings-general`, `settings-git`).
   * Access is granted only if the user holds at least `Read-only` on BOTH
   * the parent `settings` feature (the layout gate) AND this specific
   * sub-page permission.
   */
  permissionId: string;
  children: React.ReactNode;
}

/**
 * Shared wrapper for standalone settings pages.
 * Handles permission check, loading state, and breadcrumb setup.
 */
export default function SettingsPageWrapper({ title, permissionId, children }: SettingsPageWrapperProps) {
  const { t } = useTranslation(['settings', 'common']);
  const { isLoading: permissionsLoading, hasPermission } = usePermissions();
  // Distinguish "store not yet initialized" from "user lacks access" — without
  // this guard we'd flash the Access Denied panel on first mount before the
  // permissions fetch has even started.
  const initAttempted = usePermissionsStore((s) => s._initAttempted);
  const isInitializing = usePermissionsStore((s) => s._isInitializing);
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  const hasLayoutAccess = hasPermission('settings', FeatureAccessLevel.READ_ONLY);
  const hasPageAccess = hasPermission(permissionId, FeatureAccessLevel.READ_ONLY);
  const hasSettingsAccess = hasLayoutAccess && hasPageAccess;

  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle(title);
    return () => {
      setStaticSegments([]);
      setDynamicTitle(null);
    };
  }, [title, setStaticSegments, setDynamicTitle]);

  if (permissionsLoading || isInitializing || !initAttempted) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!hasSettingsAccess) {
    return (
      <div className="max-w-2xl mx-auto">
        <Alert variant="destructive" className="border-2">
          <ShieldX className="h-5 w-5" />
          <AlertTitle className="text-lg font-semibold">
            {t('settings:accessDenied.title', 'Access Denied')}
          </AlertTitle>
          <AlertDescription className="mt-2">
            <p className="mb-4">
              {t('settings:accessDenied.message', 'You do not have permission to access this page. This page is restricted to users with administrative privileges.')}
            </p>
            <p className="text-sm">
              {t('settings:accessDenied.action', 'If you believe you should have access, please contact your administrator or ')}
              <Link to="/" className="font-semibold underline hover:text-destructive-foreground">
                {t('settings:accessDenied.returnHome', 'return to the home page')}
              </Link>
              {t('settings:accessDenied.requestRole', ' to request an appropriate role.')}
            </p>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return <>{children}</>;
}
