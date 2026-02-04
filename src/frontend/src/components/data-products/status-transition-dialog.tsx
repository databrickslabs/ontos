import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useToast } from '@/hooks/use-toast';
import { AlertCircle, Info } from 'lucide-react';
import {
  getAllowedTransitions,
  getStatusConfig,
  validateTransition,
  getRecommendedAction,
} from '@/lib/odps-lifecycle';

interface StatusTransitionDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  currentStatus: string;
  onTransition: (targetStatus: string, notes?: string) => Promise<void>;
  productName?: string;
}

export default function StatusTransitionDialog({
  isOpen,
  onOpenChange,
  currentStatus,
  onTransition,
  productName,
}: StatusTransitionDialogProps) {
  const { toast } = useToast();
  const [selectedStatus, setSelectedStatus] = useState<string>('');
  const [notes, setNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const currentConfig = getStatusConfig(currentStatus);
  const allowedTransitions = getAllowedTransitions(currentStatus);
  const recommendedAction = getRecommendedAction(currentStatus);

  const handleSubmit = async () => {
    if (!selectedStatus) {
      toast({
        title: 'Validation Error',
        description: 'Please select a target status',
        variant: 'destructive',
      });
      return;
    }

    // Validate transition
    const validation = validateTransition(currentStatus, selectedStatus);
    if (!validation.valid) {
      toast({
        title: 'Invalid Transition',
        description: validation.error,
        variant: 'destructive',
      });
      return;
    }

    setIsSubmitting(true);
    try {
      await onTransition(selectedStatus, notes.trim() || undefined);
      onOpenChange(false);
      setSelectedStatus('');
      setNotes('');
    } catch (error: any) {
      toast({
        title: 'Transition Failed',
        description: error?.message || 'Failed to update product status',
        variant: 'destructive',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCancel = () => {
    setSelectedStatus('');
    setNotes('');
    onOpenChange(false);
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Change Product Status</DialogTitle>
          <DialogDescription>
            Transition the lifecycle status of {productName || 'this data product'} (ODPS v1.0.0)
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Current Status */}
          <div className="rounded-lg border bg-muted/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Label className="text-base font-semibold">Current Status:</Label>
              <span className="text-2xl">{currentConfig.icon}</span>
              <span className="font-medium">{currentConfig.label}</span>
            </div>
            <p className="text-sm text-muted-foreground">{currentConfig.description}</p>
          </div>

          {/* Recommended Action */}
          {recommendedAction && (
            <Alert>
              <Info className="h-4 w-4" />
              <AlertDescription>
                <strong>Recommended:</strong> {recommendedAction}
              </AlertDescription>
            </Alert>
          )}

          {/* Target Status Selection */}
          {allowedTransitions.length > 0 ? (
            <div className="space-y-3">
              <Label className="text-base">Select Target Status <span className="text-destructive">*</span></Label>
              <RadioGroup value={selectedStatus} onValueChange={setSelectedStatus}>
                {allowedTransitions.map((status) => {
                  const config = getStatusConfig(status);
                  return (
                    <div key={status} className="flex items-center space-x-2 rounded-lg border p-4 hover:bg-muted/50 transition-colors">
                      <RadioGroupItem value={status} id={status} />
                      <label
                        htmlFor={status}
                        className="flex-1 cursor-pointer"
                      >
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xl">{config.icon}</span>
                          <span className="font-medium">{config.label}</span>
                        </div>
                        <p className="text-sm text-muted-foreground">{config.description}</p>
                      </label>
                    </div>
                  );
                })}
              </RadioGroup>
            </div>
          ) : (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                <strong>Terminal State:</strong> No transitions available from {currentConfig.label} status.
                This product cannot be changed to any other status.
              </AlertDescription>
            </Alert>
          )}

          {/* Transition Notes */}
          {allowedTransitions.length > 0 && (
            <div className="space-y-2">
              <Label htmlFor="notes">Transition Notes (Optional)</Label>
              <Textarea
                id="notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Add notes about why this status change is being made..."
                rows={3}
              />
              <p className="text-xs text-muted-foreground">
                These notes will be logged for audit purposes
              </p>
            </div>
          )}

          {/* Lifecycle Diagram */}
          <div className="rounded-lg border p-4 bg-muted/20">
            <Label className="text-sm font-semibold mb-2 block">ODPS v1.0.0 Lifecycle Flow:</Label>
            <div className="flex items-center gap-2 text-sm font-mono flex-wrap">
              <span className={currentStatus.toLowerCase() === 'proposed' ? 'font-bold text-primary' : ''}>proposed</span>
              <span>→</span>
              <span className={currentStatus.toLowerCase() === 'draft' ? 'font-bold text-primary' : ''}>draft</span>
              <span>→</span>
              <span className={currentStatus.toLowerCase() === 'active' ? 'font-bold text-primary' : ''}>active</span>
              <span>→</span>
              <span className={currentStatus.toLowerCase() === 'deprecated' ? 'font-bold text-primary' : ''}>deprecated</span>
              <span>→</span>
              <span className={currentStatus.toLowerCase() === 'retired' ? 'font-bold text-primary' : ''}>retired</span>
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              Current status is highlighted. Emergency deprecation is allowed from any status.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleCancel} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isSubmitting || !selectedStatus || allowedTransitions.length === 0}
          >
            {isSubmitting ? 'Updating...' : 'Update Status'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
