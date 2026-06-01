import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Shield, UserPlus, Info } from 'lucide-react';
import { ListItemSkeleton } from '@/components/common/list-view-skeleton';
import { usePermissions } from '@/stores/permissions-store';
import { AppRole } from '@/types/settings';
import RequestRoleAccessDialog from '@/components/settings/request-role-access-dialog';

interface RequestRoleSectionProps {
  maxItems?: number;
}

export default function RequestRoleSection({ maxItems = 6 }: RequestRoleSectionProps) {
  const { t } = useTranslation('home');
  const { requestableRoles, isLoading } = usePermissions();
  const [selectedRole, setSelectedRole] = useState<AppRole | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleRequestClick = (role: AppRole) => {
    setSelectedRole(role);
    setDialogOpen(true);
  };

  const displayedRoles = requestableRoles.slice(0, maxItems);

  if (isLoading) {
    return (
      <section className="mb-16">
        <h2 className="text-2xl font-semibold mb-4">{t('requestRoleSection.title', 'Roles')}</h2>
        <Card>
          <CardContent className="py-6">
            <ListItemSkeleton count={3} height="h-12" className="space-y-2" />
          </CardContent>
        </Card>
      </section>
    );
  }

  if (!requestableRoles || requestableRoles.length === 0) {
    return null; // Don't show section if no roles are requestable
  }

  return (
    <section className="mb-16">
      <h2 className="text-2xl font-semibold mb-4">{t('requestRoleSection.title', 'Roles')}</h2>

      <Card>
        <CardHeader>
          <CardTitle>{t('requestRoleSection.cardTitle', 'Available Roles')}</CardTitle>
        </CardHeader>
        <CardContent>
          {/* Role Cards Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {displayedRoles.map((role) => (
              <Card 
                key={role.id} 
                className="group relative overflow-hidden border hover:border-primary/50 hover:shadow-md transition-all duration-200"
              >
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2">
                      <Shield className="h-5 w-5 text-primary/70" />
                      <CardTitle className="text-base font-semibold">
                        {role.name}
                      </CardTitle>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {role.description ? (
                    <p className="text-sm text-muted-foreground line-clamp-2">
                      {role.description}
                    </p>
                  ) : (
                    <p className="text-sm text-muted-foreground italic">
                      {t('requestRoleSection.noDescription', 'No description available')}
                    </p>
                  )}
                  <Button 
                    onClick={() => handleRequestClick(role)}
                    className="w-full"
                    size="sm"
                  >
                    <UserPlus className="mr-2 h-4 w-4" />
                    {t('requestRoleSection.requestAccess', 'Request Access')}
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Show more message if there are more roles */}
          {requestableRoles.length > maxItems && (
            <p className="text-sm text-muted-foreground text-center mt-4">
              {t('requestRoleSection.moreRoles', 'And {{count}} more roles available...', { count: requestableRoles.length - maxItems })}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Info Alert outside the card like other sections */}
      <Alert variant="default" className="mt-4">
        <Info className="h-4 w-4" />
        <AlertDescription>
          {t('requestRoleSection.info', 'After submitting a request, an administrator will review it and you will be notified of the decision via the notification bell.')}
        </AlertDescription>
      </Alert>

      {/* Request Dialog */}
      {selectedRole && (
        <RequestRoleAccessDialog
          isOpen={dialogOpen}
          onOpenChange={setDialogOpen}
          roleId={selectedRole.id}
          roleName={selectedRole.name}
          roleDescription={selectedRole.description || undefined}
        />
      )}
    </section>
  );
}

