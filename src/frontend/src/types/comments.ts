export enum CommentStatus {
  ACTIVE = "active",
  DELETED = "deleted"
}

export type CommentType = 'comment' | 'rating';

export interface Comment {
  id: string;
  entity_id: string;
  entity_type: string;
  title?: string | null;
  comment: string;
  audience?: string[] | null; // Audience tokens: plain groups, 'team:<team_id>', or 'role:<role_name>'
  project_id?: string | null; // Project ID to scope the comment
  status: CommentStatus;
  comment_type: CommentType;
  rating?: number | null; // 1-5 stars (only for rating type)
  created_by: string;
  updated_by?: string | null;
  created_at: string; // ISO string format
  updated_at: string; // ISO string format
}

export interface CommentCreate {
  entity_id: string;
  entity_type: string;
  title?: string | null;
  comment: string;
  audience?: string[] | null; // Audience tokens: plain groups, 'team:<team_id>', or 'role:<role_name>'
  project_id?: string | null; // Project ID to scope the comment
}

export interface CommentUpdate {
  title?: string | null;
  comment?: string | null;
  audience?: string[] | null;
}

export interface CommentListResponse {
  comments: Comment[];
  total_count: number;
  visible_count: number; // Number of comments visible to current user
}

export interface CommentPermissions {
  can_modify: boolean;
  is_admin: boolean;
}

// Props for comment-related components
export interface CommentSidebarProps {
  entityType: string;
  entityId: string;
  isOpen: boolean;
  onToggle: () => void;
  className?: string;
  fetchCountOnMount?: boolean;
}

export interface CommentItemProps {
  comment: Comment;
  canModify: boolean;
  onEdit: (comment: Comment) => void;
  onDelete: (commentId: string) => void;
}

// Types for audience selection
export interface AudienceTeam {
  id: string;
  name: string;
}

/**
 * App role as returned by /api/workflows/roles.
 * ``id`` is the UUID string used for ``role_id:<uuid>`` audience tokens.
 * ``source`` distinguishes "app" (RBAC) from "business" roles.
 */
export interface AudienceRole {
  id: string;
  name: string;
  description?: string | null;
  source?: 'app' | 'business' | string;
}

// Rating-related types
export interface RatingCreate {
  entity_id: string;
  entity_type: string;
  rating: number; // 1-5
  comment?: string | null; // Optional review text
  project_id?: string | null;
}

export interface RatingAggregation {
  entity_type: string;
  entity_id: string;
  average_rating: number;
  total_ratings: number;
  distribution: Record<number, number>; // {1: count, 2: count, ..., 5: count}
  user_current_rating?: number | null; // Current user's latest rating
}