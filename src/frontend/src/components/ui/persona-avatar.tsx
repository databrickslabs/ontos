import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { cn } from '@/lib/utils';
import type { PersonaDisplay } from '@/lib/persona-display';

interface PersonaAvatarProps {
  display: PersonaDisplay;
  className?: string;
  /** Ring in the persona colour (header chip). */
  ring?: boolean;
}

/** A test persona's avatar: image when available, else initials on the persona colour. */
export function PersonaAvatar({ display, className, ring = false }: PersonaAvatarProps) {
  return (
    <Avatar
      className={cn('h-8 w-8 shrink-0', className)}
      style={ring ? { boxShadow: `0 0 0 2px hsl(var(--background)), 0 0 0 4px ${display.color}` } : undefined}
    >
      {display.avatarUrl && <AvatarImage src={display.avatarUrl} alt="" className="object-cover" />}
      <AvatarFallback className="font-semibold text-white" style={{ backgroundColor: display.color }}>
        {display.initials}
      </AvatarFallback>
    </Avatar>
  );
}
