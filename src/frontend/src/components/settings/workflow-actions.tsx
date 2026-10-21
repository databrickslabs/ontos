import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Play, Square, Pause, Loader2, CheckCircle2, XCircle, Clock, Minus } from 'lucide-react';
import { WorkflowStatus } from '@/types/workflows';

interface WorkflowActionsProps {
  status: WorkflowStatus;
  onStart: () => Promise<void> | void;
  onStop: () => Promise<void> | void;
  onPause?: () => Promise<void> | void;
  onResume?: () => Promise<void> | void;
}

export function WorkflowActions({ status, onStart, onStop, onPause, onResume }: WorkflowActionsProps) {
  const { t } = useTranslation(['settings', 'common']);
  const renderLastResultIcon = () => {
    if (status.is_running) return null;
    switch (status.last_result) {
      case 'SUCCESS':
        return <CheckCircle2 className="h-4 w-4 text-green-500" />;
      case 'FAILED':
        return <XCircle className="h-4 w-4 text-red-500" />;
      case 'PENDING':
        return <Clock className="h-4 w-4 text-yellow-500" />;
      case 'CANCELED':
      case 'TIMEDOUT':
        return <Minus className="h-4 w-4 text-gray-400" />;
      default:
        return null;
    }
  };

  return (
    <TooltipProvider>
      <div className="flex items-center gap-2">
        {/* Running spinner */}
        {status.is_running && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}

        {/* State-specific combinations */}
        {status.is_running ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onStop}>
                <Square className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t('settings:workflows.actions.stop')}</TooltipContent>
          </Tooltip>
        ) : status.supports_pause ? (
          status.pause_status === 'PAUSED' ? (
            <div className="flex items-center gap-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => onStart()}>
                    <Play className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('settings:workflows.actions.start')}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => onResume && onResume()}>
                    <Play className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('settings:workflows.actions.unpause')}</TooltipContent>
              </Tooltip>
            </div>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => onPause && onPause()}>
                  <Pause className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t('settings:workflows.actions.pause')}</TooltipContent>
            </Tooltip>
          )
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onStart}>
                <Play className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t('settings:workflows.actions.start')}</TooltipContent>
          </Tooltip>
        )}

        {/* Last result icon (hidden when running) */}
        {renderLastResultIcon()}
      </div>
    </TooltipProvider>
  );
}

export default WorkflowActions;


