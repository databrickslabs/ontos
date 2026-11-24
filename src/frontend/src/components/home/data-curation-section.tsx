import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Globe, Sparkles, Database, AlertCircle } from 'lucide-react';
import React from 'react';
import SelfServiceDialog from '@/components/data-contracts/self-service-dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { useApi } from '@/hooks/use-api';

export default function DataCurationSection() {
  const { t } = useTranslation('home');
  const [isSelfServiceOpen, setIsSelfServiceOpen] = React.useState(false);
  const [initialType, setInitialType] = React.useState<'catalog' | 'schema' | 'table'>('table');
  const [showTeamMembershipAlert, setShowTeamMembershipAlert] = React.useState(false);
  const [userTeams, setUserTeams] = React.useState<any[]>([]);
  const [teamsLoaded, setTeamsLoaded] = React.useState(false);
  const { get: apiGet } = useApi();

  // Fetch user teams on component mount
  React.useEffect(() => {
    const fetchUserTeams = async () => {
      try {
        const response = await apiGet<any[]>('/api/user/teams');
        if (response.data && !response.error) {
          setUserTeams(response.data);
        }
      } catch (error) {
        console.error('Failed to fetch user teams:', error);
      } finally {
        setTeamsLoaded(true);
      }
    };
    fetchUserTeams();
  }, [apiGet]);

  const handleCreateClick = (type: 'catalog' | 'schema' | 'table') => {
    // Check if user is in any team
    if (teamsLoaded && userTeams.length === 0) {
      setShowTeamMembershipAlert(true);
      return;
    }
    
    setInitialType(type);
    setIsSelfServiceOpen(true);
  };

  return (
    <section className="mb-16">
      <h2 className="text-2xl font-semibold mb-4">{t('dataCurationSection.title')}</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        <Card className="h-full">
          <CardHeader>
            <div className="flex items-center gap-3"><Database className="h-6 w-6 text-primary" /><CardTitle>{t('dataCurationSection.createDataset.title')}</CardTitle></div>
            <CardDescription>{t('dataCurationSection.createDataset.description')}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="default" disabled={!teamsLoaded} onClick={() => handleCreateClick('table')} className="flex items-center gap-2"><Sparkles className="h-4 w-4" /> Self-Service</Button>
          </CardContent>
        </Card>
        <Card className="h-full">
          <CardHeader>
            <div className="flex items-center gap-3"><Globe className="h-6 w-6 text-primary" /><CardTitle>{t('dataCurationSection.createSchema.title')}</CardTitle></div>
            <CardDescription>{t('dataCurationSection.createSchema.description')}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="default" disabled={!teamsLoaded} onClick={() => handleCreateClick('schema')} className="flex items-center gap-2"><Sparkles className="h-4 w-4" /> Self-Service</Button>
          </CardContent>
        </Card>
        <Card className="h-full">
          <CardHeader>
            <div className="flex items-center gap-3"><Globe className="h-6 w-6 text-primary" /><CardTitle>{t('dataCurationSection.createCatalog.title')}</CardTitle></div>
            <CardDescription>{t('dataCurationSection.createCatalog.description')}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="default" disabled={!teamsLoaded} onClick={() => handleCreateClick('catalog')} className="flex items-center gap-2"><Sparkles className="h-4 w-4" /> Self-Service</Button>
          </CardContent>
        </Card>
      </div>
      
      {/* Self-Service Dialog */}
      <SelfServiceDialog isOpen={isSelfServiceOpen} onOpenChange={setIsSelfServiceOpen} initialType={initialType} />
      
      {/* Team Membership Alert Dialog */}
      <AlertDialog open={showTeamMembershipAlert} onOpenChange={setShowTeamMembershipAlert}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <AlertCircle className="h-5 w-5 text-amber-500" />
              Team Membership Required
            </AlertDialogTitle>
            <AlertDialogDescription>
              You need to be a member of at least one team to create data assets. 
              Please join a project or request access to an existing project from the project selector in the navigation bar.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogAction>OK</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}


