import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ScrollArea } from '@/components/ui/scroll-area';
import { User, Users, FolderKanban, Shield } from 'lucide-react';
import { UserProfileData, TeamRead, ProjectRead } from '@/types/profile';

interface UserProfileDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export default function UserProfileDialog({ open, onOpenChange }: UserProfileDialogProps) {
  const { t } = useTranslation('common');
  const [profileData, setProfileData] = useState<UserProfileData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      fetchProfileData();
    }
  }, [open]);

  const fetchProfileData = async () => {
    setIsLoading(true);
    setError(null);

    try {
      // Fetch all data in parallel
      const [detailsRes, roleRes, teamsRes, projectsRes] = await Promise.all([
        fetch('/api/user/details'),
        fetch('/api/user/actual-role'),
        fetch('/api/user/teams'),
        fetch('/api/user/projects'),
      ]);

      if (!detailsRes.ok) throw new Error('Failed to fetch user details');

      const details = await detailsRes.json();
      const role = roleRes.ok ? (await roleRes.json()).role : null;
      const teams = teamsRes.ok ? await teamsRes.json() : [];
      const projects = projectsRes.ok ? await projectsRes.json() : { owned_projects: [], member_projects: [], accessible_projects: [] };

      setProfileData({
        ...details,
        role,
        teams,
        projects,
      });
    } catch (err: any) {
      console.error('Failed to fetch profile data:', err);
      setError(err.message || 'Failed to load profile data');
    } finally {
      setIsLoading(false);
    }
  };

  const renderLoadingSkeleton = () => (
    <div className="space-y-4">
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-4 w-2/3" />
    </div>
  );

  const renderUserInfo = () => {
    if (!profileData) return null;

    const groups = profileData.groups || [];

    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-sm font-medium text-muted-foreground">Display Name</p>
            <p className="text-sm">{profileData.user || 'N/A'}</p>
          </div>
          <div>
            <p className="text-sm font-medium text-muted-foreground">Email</p>
            <p className="text-sm">{profileData.email || 'N/A'}</p>
          </div>
          <div>
            <p className="text-sm font-medium text-muted-foreground">Username</p>
            <p className="text-sm">{profileData.username || 'N/A'}</p>
          </div>
          <div>
            <p className="text-sm font-medium text-muted-foreground">IP Address</p>
            <p className="text-sm">{profileData.ip || 'N/A'}</p>
          </div>
        </div>

        <div className="space-y-3">
          <div>
            <p className="text-sm font-medium text-muted-foreground mb-2">App Role</p>
            {profileData.role ? (
              <div className="flex items-center gap-2 p-2 rounded-md border bg-card">
                <Shield className="h-4 w-4 text-muted-foreground" />
                <div className="flex-1">
                  <p className="text-sm font-medium">{profileData.role.name}</p>
                  {profileData.role.description && (
                    <p className="text-xs text-muted-foreground">{profileData.role.description}</p>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground italic">No app role assigned</p>
            )}
          </div>

          <div>
            <p className="text-sm font-medium text-muted-foreground mb-2">Groups ({groups.length})</p>
            {groups.length > 0 ? (
              <ScrollArea className="h-[150px] rounded-md border">
                <div className="p-2 space-y-1">
                  {groups.map((group, index) => (
                    <div
                      key={index}
                      className="flex items-center gap-2 p-2 rounded-md hover:bg-accent"
                    >
                      <Users className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="text-sm">{group}</span>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            ) : (
              <p className="text-sm text-muted-foreground italic">No groups assigned</p>
            )}
          </div>
        </div>
      </div>
    );
  };

  const renderMemberships = () => {
    if (!profileData) return null;

    const teams = profileData.teams || [];
    const { owned_projects = [], member_projects = [], accessible_projects = [] } = profileData.projects;
    const allProjects = [...owned_projects, ...member_projects, ...accessible_projects];

    // Remove duplicates based on id
    const uniqueProjects = Array.from(
      new Map(allProjects.map(p => [p.id, p])).values()
    );

    return (
      <div className="space-y-6">
        {/* Teams Section */}
        <div>
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Users className="h-4 w-4" />
            Teams ({teams.length})
          </h3>
          {teams.length > 0 ? (
            <ScrollArea className="h-[200px]">
              <div className="space-y-2">
                {teams.map((team: TeamRead) => (
                  <Card key={team.id}>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm">{team.name}</CardTitle>
                      {team.description && (
                        <CardDescription className="text-xs">{team.description}</CardDescription>
                      )}
                    </CardHeader>
                  </Card>
                ))}
              </div>
            </ScrollArea>
          ) : (
            <p className="text-sm text-muted-foreground italic">Not a member of any teams</p>
          )}
        </div>

        {/* Projects Section */}
        <div>
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <FolderKanban className="h-4 w-4" />
            Projects ({uniqueProjects.length})
          </h3>
          {uniqueProjects.length > 0 ? (
            <ScrollArea className="h-[200px]">
              <div className="space-y-2">
                {uniqueProjects.map((project: ProjectRead) => {
                  const isOwner = owned_projects.some(p => p.id === project.id);
                  const isMember = member_projects.some(p => p.id === project.id);

                  return (
                    <Card key={project.id}>
                      <CardHeader className="pb-3">
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <CardTitle className="text-sm">{project.name}</CardTitle>
                            {project.description && (
                              <CardDescription className="text-xs">{project.description}</CardDescription>
                            )}
                          </div>
                          <div className="flex gap-1">
                            {isOwner && (
                              <Badge variant="default" className="text-xs">Owner</Badge>
                            )}
                            {isMember && !isOwner && (
                              <Badge variant="secondary" className="text-xs">Member</Badge>
                            )}
                            {!isOwner && !isMember && (
                              <Badge variant="outline" className="text-xs">Access</Badge>
                            )}
                          </div>
                        </div>
                      </CardHeader>
                    </Card>
                  );
                })}
              </div>
            </ScrollArea>
          ) : (
            <p className="text-sm text-muted-foreground italic">No projects associated</p>
          )}
        </div>
      </div>
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[80vh]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <User className="h-5 w-5" />
            {t('userMenu.profile')}
          </DialogTitle>
          <DialogDescription>
            View your profile information and memberships
          </DialogDescription>
        </DialogHeader>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Tabs defaultValue="info" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="info">Info</TabsTrigger>
            <TabsTrigger value="memberships">Memberships</TabsTrigger>
          </TabsList>

          <ScrollArea className="h-[400px] mt-4">
            <TabsContent value="info" className="mt-0">
              {isLoading ? renderLoadingSkeleton() : renderUserInfo()}
            </TabsContent>

            <TabsContent value="memberships" className="mt-0">
              {isLoading ? renderLoadingSkeleton() : renderMemberships()}
            </TabsContent>
          </ScrollArea>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
