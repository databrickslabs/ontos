import { useEffect, useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';
import { PrincipalPicker } from '@/components/common/principal-picker';
import type { TeamMember } from '@/types/data-product';

type TeamMemberFormProps = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (member: TeamMember) => Promise<void>;
  initial?: TeamMember;
};

export default function TeamMemberFormDialog({ isOpen, onOpenChange, onSubmit, initial }: TeamMemberFormProps) {
  const { toast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [username, setUsername] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [role, setRole] = useState('');
  const [dateIn, setDateIn] = useState('');
  const [dateOut, setDateOut] = useState('');

  useEffect(() => {
    if (isOpen && initial) {
      setUsername(initial.username || '');
      setName(initial.name || '');
      setDescription(initial.description || '');
      setRole(initial.role || '');
      setDateIn(initial.dateIn || '');
      setDateOut(initial.dateOut || '');
    } else if (isOpen && !initial) {
      setUsername('');
      setName('');
      setDescription('');
      setRole('');
      setDateIn('');
      setDateOut('');
    }
  }, [isOpen, initial]);

  const handleSubmit = async () => {
    if (!username.trim()) {
      toast({ title: 'Validation Error', description: 'Username is required', variant: 'destructive' });
      return;
    }

    setIsSubmitting(true);
    try {
      const member: TeamMember = {
        username: username.trim(),
        name: name.trim() || undefined,
        description: description.trim() || undefined,
        role: role.trim() || undefined,
        dateIn: dateIn || undefined,
        dateOut: dateOut || undefined,
      };

      await onSubmit(member);
      onOpenChange(false);
      toast({
        title: 'Success',
        description: initial ? 'Team member updated' : 'Team member added',
      });
    } catch (error: any) {
      toast({
        title: 'Error',
        description: error?.message || 'Failed to save team member',
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
          <DialogTitle>{initial ? 'Edit Team Member' : 'Add Team Member'}</DialogTitle>
          <DialogDescription>
            Add a team member responsible for this data product (ODPS v1.0.0).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="username">
              Username <span className="text-destructive">*</span>
            </Label>
            <PrincipalPicker
              id="username"
              accepts={['user']}
              value={username || null}
              onChange={(next) => setUsername(next ?? '')}
              placeholder="e.g., user@example.com or username"
              aria-label="Username"
            />
            <p className="text-xs text-muted-foreground">
              User&apos;s username or email address (REQUIRED in ODPS)
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="name">Full Name</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Full name (optional)"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="role">Role</Label>
            <Input
              id="role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="e.g., owner, data steward, contributor"
            />
            <p className="text-xs text-muted-foreground">
              User's role in the team (e.g., owner, data steward, contributor)
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Additional information about this team member"
              rows={2}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="dateIn">Date Joined</Label>
              <Input
                id="dateIn"
                type="date"
                value={dateIn}
                onChange={(e) => setDateIn(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="dateOut">Date Left</Label>
              <Input
                id="dateOut"
                type="date"
                value={dateOut}
                onChange={(e) => setDateOut(e.target.value)}
              />
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? 'Saving...' : initial ? 'Save Changes' : 'Add Member'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
