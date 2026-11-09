import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';
import type { Support } from '@/types/data-product';

type SupportChannelFormProps = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (support: Support) => Promise<void>;
  initial?: Support;
};

const SUPPORT_TOOLS = ['email', 'slack', 'teams', 'discord', 'ticket', 'other'];
const SUPPORT_SCOPES = ['interactive', 'announcements', 'issues'];

export default function SupportChannelFormDialog({ isOpen, onOpenChange, onSubmit, initial }: SupportChannelFormProps) {
  const { t } = useTranslation(['data-products', 'common']);
  const { toast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [channel, setChannel] = useState('');
  const [url, setUrl] = useState('');
  const [description, setDescription] = useState('');
  const [tool, setTool] = useState('slack');
  const [scope, setScope] = useState('interactive');
  const [invitationUrl, setInvitationUrl] = useState('');

  useEffect(() => {
    if (isOpen && initial) {
      setChannel(initial.channel || '');
      setUrl(initial.url || '');
      setDescription(initial.description || '');
      setTool(initial.tool || 'slack');
      setScope(initial.scope || 'interactive');
      setInvitationUrl(initial.invitationUrl || '');
    } else if (isOpen && !initial) {
      setChannel('');
      setUrl('');
      setDescription('');
      setTool('slack');
      setScope('interactive');
      setInvitationUrl('');
    }
  }, [isOpen, initial]);

  const handleSubmit = async () => {
    if (!channel.trim()) {
      toast({ title: 'Validation Error', description: 'Channel name is required', variant: 'destructive' });
      return;
    }

    if (!url.trim()) {
      toast({ title: 'Validation Error', description: 'URL is required', variant: 'destructive' });
      return;
    }

    // URL validation
    try {
      new URL(url.trim());
    } catch {
      toast({ title: 'Validation Error', description: 'Please enter a valid URL', variant: 'destructive' });
      return;
    }

    // Invitation URL validation if provided
    if (invitationUrl.trim()) {
      try {
        new URL(invitationUrl.trim());
      } catch {
        toast({ title: 'Validation Error', description: 'Please enter a valid invitation URL', variant: 'destructive' });
        return;
      }
    }

    setIsSubmitting(true);
    try {
      const support: Support = {
        channel: channel.trim(),
        url: url.trim(),
        description: description.trim() || undefined,
        tool: tool || undefined,
        scope: scope || undefined,
        invitationUrl: invitationUrl.trim() || undefined,
      };

      await onSubmit(support);
      onOpenChange(false);
      toast({
        title: 'Success',
        description: initial ? 'Support channel updated' : 'Support channel added',
      });
    } catch (error: any) {
      toast({
        title: 'Error',
        description: error?.message || 'Failed to save support channel',
        variant: 'destructive',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{initial ? 'Edit Support Channel' : 'Add Support Channel'}</DialogTitle>
          <DialogDescription>
            Define a support channel for users of this data product (ODPS v1.0.0).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="channel">
              Channel Name <span className="text-destructive">*</span>
            </Label>
            <Input
              id="channel"
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
              placeholder={t('data-products:supportChannelForm.channelNamePlaceholder')}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="url">
              Access URL <span className="text-destructive">*</span>
            </Label>
            <Input
              id="url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t('data-products:supportChannelForm.accessUrlPlaceholder')}
            />
            <p className="text-xs text-muted-foreground">
              URL to access this support channel
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="tool">{t('data-products:supportChannelForm.tool')}</Label>
              <Select value={tool} onValueChange={setTool}>
                <SelectTrigger id="tool">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SUPPORT_TOOLS.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t.charAt(0).toUpperCase() + t.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="scope">{t('data-products:supportChannelForm.scope')}</Label>
              <Select value={scope} onValueChange={setScope}>
                <SelectTrigger id="scope">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SUPPORT_SCOPES.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s.charAt(0).toUpperCase() + s.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="invitationUrl">{t('data-products:supportChannelForm.invitationUrl')}</Label>
            <Input
              id="invitationUrl"
              type="url"
              value={invitationUrl}
              onChange={(e) => setInvitationUrl(e.target.value)}
              placeholder={t('data-products:supportChannelForm.invitationUrlPlaceholder')}
            />
            <p className="text-xs text-muted-foreground">
              Optional invitation link for new members
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">{t('common:labels.description')}</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('data-products:supportChannelForm.descriptionPlaceholder')}
              rows={3}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? 'Saving...' : initial ? 'Save Changes' : 'Add Channel'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
