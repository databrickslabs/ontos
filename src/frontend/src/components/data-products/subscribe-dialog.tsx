import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { Loader2, Bell } from 'lucide-react';
import { useUserStore } from '@/stores/user-store';

// subscribe on behalf of group / SP. The form picks one of:
//   - "self": current user
//   - "my_group": one of the user's own groups (validated client-side via /user/details)
//   - "other": free-text group display name or SP applicationId/displayName.
//              Backend validates against workspace SCIM and returns 400 when
//              the principal does not exist.
type ObOMode = 'self' | 'my_group' | 'other';

interface SubscribeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  productId: string;
  productName: string;
  onSuccess?: () => void;
}

export default function SubscribeDialog({
  open,
  onOpenChange,
  productId,
  productName,
  onSuccess,
}: SubscribeDialogProps) {
  const { toast } = useToast();
  const userInfo = useUserStore((s) => s.userInfo);
  const fetchUserInfo = useUserStore((s) => s.fetchUserInfo);

  const [reason, setReason] = useState('');
  const [oboMode, setOboMode] = useState<ObOMode>('self');
  const [oboGroup, setOboGroup] = useState<string>(''); // selected group from user's groups
  const [oboOther, setOboOther] = useState<string>(''); // free text — group name or SP id
  const [oboOtherType, setOboOtherType] = useState<'group' | 'service_principal'>('group');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const entityType = 'Data Product';
  const apiEndpoint = `/api/data-products/${productId}/subscribe`;

  // Pull user details so the "for a group I'm part of" picker is populated.
  useEffect(() => {
    if (open && !userInfo) {
      fetchUserInfo().catch(() => {});
    }
  }, [open, userInfo, fetchUserInfo]);

  const myGroups = (userInfo?.groups ?? []).filter((g) => !!g);

  // Submit button is disabled if the chosen mode is missing its required value.
  const submitDisabled =
    isSubmitting ||
    (oboMode === 'my_group' && !oboGroup) ||
    (oboMode === 'other' && !oboOther.trim());

  const buildOnBehalfOf = (): { type: string; value: string } | undefined => {
    if (oboMode === 'self') return undefined;
    if (oboMode === 'my_group') {
      return { type: 'group', value: oboGroup };
    }
    // 'other' — user supplies free text + SP/group toggle
    return { type: oboOtherType, value: oboOther.trim() };
  };

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      const payload: { reason?: string; on_behalf_of?: { type: string; value: string } } = {
        reason: reason.trim() || undefined,
      };
      const obo = buildOnBehalfOf();
      if (obo) payload.on_behalf_of = obo;

      const response = await fetch(apiEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Failed to subscribe (${response.status})`);
      }

      const successDescription = obo
        ? `You are now subscribed to "${productName}" on behalf of ${obo.type === 'group' ? 'group ' : 'service principal '}"${obo.value}".`
        : `You are now subscribed to "${productName}". You'll receive notifications about updates and changes.`;
      toast({ title: 'Subscribed!', description: successDescription });

      // Reset form
      setReason('');
      setOboMode('self');
      setOboGroup('');
      setOboOther('');
      setOboOtherType('group');
      onOpenChange(false);
      onSuccess?.();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to subscribe';
      toast({ title: 'Subscription Failed', description: message, variant: 'destructive' });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    if (!isSubmitting) {
      setReason('');
      setOboMode('self');
      setOboGroup('');
      setOboOther('');
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bell className="h-5 w-5 text-primary" />
            Subscribe to {entityType}
          </DialogTitle>
          <DialogDescription>
            Subscribe to <span className="font-medium">{productName}</span> to receive notifications about updates, changes, and compliance status.
          </DialogDescription>
        </DialogHeader>

        <div className="py-4 space-y-4">
          <div>
            <Label className="text-sm font-medium">Subscribe as</Label>
            <RadioGroup
              className="mt-2 space-y-2"
              value={oboMode}
              onValueChange={(v) => setOboMode(v as ObOMode)}
              disabled={isSubmitting}
            >
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="self" id="obo-self" />
                <Label htmlFor="obo-self" className="font-normal cursor-pointer">
                  For myself
                </Label>
              </div>

              <div className="space-y-2">
                <div className="flex items-center space-x-2">
                  <RadioGroupItem
                    value="my_group"
                    id="obo-my-group"
                    disabled={myGroups.length === 0}
                  />
                  <Label
                    htmlFor="obo-my-group"
                    className={`font-normal cursor-pointer ${myGroups.length === 0 ? 'text-muted-foreground' : ''}`}
                  >
                    For a group I'm part of
                    {myGroups.length === 0 && (
                      <span className="ml-1 text-xs">(no groups available)</span>
                    )}
                  </Label>
                </div>
                {oboMode === 'my_group' && myGroups.length > 0 && (
                  <div className="ml-6">
                    <Select value={oboGroup} onValueChange={setOboGroup}>
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Select one of your groups" />
                      </SelectTrigger>
                      <SelectContent>
                        {myGroups.map((g) => (
                          <SelectItem key={g} value={g}>
                            {g}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <div className="flex items-center space-x-2">
                  <RadioGroupItem value="other" id="obo-other" />
                  <Label htmlFor="obo-other" className="font-normal cursor-pointer">
                    Other group or service principal
                  </Label>
                </div>
                {oboMode === 'other' && (
                  <div className="ml-6 space-y-2">
                    <Select
                      value={oboOtherType}
                      onValueChange={(v) => setOboOtherType(v as 'group' | 'service_principal')}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="group">Group (display name)</SelectItem>
                        <SelectItem value="service_principal">Service principal (display name or applicationId)</SelectItem>
                      </SelectContent>
                    </Select>
                    <Input
                      placeholder={oboOtherType === 'group' ? 'e.g., sales_consumers' : 'e.g., 11111111-2222-3333-4444-555555555555'}
                      value={oboOther}
                      onChange={(e) => setOboOther(e.target.value)}
                      disabled={isSubmitting}
                    />
                    <p className="text-xs text-muted-foreground">
                      Will be validated against the workspace directory before the request is recorded.
                    </p>
                  </div>
                )}
              </div>
            </RadioGroup>
          </div>

          <div>
            <Label htmlFor="reason" className="text-sm font-medium">
              Why are you subscribing? <span className="text-muted-foreground">(optional)</span>
            </Label>
            <Textarea
              id="reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="E.g., Need this data for quarterly reporting, building a dashboard, etc."
              className="mt-2 min-h-[80px]"
              disabled={isSubmitting}
            />
            <p className="text-xs text-muted-foreground mt-2">
              This helps data owners understand how their products are being used.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={submitDisabled}>
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Subscribing...
              </>
            ) : (
              <>
                <Bell className="mr-2 h-4 w-4" />
                Subscribe
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
