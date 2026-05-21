import { useEffect, useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import { PrincipalPicker } from '@/components/common/principal-picker'
import { buildContractTeamMember } from '@/lib/team-members'
import type { TeamMember } from '@/types/data-contract'

type TeamMemberFormProps = {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (member: TeamMember) => Promise<void>
  initial?: TeamMember
}

export default function TeamMemberFormDialog({ isOpen, onOpenChange, onSubmit, initial }: TeamMemberFormProps) {
  const { toast } = useToast()
  const [isSubmitting, setIsSubmitting] = useState(false)

  const [role, setRole] = useState('')
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')

  useEffect(() => {
    if (isOpen && initial) {
      setRole(initial.role || '')
      // Prefer email, fallback to username (for ODCS compatibility)
      setEmail(initial.email || initial.username || '')
      setName(initial.name || '')
    } else if (isOpen && !initial) {
      setRole('')
      setEmail('')
      setName('')
    }
  }, [isOpen, initial])

  const handleSubmit = async () => {
    if (!role.trim()) {
      toast({ title: 'Validation Error', description: 'Role is required', variant: 'destructive' })
      return
    }

    if (!email.trim()) {
      toast({ title: 'Validation Error', description: 'Email/Username is required', variant: 'destructive' })
      return
    }

    // Basic email validation (if it looks like an email)
    if (email.includes('@') && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      toast({ title: 'Validation Error', description: 'Please enter a valid email address', variant: 'destructive' })
      return
    }

    setIsSubmitting(true)
    try {
      const member: TeamMember = buildContractTeamMember({
        emailOrUsername: email,
        role,
        name,
      })

      await onSubmit(member)
      onOpenChange(false)
    } catch (error: any) {
      toast({
        title: 'Error',
        description: error?.message || 'Failed to save team member',
        variant: 'destructive',
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{initial ? 'Edit Team Member' : 'Add Team Member'}</DialogTitle>
          <DialogDescription>
            Add a team member responsible for this data contract.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="role">
              Role <span className="text-destructive">*</span>
            </Label>
            <Input
              id="role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="e.g., Data Owner, Steward, Engineer"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="email">
              Email/Username <span className="text-destructive">*</span>
            </Label>
            <PrincipalPicker
              id="email"
              accepts={['user']}
              value={email || null}
              onChange={(next) => setEmail(next ?? '')}
              placeholder="user@example.com or username"
              aria-label="Email or username"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Full name (optional)"
            />
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
  )
}
