import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { useTranslation } from 'react-i18next';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { 
  Zap,
  Shield,
  UserCheck,
  Bell,
  Tag,
  Code,
  CheckCircle,
  XCircle,
  ClipboardCheck,
  // Truck - unused
  GitBranch,
  FileSearch,
  Globe,
} from 'lucide-react';
import type { WorkflowStep, WorkflowTrigger } from '@/types/process-workflow';
import { 
  getTriggerTypeLabel, 
  getEntityTypeLabel,
  // getStepIcon - unused
  // getStepColor - unused
  resolveRecipientDisplay,
  // STEP_ICONS - unused
  // STEP_COLORS - unused
} from '@/lib/workflow-labels';

// Base node styles - fixed width for consistent compact sizing
const baseNodeClass = "rounded-lg shadow-md border-2 w-[180px] transition-all hover:shadow-lg"

// Node color configurations for consistent dark mode styling
// Each node type has a distinct color theme with proper contrast
const nodeColorStyles = {
  trigger: {
    card: "border-purple-500 bg-purple-50 dark:bg-purple-900/50 dark:border-purple-400",
    icon: "text-purple-600 dark:text-purple-300",
    ring: "ring-purple-500 dark:ring-purple-400",
    handle: "!bg-purple-500 dark:!bg-purple-400",
  },
  validation: {
    card: "border-blue-500 bg-blue-50 dark:bg-blue-900/50 dark:border-blue-400",
    icon: "text-blue-600 dark:text-blue-300",
    ring: "ring-blue-500 dark:ring-blue-400",
  },
  approval: {
    card: "border-amber-500 bg-amber-50 dark:bg-amber-900/50 dark:border-amber-400",
    icon: "text-amber-600 dark:text-amber-300",
    ring: "ring-amber-500 dark:ring-amber-400",
  },
  notification: {
    card: "border-cyan-500 bg-cyan-50 dark:bg-cyan-900/50 dark:border-cyan-400",
    icon: "text-cyan-600 dark:text-cyan-300",
    ring: "ring-cyan-500 dark:ring-cyan-400",
  },
  assignTag: {
    card: "border-teal-500 bg-teal-50 dark:bg-teal-900/50 dark:border-teal-400",
    icon: "text-teal-600 dark:text-teal-300",
    ring: "ring-teal-500 dark:ring-teal-400",
  },
  conditional: {
    card: "border-violet-500 bg-violet-50 dark:bg-violet-900/50 dark:border-violet-400",
    icon: "text-violet-600 dark:text-violet-300",
    ring: "ring-violet-500 dark:ring-violet-400",
  },
  script: {
    card: "border-slate-500 bg-slate-100 dark:bg-slate-800/70 dark:border-slate-400",
    icon: "text-slate-600 dark:text-slate-300",
    ring: "ring-slate-500 dark:ring-slate-400",
  },
  policyCheck: {
    card: "border-indigo-500 bg-indigo-50 dark:bg-indigo-900/50 dark:border-indigo-400",
    icon: "text-indigo-600 dark:text-indigo-300",
    ring: "ring-indigo-500 dark:ring-indigo-400",
  },
  pass: {
    card: "border-green-500 bg-green-50 dark:bg-green-900/50 dark:border-green-400",
    icon: "text-green-600 dark:text-green-300",
    ring: "ring-green-500 dark:ring-green-400",
  },
  fail: {
    card: "border-red-500 bg-red-50 dark:bg-red-900/50 dark:border-red-400",
    icon: "text-red-600 dark:text-red-300",
    ring: "ring-red-500 dark:ring-red-400",
  },
  webhook: {
    card: "border-orange-500 bg-orange-50 dark:bg-orange-900/50 dark:border-orange-400",
    icon: "text-orange-600 dark:text-orange-300",
    ring: "ring-orange-500 dark:ring-orange-400",
  },
} as const;

// Shared text styles for better dark mode visibility
const nodeTextStyles = {
  title: "text-sm font-medium text-foreground",
  description: "text-xs text-muted-foreground dark:text-slate-300",
  badge: "text-xs",
};

// Trigger Node
interface TriggerNodeData {
  trigger: WorkflowTrigger;
}

export const TriggerNode = memo(({ data, selected }: NodeProps<TriggerNodeData>) => {
  const { t } = useTranslation(['common']);
  const trigger = data.trigger;
  const styles = nodeColorStyles.trigger;

  return (
    <Card className={`${baseNodeClass} ${styles.card} ${selected ? `ring-2 ${styles.ring}` : ''}`}>
      <CardHeader className="p-3 pb-2">
        <CardTitle className={`${nodeTextStyles.title} flex items-center gap-2`}>
          <Zap className={`h-4 w-4 ${styles.icon}`} />
          {t('common:labels.type')}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        <div className={nodeTextStyles.description}>
          {getTriggerTypeLabel(trigger.type, t)}
        </div>
        <div className="flex flex-wrap gap-1 mt-1">
          {trigger.entity_types.slice(0, 3).map(et => (
            <Badge key={et} variant="secondary" className="text-xs px-1 py-0 dark:bg-purple-800/50 dark:text-purple-200">
              {getEntityTypeLabel(et, t)}
            </Badge>
          ))}
          {trigger.entity_types.length > 3 && (
            <Badge variant="secondary" className="text-xs px-1 py-0 dark:bg-purple-800/50 dark:text-purple-200">
              +{trigger.entity_types.length - 3}
            </Badge>
          )}
        </div>
      </CardContent>
      <Handle type="source" position={Position.Bottom} className={styles.handle} />
    </Card>
  );
});
TriggerNode.displayName = 'TriggerNode';

// Base Step Node Component
interface StepNodeData {
  step: WorkflowStep;
  rolesMap?: Record<string, string>;  // UUID -> name mapping for display
}

const StepNodeBase = memo(({ 
  data, 
  selected, 
  icon: Icon, 
  color, 
  hasPassHandle = true,
  hasFailHandle = true,
}: NodeProps<StepNodeData> & { 
  icon: React.ElementType;
  color: string;
  hasPassHandle?: boolean;
  hasFailHandle?: boolean;
}) => {
  const step = data.step;
  
  return (
    <Card className={`${baseNodeClass} border-${color}-500 bg-${color}-50 dark:bg-${color}-950/30 ${selected ? `ring-2 ring-${color}-500` : ''}`}
      style={{ borderColor: `var(--${color}-500, #6b7280)` }}>
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      <CardHeader className="p-3 pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Icon className={`h-4 w-4 text-${color}-500`} />
          {step.name || step.step_type}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        <Badge variant="outline" className="text-xs">
          {step.step_type.replace('_', ' ')}
        </Badge>
        {step.config && Object.keys(step.config).length > 0 && (
          <div className="text-xs text-muted-foreground mt-1 truncate max-w-[140px]">
            {JSON.stringify(step.config).slice(0, 30)}...
          </div>
        )}
      </CardContent>
      {hasPassHandle && (
        <Handle 
          type="source" 
          position={Position.Bottom} 
          id="pass" 
          className="!bg-green-500"
          style={{ left: hasFailHandle ? '30%' : '50%' }}
        />
      )}
      {hasFailHandle && (
        <Handle 
          type="source" 
          position={Position.Bottom} 
          id="fail" 
          className="!bg-red-500"
          style={{ left: '70%' }}
        />
      )}
    </Card>
  );
});
StepNodeBase.displayName = 'StepNodeBase';

// Validation Node
export const ValidationNode = memo((props: NodeProps<StepNodeData>) => {
  const styles = nodeColorStyles.validation;
  return (
    <Card className={`${baseNodeClass} ${styles.card} ${props.selected ? `ring-2 ${styles.ring}` : ''}`}>
      <Handle type="target" position={Position.Top} className="!bg-slate-400 dark:!bg-slate-500" />
      <CardHeader className="p-3 pb-2">
        <CardTitle className={`${nodeTextStyles.title} flex items-center gap-2`}>
          <Shield className={`h-4 w-4 ${styles.icon}`} />
          {props.data.step.name || 'Validation'}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        <Badge variant="outline" className="text-xs dark:border-blue-400/50 dark:text-blue-200">validation</Badge>
        {(props.data.step.config as { rule?: string })?.rule && (
          <div className={`${nodeTextStyles.description} mt-1 truncate max-w-[140px] font-mono`}>
            {((props.data.step.config as { rule?: string }).rule || '').slice(0, 25)}...
          </div>
        )}
      </CardContent>
      <Handle type="source" position={Position.Bottom} id="pass" className="!bg-green-500 dark:!bg-green-400" style={{ left: '30%' }} />
      <Handle type="source" position={Position.Bottom} id="fail" className="!bg-red-500 dark:!bg-red-400" style={{ left: '70%' }} />
    </Card>
  );
});
ValidationNode.displayName = 'ValidationNode';

// Approval Node
export const ApprovalNode = memo((props: NodeProps<StepNodeData>) => {
  const approversValue = (props.data.step.config as { approvers?: string })?.approvers;
  const displayName = resolveRecipientDisplay(approversValue, props.data.rolesMap || {});
  const styles = nodeColorStyles.approval;
  
  return (
    <Card className={`${baseNodeClass} ${styles.card} ${props.selected ? `ring-2 ${styles.ring}` : ''}`}>
      <Handle type="target" position={Position.Top} className="!bg-slate-400 dark:!bg-slate-500" />
      <CardHeader className="p-3 pb-2">
        <CardTitle className={`${nodeTextStyles.title} flex items-center gap-2`}>
          <UserCheck className={`h-4 w-4 ${styles.icon}`} />
          {props.data.step.name || 'Approval'}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        <Badge variant="outline" className="text-xs dark:border-amber-400/50 dark:text-amber-200">approval</Badge>
        {approversValue && (
          <div className={nodeTextStyles.description + " mt-1"}>
            {displayName}
          </div>
        )}
      </CardContent>
      <Handle type="source" position={Position.Bottom} id="pass" className="!bg-green-500 dark:!bg-green-400" style={{ left: '30%' }} />
      <Handle type="source" position={Position.Bottom} id="fail" className="!bg-red-500 dark:!bg-red-400" style={{ left: '70%' }} />
    </Card>
  );
});
ApprovalNode.displayName = 'ApprovalNode';

// Notification Node
export const NotificationNode = memo((props: NodeProps<StepNodeData>) => {
  const recipientsValue = (props.data.step.config as { recipients?: string })?.recipients;
  const displayName = resolveRecipientDisplay(recipientsValue, props.data.rolesMap || {});
  const styles = nodeColorStyles.notification;
  
  return (
    <Card className={`${baseNodeClass} ${styles.card} ${props.selected ? `ring-2 ${styles.ring}` : ''}`}>
      <Handle type="target" position={Position.Top} className="!bg-slate-400 dark:!bg-slate-500" />
      <CardHeader className="p-3 pb-2">
        <CardTitle className={`${nodeTextStyles.title} flex items-center gap-2`}>
          <Bell className={`h-4 w-4 ${styles.icon}`} />
          {props.data.step.name || 'Notification'}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        <Badge variant="outline" className="text-xs dark:border-cyan-400/50 dark:text-cyan-200">notification</Badge>
        {recipientsValue && (
          <div className={nodeTextStyles.description + " mt-1"}>
            To: {displayName}
          </div>
        )}
      </CardContent>
      <Handle type="source" position={Position.Bottom} id="pass" className="!bg-green-500 dark:!bg-green-400" />
    </Card>
  );
});
NotificationNode.displayName = 'NotificationNode';

// Assign Tag Node
export const AssignTagNode = memo((props: NodeProps<StepNodeData>) => {
  const styles = nodeColorStyles.assignTag;
  return (
    <Card className={`${baseNodeClass} ${styles.card} ${props.selected ? `ring-2 ${styles.ring}` : ''}`}>
      <Handle type="target" position={Position.Top} className="!bg-slate-400 dark:!bg-slate-500" />
      <CardHeader className="p-3 pb-2">
        <CardTitle className={`${nodeTextStyles.title} flex items-center gap-2`}>
          <Tag className={`h-4 w-4 ${styles.icon}`} />
          {props.data.step.name || 'Assign Tag'}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        <Badge variant="outline" className="text-xs dark:border-teal-400/50 dark:text-teal-200">assign_tag</Badge>
        {(props.data.step.config as { key?: string })?.key && (
          <div className={nodeTextStyles.description + " mt-1"}>
            Key: {(props.data.step.config as { key?: string }).key}
          </div>
        )}
      </CardContent>
      <Handle type="source" position={Position.Bottom} id="pass" className="!bg-green-500 dark:!bg-green-400" />
    </Card>
  );
});
AssignTagNode.displayName = 'AssignTagNode';

// Conditional Node
export const ConditionalNode = memo((props: NodeProps<StepNodeData>) => {
  const styles = nodeColorStyles.conditional;
  return (
    <Card className={`${baseNodeClass} ${styles.card} ${props.selected ? `ring-2 ${styles.ring}` : ''}`}>
      <Handle type="target" position={Position.Top} className="!bg-slate-400 dark:!bg-slate-500" />
      <CardHeader className="p-3 pb-2">
        <CardTitle className={`${nodeTextStyles.title} flex items-center gap-2`}>
          <GitBranch className={`h-4 w-4 ${styles.icon}`} />
          {props.data.step.name || 'Conditional'}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        <Badge variant="outline" className="text-xs dark:border-violet-400/50 dark:text-violet-200">conditional</Badge>
        {(props.data.step.config as { condition?: string })?.condition && (
          <div className={`${nodeTextStyles.description} mt-1 truncate max-w-[140px] font-mono`}>
            {((props.data.step.config as { condition?: string }).condition || '').slice(0, 25)}...
          </div>
        )}
      </CardContent>
      <Handle type="source" position={Position.Bottom} id="pass" className="!bg-green-500 dark:!bg-green-400" style={{ left: '30%' }} />
      <Handle type="source" position={Position.Bottom} id="fail" className="!bg-red-500 dark:!bg-red-400" style={{ left: '70%' }} />
    </Card>
  );
});
ConditionalNode.displayName = 'ConditionalNode';

// Script Node
export const ScriptNode = memo((props: NodeProps<StepNodeData>) => {
  const styles = nodeColorStyles.script;
  return (
    <Card className={`${baseNodeClass} ${styles.card} ${props.selected ? `ring-2 ${styles.ring}` : ''}`}>
      <Handle type="target" position={Position.Top} className="!bg-slate-400 dark:!bg-slate-500" />
      <CardHeader className="p-3 pb-2">
        <CardTitle className={`${nodeTextStyles.title} flex items-center gap-2`}>
          <Code className={`h-4 w-4 ${styles.icon}`} />
          {props.data.step.name || 'Script'}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        <Badge variant="outline" className="text-xs dark:border-slate-400/50 dark:text-slate-200">
          {(props.data.step.config as { language?: string })?.language || 'script'}
        </Badge>
      </CardContent>
      <Handle type="source" position={Position.Bottom} id="pass" className="!bg-green-500 dark:!bg-green-400" style={{ left: '30%' }} />
      <Handle type="source" position={Position.Bottom} id="fail" className="!bg-red-500 dark:!bg-red-400" style={{ left: '70%' }} />
    </Card>
  );
});
ScriptNode.displayName = 'ScriptNode';

// End Node (Pass/Fail)
export const EndNode = memo((props: NodeProps<StepNodeData>) => {
  const isPass = props.data.step.step_type === 'pass';
  const Icon = isPass ? CheckCircle : XCircle;
  const styles = isPass ? nodeColorStyles.pass : nodeColorStyles.fail;
  
  return (
    <Card className={`${baseNodeClass} ${styles.card} ${props.selected ? `ring-2 ${styles.ring}` : ''}`}>
      <Handle type="target" position={Position.Top} className="!bg-slate-400 dark:!bg-slate-500" />
      <CardHeader className="p-3 pb-2">
        <CardTitle className={`${nodeTextStyles.title} flex items-center gap-2`}>
          <Icon className={`h-4 w-4 ${styles.icon}`} />
          {props.data.step.name || (isPass ? 'Success' : 'Failure')}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        <Badge 
          variant={isPass ? 'default' : 'destructive'} 
          className={`text-xs ${isPass ? 'dark:bg-green-600 dark:text-green-50' : 'dark:bg-red-600 dark:text-red-50'}`}
        >
          {isPass ? 'pass' : 'fail'}
        </Badge>
        {!isPass && (props.data.step.config as { message?: string })?.message && (
          <div className={nodeTextStyles.description + " mt-1"}>
            {(props.data.step.config as { message?: string }).message}
          </div>
        )}
      </CardContent>
    </Card>
  );
});
EndNode.displayName = 'EndNode';

// Policy Check Node
export const PolicyCheckNode = memo((props: NodeProps<StepNodeData>) => {
  const policyName = (props.data.step.config as { policy_name?: string })?.policy_name;
  const policyId = (props.data.step.config as { policy_id?: string })?.policy_id;
  const styles = nodeColorStyles.policyCheck;
  
  return (
    <Card className={`${baseNodeClass} ${styles.card} ${props.selected ? `ring-2 ${styles.ring}` : ''}`}>
      <Handle type="target" position={Position.Top} className="!bg-slate-400 dark:!bg-slate-500" />
      <CardHeader className="p-3 pb-2">
        <CardTitle className={`${nodeTextStyles.title} flex items-center gap-2`}>
          <ClipboardCheck className={`h-4 w-4 ${styles.icon}`} />
          {props.data.step.name || 'Policy Check'}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        <Badge variant="outline" className="text-xs dark:border-indigo-400/50 dark:text-indigo-200">policy_check</Badge>
        {policyName && (
          <div className={nodeTextStyles.description + " mt-1"}>
            Policy: {policyName}
          </div>
        )}
        {!policyName && policyId && (
          <div className={`${nodeTextStyles.description} mt-1 truncate max-w-[140px]`}>
            ID: {policyId.slice(0, 8)}...
          </div>
        )}
        {!policyName && !policyId && (
          <div className="text-xs text-amber-600 dark:text-amber-400 mt-1">
            No policy selected
          </div>
        )}
      </CardContent>
      <Handle type="source" position={Position.Bottom} id="pass" className="!bg-green-500 dark:!bg-green-400" style={{ left: '30%' }} />
      <Handle type="source" position={Position.Bottom} id="fail" className="!bg-red-500 dark:!bg-red-400" style={{ left: '70%' }} />
    </Card>
  );
});
PolicyCheckNode.displayName = 'PolicyCheckNode';

export const CreateAssetReviewNode = memo((props: NodeProps<StepNodeData>) => {
  const reviewerRole = (props.data.step.config as { reviewer_role?: string })?.reviewer_role;
  const reviewType = (props.data.step.config as { review_type?: string })?.review_type;
  const displayRole = resolveRecipientDisplay(reviewerRole, props.data.rolesMap || {});
  const styles = nodeColorStyles.assignTag; // Reuse teal theme
  
  return (
    <Card className={`${baseNodeClass} ${styles.card} ${props.selected ? `ring-2 ${styles.ring}` : ''}`}>
      <Handle type="target" position={Position.Top} className="!bg-slate-400 dark:!bg-slate-500" />
      <CardHeader className="p-3 pb-2">
        <CardTitle className={`${nodeTextStyles.title} flex items-center gap-2`}>
          <FileSearch className={`h-4 w-4 ${styles.icon}`} />
          {props.data.step.name || 'Asset Review'}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0 space-y-1">
        <p className={`${nodeTextStyles.description} truncate`} title={displayRole}>
          <span className="font-medium text-foreground">Reviewer:</span> {displayRole || 'Not set'}
        </p>
        {reviewType && (
          <Badge variant="outline" className="text-xs dark:border-teal-400/50 dark:text-teal-200">
            {reviewType}
          </Badge>
        )}
      </CardContent>
      <Handle type="source" position={Position.Bottom} id="pass" className="!bg-green-500 dark:!bg-green-400 !-bottom-2" />
    </Card>
  );
});

CreateAssetReviewNode.displayName = 'CreateAssetReviewNode';

// Webhook Node - calls external HTTP endpoints
export const WebhookNode = memo((props: NodeProps<StepNodeData>) => {
  const connectionName = (props.data.step.config as { connection_name?: string })?.connection_name;
  const url = (props.data.step.config as { url?: string })?.url;
  const method = (props.data.step.config as { method?: string })?.method || 'POST';
  const styles = nodeColorStyles.webhook;
  
  // Determine display text - prefer connection name, fallback to URL
  const displayTarget = connectionName 
    ? `Connection: ${connectionName}`
    : url 
      ? url.length > 30 ? url.slice(0, 27) + '...' : url
      : 'Not configured';
  
  return (
    <Card className={`${baseNodeClass} ${styles.card} ${props.selected ? `ring-2 ${styles.ring}` : ''}`}>
      <Handle type="target" position={Position.Top} className="!bg-slate-400 dark:!bg-slate-500" />
      <CardHeader className="p-3 pb-2">
        <CardTitle className={`${nodeTextStyles.title} flex items-center gap-2`}>
          <Globe className={`h-4 w-4 ${styles.icon}`} />
          {props.data.step.name || 'Webhook'}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0 space-y-1">
        <Badge variant="outline" className="text-xs dark:border-orange-400/50 dark:text-orange-200">
          {method}
        </Badge>
        <p className={`${nodeTextStyles.description} truncate`} title={connectionName || url}>
          {displayTarget}
        </p>
        {!connectionName && !url && (
          <div className="text-xs text-amber-600 dark:text-amber-400">
            Configure URL or Connection
          </div>
        )}
      </CardContent>
      <Handle type="source" position={Position.Bottom} id="pass" className="!bg-green-500 dark:!bg-green-400" style={{ left: '30%' }} />
      <Handle type="source" position={Position.Bottom} id="fail" className="!bg-red-500 dark:!bg-red-400" style={{ left: '70%' }} />
    </Card>
  );
});

WebhookNode.displayName = 'WebhookNode';
