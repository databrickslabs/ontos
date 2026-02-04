import React, { useState, useEffect, useCallback, useRef } from 'react';
import { MessageSquare, Plus, Trash2, Edit, Send, Users, Filter, Clock, FileText, FolderOpen } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { useProjectContext } from '@/stores/project-store';
import {
  Comment,
  CommentCreate,
  CommentUpdate,
  CommentSidebarProps,
  AudienceTeam,
  AudienceRole,
} from '@/types/comments';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Avatar } from '@/components/ui/avatar';
import { RelativeDate } from '@/components/common/relative-date';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
// Select components removed - unused

interface CommentFormData {
  title: string;
  comment: string;
  selectedTeams: string[];
  selectedRoles: string[];
}

interface TimelineEntry {
  id: string;
  type: 'comment' | 'change';
  entity_type: string;
  entity_id: string;
  title?: string;
  content: string;
  username: string;
  timestamp: string;
  updated_at?: string;
  audience?: string[];
  status?: string;
  metadata?: {
    updated_by?: string;
    action?: string;
  };
}

interface TimelineResponse {
  timeline: TimelineEntry[];
  total_count: number;
  filter_type: string;
}

const CommentSidebar: React.FC<CommentSidebarProps> = ({
  entityType,
  entityId,
  isOpen,
  onToggle,
  className,
  fetchCountOnMount = true,
}) => {
  const { get, post, put, delete: deleteApi, loading } = useApi();
  const { toast } = useToast();
  const { currentProject } = useProjectContext();
  
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [filterType, setFilterType] = useState<'all' | 'comments' | 'changes'>('all');
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingComment, setEditingComment] = useState<Comment | null>(null);
  const [formData, setFormData] = useState<CommentFormData>({
    title: '',
    comment: '',
    selectedTeams: [],
    selectedRoles: [],
  });

  // Ref for the ScrollArea viewport to control scrolling
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  // State for available teams and roles
  const [availableTeams, setAvailableTeams] = useState<AudienceTeam[]>([]);
  const [availableRoles, setAvailableRoles] = useState<AudienceRole[]>([]);

  // Fetch teams for current project
  const fetchTeams = useCallback(async () => {
    if (!currentProject?.id) {
      console.debug('CommentSidebar: No current project, clearing teams');
      setAvailableTeams([]);
      return;
    }

    console.debug(`CommentSidebar: Fetching teams for project ${currentProject.id} (${currentProject.name})`);
    const response = await get<AudienceTeam[]>(`/api/projects/${currentProject.id}/teams`);
    
    if (response.error) {
      console.error('CommentSidebar: Failed to fetch teams:', response.error);
      // Don't show error toast for now - project might not exist
      setAvailableTeams([]);
    } else if (response.data) {
      console.debug(`CommentSidebar: Loaded ${response.data.length} teams:`, response.data);
      setAvailableTeams(response.data);
    } else {
      console.warn('CommentSidebar: No team data returned');
      setAvailableTeams([]);
    }
  }, [currentProject?.id, currentProject?.name, get]);

  // Fetch available app roles
  const fetchRoles = useCallback(async () => {
    console.debug('CommentSidebar: Fetching app roles');
    const response = await get<AudienceRole[]>('/api/settings/roles/summary');
    
    if (response.error) {
      console.error('CommentSidebar: Failed to fetch roles:', response.error);
      // Roles are less critical, just log the error
      setAvailableRoles([]);
    } else if (response.data) {
      console.debug(`CommentSidebar: Loaded ${response.data.length} roles:`, response.data);
      setAvailableRoles(response.data);
    } else {
      console.warn('CommentSidebar: No role data returned');
      setAvailableRoles([]);
    }
  }, [get]);

  const fetchCommentCount = useCallback(async () => {
    if (!entityType || !entityId) {
      console.debug('CommentSidebar: Skipping count fetch - missing entityType or entityId');
      return;
    }

    console.debug(`CommentSidebar: Fetching count for ${entityType}/${entityId}`);

    const projectParam = currentProject?.id ? `&project_id=${currentProject.id}` : '';
    const response = await get<TimelineResponse>(
      `/api/entities/${entityType}/${entityId}/timeline/count?filter_type=all${projectParam}`
    );

    if (response.error) {
      console.warn(
        "CommentSidebar: Failed to load comment count for entity",
        entityType,
        entityId,
        ":", 
        response.error
      );
      return;
    }

    const count = response.data?.total_count || 0;
    console.debug(`CommentSidebar: Setting count to ${count} for ${entityType}/${entityId}`);
    setTotalCount(count);
  }, [entityType, entityId, get]);

  const fetchTimeline = async () => {
    const projectParam = currentProject?.id ? `&project_id=${currentProject.id}` : '';
    const response = await get<TimelineResponse>(
      `/api/entities/${entityType}/${entityId}/timeline?filter_type=${filterType}${projectParam}`
    );
    
    if (response.error) {
      toast({
        title: 'Error',
        description: `Failed to load timeline: ${response.error}`,
        variant: 'destructive',
      });
      return;
    }
    
    setTimeline(response.data.timeline || []);
    setTotalCount(response.data.total_count || 0);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!formData.comment.trim()) {
      toast({
        title: 'Error',
        description: 'Comment content is required',
        variant: 'destructive',
      });
      return;
    }

    // Build audience array with team: and role: prefixes
    const audienceTokens: string[] = [
      ...formData.selectedTeams.map(teamId => `team:${teamId}`),
      ...formData.selectedRoles.map(roleName => `role:${roleName}`),
    ];

    const commentData: CommentCreate | CommentUpdate = {
      title: formData.title || null,
      comment: formData.comment,
      audience: audienceTokens.length > 0 ? audienceTokens : null,
    };

    if (editingComment) {
      // Update existing comment
      const response = await put<Comment>(
        `/api/comments/${editingComment.id}`,
        commentData
      );
      
      if (response.error) {
        toast({
          title: 'Error',
          description: `Failed to update comment: ${response.error}`,
          variant: 'destructive',
        });
        return;
      }
      
      toast({
        title: 'Success',
        description: 'Comment updated successfully',
      });
    } else {
      // Create new comment
      const createData: CommentCreate = {
        entity_id: entityId,
        entity_type: entityType,
        title: formData.title || null,
        comment: formData.comment,
        audience: audienceTokens.length > 0 ? audienceTokens : null,
        project_id: currentProject?.id || null,
      };
      
      const response = await post<Comment>(
        `/api/entities/${entityType}/${entityId}/comments`,
        createData
      );
      
      if (response.error) {
        toast({
          title: 'Error',
          description: `Failed to create comment: ${response.error}`,
          variant: 'destructive',
        });
        return;
      }
      
      toast({
        title: 'Success',
        description: 'Comment created successfully',
      });
    }
    
    // Reset form and refresh timeline
    setFormData({ title: '', comment: '', selectedTeams: [], selectedRoles: [] });
    setEditingComment(null);
    setIsFormOpen(false);
    await fetchTimeline();

    // Update count if we're fetching it on mount (to keep button in sync)
    if (fetchCountOnMount) {
      await fetchCommentCount();
    }
  };

  const handleDelete = async (commentId: string) => {
    if (!confirm('Are you sure you want to delete this comment?')) {
      return;
    }
    
    const response = await deleteApi(`/api/comments/${commentId}`);
    
    if (response.error) {
      toast({
        title: 'Error',
        description: `Failed to delete comment: ${response.error}`,
        variant: 'destructive',
      });
      return;
    }
    
    toast({
      title: 'Success',
      description: 'Comment deleted successfully',
    });

    await fetchTimeline();

    // Update count if we're fetching it on mount (to keep button in sync)
    if (fetchCountOnMount) {
      await fetchCommentCount();
    }
  };

  const handleEdit = (comment: Comment) => {
    setEditingComment(comment);
    
    // Parse audience tokens to extract teams and roles
    const teams: string[] = [];
    const roles: string[] = [];
    
    if (comment.audience) {
      comment.audience.forEach(token => {
        if (token.startsWith('team:')) {
          teams.push(token.substring(5));
        } else if (token.startsWith('role:')) {
          roles.push(token.substring(5));
        }
      });
    }
    
    setFormData({
      title: comment.title || '',
      comment: comment.comment,
      selectedTeams: teams,
      selectedRoles: roles,
    });
    setIsFormOpen(true);
  };

  const resetForm = () => {
    setFormData({ title: '', comment: '', selectedTeams: [], selectedRoles: [] });
    setEditingComment(null);
    setIsFormOpen(false);
  };

  // Fetch comment count on mount if requested
  useEffect(() => {
    if (fetchCountOnMount) {
      fetchCommentCount();
    }
  }, [fetchCountOnMount, fetchCommentCount]);

  // Fetch teams and roles when sidebar opens
  useEffect(() => {
    if (isOpen) {
      fetchTeams();
      fetchRoles();
      fetchTimeline();
    }
  }, [isOpen, entityType, entityId, filterType, currentProject?.id]);

  // Scroll to top when comment form opens
  useEffect(() => {
    if (isFormOpen && scrollAreaRef.current) {
      // Find the viewport element within the ScrollArea
      const viewport = scrollAreaRef.current.querySelector('[data-radix-scroll-area-viewport]');
      if (viewport) {
        viewport.scrollTo({ top: 0, behavior: 'smooth' });
      }
    }
  }, [isFormOpen]);

  const CommentForm = React.useMemo(() => (
    <form onSubmit={handleSubmit} className="space-y-4 p-4 border-t">
      <div>
        <Label htmlFor="title">Title (Optional)</Label>
        <Input
          id="title"
          value={formData.title}
          onChange={(e) => setFormData({ ...formData, title: e.target.value })}
          placeholder="Add a title for this comment..."
          className="mt-1"
        />
      </div>
      
      <div>
        <Label htmlFor="comment">Comment</Label>
        <Textarea
          id="comment"
          value={formData.comment}
          onChange={(e) => setFormData({ ...formData, comment: e.target.value })}
          placeholder="Write your comment..."
          className="mt-1"
          rows={3}
          required
        />
      </div>
      
      <div className="space-y-3">
        <div className="text-sm text-muted-foreground">
          Target specific teams or roles (optional). Leave empty for visibility to all project members.
        </div>
        
        {/* Teams multi-select */}
        <div>
          <Label htmlFor="teams">Teams</Label>
          <div className="mt-1 space-y-2">
            {availableTeams.map(team => (
              <div key={team.id} className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id={`team-${team.id}`}
                  checked={formData.selectedTeams.includes(team.id)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setFormData({ 
                        ...formData, 
                        selectedTeams: [...formData.selectedTeams, team.id] 
                      });
                    } else {
                      setFormData({ 
                        ...formData, 
                        selectedTeams: formData.selectedTeams.filter(id => id !== team.id) 
                      });
                    }
                  }}
                  className="rounded"
                />
                <Label htmlFor={`team-${team.id}`} className="text-sm font-normal">
                  {team.name}
                </Label>
              </div>
            ))}
            {availableTeams.length === 0 && (
              <div className="text-xs text-muted-foreground">No teams available in current project</div>
            )}
          </div>
        </div>

        {/* Roles multi-select */}
        <div>
          <Label htmlFor="roles">App Roles</Label>
          <div className="mt-1 space-y-2">
            {availableRoles.map(role => (
              <div key={role.name} className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id={`role-${role.name}`}
                  checked={formData.selectedRoles.includes(role.name)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setFormData({ 
                        ...formData, 
                        selectedRoles: [...formData.selectedRoles, role.name] 
                      });
                    } else {
                      setFormData({ 
                        ...formData, 
                        selectedRoles: formData.selectedRoles.filter(name => name !== role.name) 
                      });
                    }
                  }}
                  className="rounded"
                />
                <Label htmlFor={`role-${role.name}`} className="text-sm font-normal">
                  {role.name}
                </Label>
              </div>
            ))}
          </div>
        </div>
        
        {/* Display selected teams and roles */}
        {(formData.selectedTeams.length > 0 || formData.selectedRoles.length > 0) && (
          <div className="flex flex-wrap gap-1 mt-2">
            {formData.selectedTeams.map(teamId => {
              const team = availableTeams.find(t => t.id === teamId);
              return team ? (
                <Badge key={`team-${teamId}`} variant="secondary" className="text-xs">
                  <Users className="w-3 h-3 mr-1" />
                  Team: {team.name}
                </Badge>
              ) : null;
            })}
            {formData.selectedRoles.map(roleName => (
              <Badge key={`role-${roleName}`} variant="outline" className="text-xs">
                Role: {roleName}
              </Badge>
            ))}
          </div>
        )}
      </div>
      
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={loading}>
          <Send className="w-4 h-4 mr-1" />
          {editingComment ? 'Update' : 'Post'}
        </Button>
        {(editingComment || formData.title || formData.comment) && (
          <Button type="button" variant="outline" size="sm" onClick={resetForm}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  ), [formData, editingComment, loading, availableTeams, availableRoles, handleSubmit, resetForm]);

  const TimelineItem: React.FC<{ entry: TimelineEntry; canModify: boolean }> = ({ 
    entry, 
    canModify 
  }) => {
    const parsed = React.useMemo(() => {
      if (entry.type !== 'change') return null;
      try {
        const trimmed = (entry.content || '').trim();
        if (!trimmed || (trimmed[0] !== '{' && trimmed[0] !== '[')) return null;
        return JSON.parse(trimmed);
      } catch {
        return null;
      }
    }, [entry]);

    const renderParsedObject = (obj: any) => {
      // Special formatting for access_request_* actions
      const action = entry.metadata?.action || '';
      if (action.startsWith('access_request_')) {
        return (
          <div className="text-sm space-y-1">
            {obj.requester_email && (
              <div><span className="text-muted-foreground">Requester:</span> {obj.requester_email}</div>
            )}
            {obj.decision && (
              <div className="flex items-center gap-1">
                <span className="text-muted-foreground">Decision:</span>
                <Badge variant={obj.decision === 'approve' ? 'secondary' : obj.decision === 'deny' ? 'destructive' : 'outline'} className="text-xs">
                  {String(obj.decision)}
                </Badge>
              </div>
            )}
            {obj.message && (
              <div><span className="text-muted-foreground">Message:</span> {String(obj.message)}</div>
            )}
          </div>
        );
      }
      
      // Special formatting for semantic link changes
      if (action.startsWith('SEMANTIC_LINK_')) {
        const operation = action === 'SEMANTIC_LINK_ADD'
          ? 'linked'
          : action === 'SEMANTIC_LINK_REMOVE'
          ? 'unlinked'
          : action.toLowerCase();
        const iri = typeof obj?.iri === 'string' ? obj.iri : undefined;
        const linkId = typeof obj?.link_id === 'string' ? obj.link_id : undefined;
        return (
          <div className="text-sm space-y-1">
            {iri && (
              <div><span className="text-muted-foreground">Iri:</span> {iri}</div>
            )}
            {linkId && (
              <div><span className="text-muted-foreground">Link Id:</span> {linkId}</div>
            )}
            <div><span className="text-muted-foreground">Operation:</span> {operation}</div>
          </div>
        );
      }
      // Generic key/value renderer
      return (
        <div className="text-sm space-y-1">
          {Object.entries(obj).map(([k, v]) => (
            <div key={k} className="flex gap-1">
              <span className="text-muted-foreground capitalize">{k.replace(/_/g, ' ')}:</span>
              <span>{typeof v === 'string' ? v : JSON.stringify(v)}</span>
            </div>
          ))}
        </div>
      );
    };

    return (
      <div className={cn(
        "p-3 border rounded-lg space-y-2",
        entry.type === 'change' && "border-blue-200 bg-blue-50/50 dark:border-blue-800 dark:bg-blue-950/20"
      )}>
        <div className="flex items-center gap-2">
          {entry.type === 'comment' ? (
            <MessageSquare className="w-4 h-4 text-muted-foreground" />
          ) : (
            <Clock className="w-4 h-4 text-blue-600" />
          )}
          {entry.title && (
            <h4 className="font-medium text-sm">{entry.title}</h4>
          )}
          <Badge variant={entry.type === 'change' ? 'secondary' : 'outline'} className="text-xs">
            {entry.type}
          </Badge>
        </div>

        {parsed ? (
          renderParsedObject(parsed)
        ) : (
          <p className="text-sm text-foreground whitespace-pre-wrap">
            {entry.content}
          </p>
        )}

        {entry.audience && entry.audience.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {entry.audience.map((token, idx) => {
              // Parse audience tokens
              if (token.startsWith('team:')) {
                const teamId = token.substring(5);
                const team = availableTeams.find(t => t.id === teamId);
                return (
                  <Badge key={`${token}-${idx}`} variant="secondary" className="text-xs">
                    <Users className="w-3 h-3 mr-1" />
                    Team: {team?.name || teamId}
                  </Badge>
                );
              } else if (token.startsWith('role:')) {
                const roleName = token.substring(5);
                return (
                  <Badge key={`${token}-${idx}`} variant="outline" className="text-xs">
                    Role: {roleName}
                  </Badge>
                );
              } else {
                // Plain group token
                return (
                  <Badge key={`${token}-${idx}`} variant="outline" className="text-xs">
                    <Users className="w-3 h-3 mr-1" />
                    {token}
                  </Badge>
                );
              }
            })}
          </div>
        )}

        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <Avatar className="w-5 h-5">
              <div className="w-5 h-5 rounded-full bg-primary/10 flex items-center justify-center">
                {entry.username.charAt(0).toUpperCase()}
              </div>
            </Avatar>
            <span>{entry.username}</span>
            <RelativeDate date={new Date(entry.timestamp)} />
            {entry.updated_at && (
              <span className="italic">(edited)</span>
            )}
          </div>

          {canModify && entry.type === 'comment' && (
            <div className="flex gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0"
                onClick={() => handleEdit(entry as any)}
              >
                <Edit className="w-3 h-3" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0 text-destructive hover:text-destructive"
                onClick={() => handleDelete(entry.id)}
              >
                <Trash2 className="w-3 h-3" />
              </Button>
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <Sheet open={isOpen} onOpenChange={onToggle}>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm" className={cn("relative", className)}>
          <MessageSquare className="w-4 h-4 mr-1" />
          Comments
          {totalCount > 0 && (
            <Badge variant="secondary" className="ml-2 h-5 px-1 text-xs">
              {totalCount}
            </Badge>
          )}
        </Button>
      </SheetTrigger>
      
      <SheetContent side="right" className="w-full sm:max-w-lg flex flex-col h-full p-0">
        <SheetHeader className="p-4 pb-2">
          <SheetTitle className="flex items-center gap-2">
            <MessageSquare className="w-5 h-5" />
            Activity Timeline
            {totalCount > 0 && (
              <Badge variant="secondary" className="h-5 px-2 text-xs">
                {totalCount}
              </Badge>
            )}
          </SheetTitle>
          {currentProject && (
            <div className="flex items-center gap-1 text-xs text-muted-foreground mt-1">
              <FolderOpen className="w-3 h-3" />
              <span>Project: {currentProject.name}</span>
            </div>
          )}
          {!currentProject && (
            <div className="flex items-center gap-1 text-xs text-amber-600 mt-1">
              <FolderOpen className="w-3 h-3" />
              <span>No project context (global)</span>
            </div>
          )}
        </SheetHeader>
        
        {/* Filter Toolbar */}
        <div className="px-4 pb-2">
          <div className="flex items-center gap-2 mb-2">
            <Filter className="w-4 h-4 text-muted-foreground" />
            <span className="text-sm font-medium text-muted-foreground">Filter:</span>
          </div>
          <div className="flex gap-2">
            <Button
              variant={filterType === 'all' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setFilterType('all')}
              className="flex-1"
            >
              <FileText className="w-3 h-3 mr-1" />
              All
            </Button>
            <Button
              variant={filterType === 'comments' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setFilterType('comments')}
              className="flex-1"
            >
              <MessageSquare className="w-3 h-3 mr-1" />
              Comments
            </Button>
            <Button
              variant={filterType === 'changes' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setFilterType('changes')}
              className="flex-1"
            >
              <Clock className="w-3 h-3 mr-1" />
              Changes
            </Button>
          </div>
        </div>
        
        <div className="flex-1 flex flex-col min-h-0">
          <div className="p-4 pt-0">
            <Button 
              variant="outline" 
              size="sm" 
              onClick={() => setIsFormOpen(!isFormOpen)}
              className="w-full"
            >
              <Plus className="w-4 h-4 mr-1" />
              Add Comment
            </Button>
          </div>
          
          <Separator />
          
          <ScrollArea className="flex-1" ref={scrollAreaRef}>
            {isFormOpen && CommentForm}
            
            {timeline.length > 0 ? (
              <div className="p-4 space-y-3">
                {timeline.map(entry => (
                  <TimelineItem
                    key={entry.id}
                    entry={entry}
                    canModify={true} // TODO: Check actual permissions
                  />
                ))}
              </div>
            ) : (
              <div className="p-4 text-center text-muted-foreground">
                {filterType === 'comments' ? (
                  <>
                    <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p className="text-sm">No comments yet</p>
                    <p className="text-xs">Be the first to add a comment!</p>
                  </>
                ) : filterType === 'changes' ? (
                  <>
                    <Clock className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p className="text-sm">No changes recorded</p>
                    <p className="text-xs">Changes will appear here when they occur</p>
                  </>
                ) : (
                  <>
                    <FileText className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p className="text-sm">No activity yet</p>
                    <p className="text-xs">Comments and changes will appear here</p>
                  </>
                )}
              </div>
            )}
          </ScrollArea>
        </div>
      </SheetContent>
    </Sheet>
  );
};

export default CommentSidebar;