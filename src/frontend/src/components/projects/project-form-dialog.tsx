import { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import TagSelector from '@/components/ui/tag-selector';
import type { AssignedTag as _AssignedTag } from '@/components/ui/tag-chip';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Loader2, FolderOpen, Users, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { ProjectRead, ProjectCreate, ProjectUpdate } from '@/types/project';
import { TeamSummary } from '@/types/team';

// Form schema
const tagSchema = z.union([
  z.string(),
  z.record(z.any()), // Allows object tags during form state
]);

const projectFormSchema = z.object({
  name: z.string().min(1, 'Project name is required'),
  title: z.string().optional(),
  description: z.string().optional(),
  tags: z.array(tagSchema).optional(),
  team_ids: z.array(z.string()).optional(),
  project_type: z.enum(['PERSONAL', 'TEAM']).optional(),
});

type ProjectFormData = z.infer<typeof projectFormSchema>;

interface ProjectFormDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  project?: ProjectRead | null;
  onSubmitSuccess: (project: ProjectRead) => void;
}

export function ProjectFormDialog({
  isOpen,
  onOpenChange,
  project,
  onSubmitSuccess,
}: ProjectFormDialogProps) {
  const [availableTeams, setAvailableTeams] = useState<TeamSummary[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { get: apiGet, post: apiPost, put: apiPut } = useApi();
  const { toast } = useToast();
  const { t } = useTranslation(['projects', 'common']);

  const form = useForm<ProjectFormData>({
    resolver: zodResolver(projectFormSchema),
    defaultValues: {
      name: '',
      title: '',
      description: '',
      tags: [],
      team_ids: [],
      project_type: 'TEAM',
    },
  });

  // Fetch data when dialog opens
  useEffect(() => {
    if (isOpen) {
      fetchAvailableTeams();

      if (project) {
        // Edit mode - populate form with existing project data
        form.reset({
          name: project.name,
          title: project.title || '',
          description: project.description || '',
          tags: (project.tags || []).map((tag: any) => typeof tag === 'string' ? tag : (tag?.name ?? tag?.value ?? tag?.tag ?? '')),
          team_ids: project.teams?.map(team => team.id) || [],
          project_type: (project.project_type as any) || 'TEAM',
        });
      } else {
        // Create mode - reset form
        form.reset({
          name: '',
          title: '',
          description: '',
          tags: [],
          team_ids: [],
          project_type: 'TEAM',
        });
      }
    }
  }, [isOpen, project, form]);

  const fetchAvailableTeams = async () => {
    try {
      const response = await apiGet<TeamSummary[]>('/api/teams');
      if (response.data && !response.error) {
        setAvailableTeams(Array.isArray(response.data) ? response.data : []);
      }
    } catch (error) {
      console.error('Failed to fetch teams:', error);
    }
  };

  // Normalize tags for backend submission (supports both string and AssignedTag)
  // Use fully_qualified_name so backend can look up existing tags by FQN
  const normalizeTagsForSubmission = (tags: any[]): (string | { tag_id: string; assigned_value?: string })[] => {
    if (!tags || tags.length === 0) return [];

    return tags.map((tag) => {
      if (typeof tag === 'string') return tag;
      // Prefer fully_qualified_name for existing tags, fallback to tag_id object
      return tag.fully_qualified_name || { tag_id: tag.tag_id || tag.id, assigned_value: tag.assigned_value };
    });
  };

  const handleSubmit = async (data: ProjectFormData) => {
    setIsSubmitting(true);
    try {
      // Normalize tags for backend compatibility
      const normalizedTags = normalizeTagsForSubmission(data.tags || []);

      const cleanedData = {
        ...data,
        tags: normalizedTags,
        team_ids: data.team_ids || [],
        project_type: data.project_type || 'TEAM',
      };

      let response;
      if (project) {
        // Update existing project
        const updateData: ProjectUpdate = {
          name: cleanedData.name,
          title: cleanedData.title || undefined,
          description: cleanedData.description || undefined,
          tags: cleanedData.tags as ProjectUpdate['tags'],
          metadata: undefined,
          project_type: cleanedData.project_type,
        };
        response = await apiPut<ProjectRead>(`/api/projects/${project.id}`, updateData);

        // Handle team assignments separately
        if (cleanedData.team_ids.length > 0) {
          for (const teamId of cleanedData.team_ids) {
            await apiPost(`/api/projects/${project.id}/teams`, { team_id: teamId });
          }
        }
      } else {
        // Create new project
        const createData: ProjectCreate = {
          name: cleanedData.name,
          title: cleanedData.title || undefined,
          description: cleanedData.description || undefined,
          tags: cleanedData.tags as ProjectCreate['tags'],
          metadata: undefined,
          team_ids: cleanedData.team_ids,
          project_type: cleanedData.project_type,
        };
        response = await apiPost<ProjectRead>('/api/projects', createData);
      }

      if (response.error) {
        throw new Error(response.error);
      }

      toast({
        title: project ? t('projects:form.toasts.updatedTitle') : t('projects:form.toasts.createdTitle'),
        description: project
          ? t('projects:form.toasts.updatedDescription', { name: cleanedData.name })
          : t('projects:form.toasts.createdDescription', { name: cleanedData.name }),
      });

      onSubmitSuccess(response.data as ProjectRead);
      onOpenChange(false);
    } catch (error) {
      toast({
        variant: 'destructive',
        title: project ? t('projects:form.toasts.updateFailedTitle') : t('projects:form.toasts.createFailedTitle'),
        description: error instanceof Error ? error.message : t('projects:form.toasts.failedDescription'),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const selectedTeamIds = form.watch('team_ids') || [];
  const selectedTeams = availableTeams.filter(team => selectedTeamIds.includes(team.id));

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-height-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FolderOpen className="w-5 h-5" />
            {project ? t('projects:form.dialog.editTitle') : t('projects:form.dialog.createTitle')}
          </DialogTitle>
          <DialogDescription>
            {project ? t('projects:form.dialog.editDescription') : t('projects:form.dialog.createDescription')}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-6">
            {/* Basic Project Information */}
            <div className="space-y-4">
              <h3 className="text-lg font-medium">{t('projects:form.sections.info')}</h3>

              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('projects:form.labels.name')}</FormLabel>
                    <FormControl>
                      <Input placeholder={t('projects:form.placeholders.name')} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="title"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('projects:form.labels.title')}</FormLabel>
                    <FormControl>
                      <Input placeholder={t('projects:form.placeholders.title')} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('projects:form.labels.description')}</FormLabel>
                    <FormControl>
                      <Textarea placeholder={t('projects:form.placeholders.description')} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="project_type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('projects:form.labels.projectType')}</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder={t('projects:form.placeholders.selectProjectType')} />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="PERSONAL">{t('projects:form.types.PERSONAL')}</SelectItem>
                        <SelectItem value="TEAM">{t('projects:form.types.TEAM')}</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            {/* Team Assignments */}
            <div className="space-y-4">
              <h3 className="text-lg font-medium">{t('projects:form.sections.teams')}</h3>

              <FormField
                control={form.control}
                name="team_ids"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('projects:form.labels.assignTeams')}</FormLabel>
                    <Select
                      onValueChange={(value) => {
                        if (value && !field.value?.includes(value)) {
                          field.onChange([...(field.value || []), value]);
                        }
                      }}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder={t('projects:form.placeholders.assignTeams')} />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {availableTeams
                          .filter((team) => !selectedTeamIds.includes(team.id))
                          .map((team: TeamSummary) => (
                            <SelectItem key={team.id} value={team.id}>
                              <div className="flex items-center justify-between w-full">
                                <span>{team.name}</span>
                                {team.title && (
                                  <span className="text-xs text-muted-foreground ml-2">
                                    {team.title}
                                  </span>
                                )}
                              </div>
                            </SelectItem>
                          ))}
                        {availableTeams.filter(team => !selectedTeamIds.includes(team.id)).length === 0 && (
                          <SelectItem value="none" disabled>
                            {availableTeams.length === 0 ? t('projects:form.placeholders.noTeamsAvailable') : t('projects:form.placeholders.allTeamsAssigned')}
                          </SelectItem>
                        )}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Selected Teams Display */}
              {selectedTeams.length > 0 && (
                <div className="space-y-2">
                  <label className="text-sm font-medium">{t('projects:form.labels.assignedTeams')}</label>
                  <div className="flex flex-wrap gap-2">
                    {selectedTeams.map((team) => (
                      <Badge
                        key={team.id}
                        variant="secondary"
                        className="flex items-center gap-1 px-2 py-1"
                      >
                        <Users className="w-3 h-3" />
                        {team.name}
                        <button
                          type="button"
                          onClick={() => {
                            const currentTeamIds = form.getValues('team_ids') || [];
                            form.setValue('team_ids', currentTeamIds.filter(id => id !== team.id));
                          }}
                          className="ml-1 hover:bg-destructive hover:text-destructive-foreground rounded-full p-0.5"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Tags */}
            <div className="space-y-4">
              <h3 className="text-lg font-medium">{t('projects:form.sections.tags')}</h3>

              <FormField
                control={form.control}
                name="tags"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('projects:form.labels.tags')}</FormLabel>
                    <FormControl>
                      <TagSelector
                        value={(field.value || []) as (string | import('@/components/ui/tag-chip').AssignedTag)[]}
                        onChange={field.onChange}
                        placeholder={t('projects:form.placeholders.selectTags')}
                        allowCreate={true}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={isSubmitting}
              >
                {t('common:actions.cancel')}
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                {project ? t('projects:form.buttons.update') : t('projects:form.buttons.create')}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}