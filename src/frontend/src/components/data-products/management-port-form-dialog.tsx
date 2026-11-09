import { useEffect, useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from 'react-i18next';
import type { ManagementPort } from '@/types/data-product';

type ManagementPortFormProps = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (port: ManagementPort) => Promise<void>;
  initial?: ManagementPort;
};

const MANAGEMENT_PORT_CONTENTS = ['discoverability', 'observability', 'control', 'dictionary'];
const MANAGEMENT_PORT_TYPES = ['rest', 'topic'];

export default function ManagementPortFormDialog({ isOpen, onOpenChange, onSubmit, initial }: ManagementPortFormProps) {
  const { toast } = useToast();
  const { t } = useTranslation(['data-products', 'common']);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [name, setName] = useState('');
  const [content, setContent] = useState('observability');
  const [type, setType] = useState('rest');
  const [url, setUrl] = useState('');
  const [channel, setChannel] = useState('');
  const [description, setDescription] = useState('');

  useEffect(() => {
    if (isOpen && initial) {
      setName(initial.name || '');
      setContent(initial.content || 'observability');
      setType(initial.type || 'rest');
      setUrl(initial.url || '');
      setChannel(initial.channel || '');
      setDescription(initial.description || '');
    } else if (isOpen && !initial) {
      setName('');
      setContent('observability');
      setType('rest');
      setUrl('');
      setChannel('');
      setDescription('');
    }
  }, [isOpen, initial]);

  const handleSubmit = async () => {
    if (!name.trim()) {
      toast({ title: 'Validation Error', description: 'Port name is required', variant: 'destructive' });
      return;
    }

    if (!content.trim()) {
      toast({ title: 'Validation Error', description: 'Content type is required', variant: 'destructive' });
      return;
    }

    // URL validation if provided
    if (url.trim()) {
      try {
        new URL(url.trim());
      } catch {
        toast({ title: 'Validation Error', description: 'Please enter a valid URL', variant: 'destructive' });
        return;
      }
    }

    setIsSubmitting(true);
    try {
      const port: ManagementPort = {
        name: name.trim(),
        content: content.trim(),
        type: type || 'rest',
        url: url.trim() || undefined,
        channel: channel.trim() || undefined,
        description: description.trim() || undefined,
      };

      await onSubmit(port);
      onOpenChange(false);
      toast({
        title: 'Success',
        description: initial ? 'Management port updated' : 'Management port added',
      });
    } catch (error: any) {
      toast({
        title: 'Error',
        description: error?.message || 'Failed to save management port',
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
          <DialogTitle>{initial ? t('data-products:managementPortForm.editTitle') : t('data-products:managementPortForm.addTitle')}</DialogTitle>
          <DialogDescription>
            {t('data-products:managementPortForm.description')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="name">
              {t('data-products:managementPortForm.labels.portName')} <span className="text-destructive">*</span>
            </Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('data-products:managementPortForm.placeholders.name')}
              autoFocus
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="content">
                {t('data-products:managementPortForm.labels.contentType')} <span className="text-destructive">*</span>
              </Label>
              <Select value={content} onValueChange={setContent}>
                <SelectTrigger id="content">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MANAGEMENT_PORT_CONTENTS.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c.charAt(0).toUpperCase() + c.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Purpose of this management port
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="type">{t('data-products:managementPortForm.labels.portType')}</Label>
              <Select value={type} onValueChange={setType}>
                <SelectTrigger id="type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MANAGEMENT_PORT_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t.toUpperCase()}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="url">{t('data-products:managementPortForm.labels.url')}</Label>
            <Input
              id="url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t('data-products:managementPortForm.placeholders.url')}
            />
            <p className="text-xs text-muted-foreground">
              Access URL for this management port
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="channel">{t('data-products:managementPortForm.labels.channel')}</Label>
            <Input
              id="channel"
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
              placeholder={t('data-products:managementPortForm.placeholders.channel')}
            />
            <p className="text-xs text-muted-foreground">
              Communication channel identifier
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">{t('common:labels.description')}</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('data-products:managementPortForm.placeholders.description')}
              rows={3}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? 'Saving...' : initial ? 'Save Changes' : 'Add Port'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
