import { Navigation } from './navigation';
import { SidebarBrand } from './sidebar-brand';
import { SidebarPoweredBy } from './sidebar-powered-by';
import { cn } from '@/lib/utils';

interface SidebarProps {
  isCollapsed: boolean;
}

export function Sidebar({ isCollapsed }: SidebarProps) {
  return (
    <aside
      className={cn(
        'fixed inset-y-0 left-0 z-50 flex flex-col border-r bg-sidebar transition-all duration-300 ease-in-out overflow-x-hidden',
        isCollapsed ? 'w-14' : 'w-60' // Adjust width based on state
      )}
    >
      {/* Logo/Branding */}
      <SidebarBrand isCollapsed={isCollapsed} />

      {/* Navigation */}
      <div className="flex-1 overflow-y-auto">
         <Navigation isCollapsed={isCollapsed} />
      </div>

      {/* "Powered by Ontos" while a custom brand is active */}
      <SidebarPoweredBy isCollapsed={isCollapsed} />
    </aside>
  );
}
